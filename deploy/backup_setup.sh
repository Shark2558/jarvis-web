#!/usr/bin/env bash
# deploy/backup_setup.sh -- the owner's one-time step for backups (docs/plans/r14-hardening.md D3,
# D4, owner steps 1-7). Two modes, fixed at R14 I0 so Parts A and D can't drift:
#
#   bash deploy/backup_setup.sh --status   READ ONLY, always exit 0: what is set up now (the
#                                          deploy calls only this; it never makes a schedule, a
#                                          binding or protection, and never spends anything)
#   bash deploy/backup_setup.sh            the set-up: shows the cost lines, waits for YES, then
#                                          the daily schedule kept 7 days, delete protection on
#                                          (default), and the drill's three grants for jarvis-run
#
# The drill's grants (least privilege, D4): the custom role jarvisDrillCleanup
# (datastore.databases.get, .getMetadata, .update, .delete) ONLY with the condition
# resource.name=="projects/P/databases/jarvis-drill", granted FIRST; only once it is bound,
# roles/datastore.restoreAdmin (restore into a NEW database; it can't delete or overwrite one) and
# roles/datastore.backupSchedulesViewer, so the drill never gets a restore it couldn't clean up.
# Never datastore.owner. If Google ignored the condition the drill copy could not be deleted
# (JARVIS says so) and (default) is still safe: delete protection is on and no other grant can
# delete it. The database name jarvis-drill is the drill's: a database by that name is deleted.
# Nothing here changes without a typed YES; each step that Google refuses says "could not" and
# the rest go on. gcloud never prompts (CLOUDSDK_CORE_DISABLE_PROMPTS) and never reads what he
# types (its stdin is /dev/null); a project id that isn't one is never passed to it.
set -euo pipefail
export CLOUDSDK_CORE_DISABLE_PROMPTS=1

LIVE_DB="(default)"
DRILL_DB="jarvis-drill"
ROLE_ID="jarvisDrillCleanup"
ROLE_PERMS="datastore.databases.get,datastore.databases.getMetadata,datastore.databases.update,datastore.databases.delete"
PROJECT_ID_RE='^([a-z][a-z0-9.-]*:)?[a-z][a-z0-9-]{4,28}[a-z0-9]$'
NOT_DAILY="on, but not daily kept 7 days (send this to the Workshop)"
GCLOUD_ERROR="could not read (gcloud error: is the project right and are you signed in?)"
COST_LINES=(
  "Backups: about ₹4 a month at 100 MB, about ₹40 at 1 GB (Google's charge; JARVIS shows the real figure after the first copy)."
  "Monthly restore drill: about ₹2 at 100 MB, never over ₹100 a drill (you may ask for 2 more a month)."
  "Google keeps each daily copy 7 days, so a thing you delete stays in the copies up to 7 days."
  "The drill uses a throw-away database named jarvis-drill: JARVIS deletes any database by that name."
)

gc() { gcloud "$@" </dev/null; }  # never a prompt, never his typing

project() {
  local p
  p="$(gc config get-value project 2>/dev/null || true)"
  if [[ "$p" =~ $PROJECT_ID_RE ]]; then echo "$p"; fi
}
run_sa() { echo "serviceAccount:jarvis-run@${1}.iam.gserviceaccount.com"; }

schedules_json() {  # gcloud's own exit status: failing is "could not read", not "not set up"
  gc firestore backups schedules list --database="$LIVE_DB" --format=json 2>/dev/null
}

schedule_word() {  # daily7 | other | none, from the JSON on stdin (no python3: other)
  if ! command -v python3 >/dev/null 2>&1; then echo "other"; return 0; fi
  python3 -I -c '
import json, sys
try:
    found = json.loads(sys.stdin.read() or "[]")
except ValueError:
    found = []
daily = any("dailyRecurrence" in s and s.get("retention") == "604800s" for s in found)
print("daily7" if daily else ("other" if found else "none"))'
}

protection_of() {  # ENABLED / DISABLED, read from JSON so no argument names the verb
  local got
  got="$(gc firestore databases describe --database="$LIVE_DB" --format=json 2>/dev/null)" || return 1
  grep -o 'PROTECTION_[A-Z]*' <<<"$got" | head -n 1 | sed 's/^PROTECTION_//' || true
}

grants_of() {
  gc projects get-iam-policy "$1" --flatten='bindings[].members' \
    --filter="bindings.members:$(run_sa "$1")" \
    --format='value(bindings.role,bindings.condition.expression)' 2>/dev/null
}

access_word() {  # "on" when all three grants are there, the custom one only on jarvis-drill
  local g="$1"
  if grep -q 'roles/datastore.restoreAdmin' <<<"$g" \
    && grep -q 'roles/datastore.backupSchedulesViewer' <<<"$g" \
    && grep -q "roles/${ROLE_ID}.*databases/${DRILL_DB}\"" <<<"$g"; then
    echo "on"
  else
    echo "not yet"
  fi
}

backups_line() {
  local json
  if ! json="$(schedules_json)"; then echo "Backups: ${GCLOUD_ERROR}"; return 0; fi
  case "$(schedule_word <<<"$json")" in
    daily7) echo "Backups: on, kept 7 days" ;;
    other) echo "Backups: ${NOT_DAILY}" ;;
    *) echo "Backups: not set up (the one-time step: bash deploy/backup_setup.sh)" ;;
  esac
}

status() {
  local p prot grants
  p="$(project)"
  if [[ -z "$p" ]]; then
    echo "Backups: could not read the project (run: gcloud config set project YOUR_PROJECT_ID)"
    return 0
  fi
  backups_line
  if ! prot="$(protection_of)"; then
    echo "Delete protection: ${GCLOUD_ERROR}"
  elif [[ "$prot" == "ENABLED" ]]; then
    echo "Delete protection: on"
  else
    echo "Delete protection: off or unknown"
  fi
  if grants="$(grants_of "$p")"; then
    echo "Drill access: $(access_word "$grants")"
  else
    echo "Drill access: ${GCLOUD_ERROR}"
  fi
  return 0
}

bind() {  # project member role condition: a new role can take a few seconds to be visible
  local tries="${BIND_TRIES:-3}"
  for ((n = 1; n <= tries; n++)); do
    gc projects add-iam-policy-binding "$1" --member="$2" --role="$3" --condition="$4" \
      --quiet >/dev/null 2>&1 && return 0
    sleep "${BIND_SLEEP:-5}"
  done
  return 1
}

make_schedule() {  # prints what Backups is: "on, kept 7 days" or the not-daily words
  local json word
  json="$(schedules_json)" || return 1
  word="$(schedule_word <<<"$json")"
  if [[ "$word" == "other" ]]; then echo "$NOT_DAILY"; return 0; fi  # his own: kept
  if [[ "$word" == "none" ]]; then
    gc firestore backups schedules create --database="$LIVE_DB" --recurrence=daily \
      --retention=7d --quiet >/dev/null || return 1
  fi
  echo "on, kept 7 days"
}

protect_live() {
  gc firestore databases update --database="$LIVE_DB" --delete-protection --quiet >/dev/null
}

cleanup_role() {
  local p="$1"
  if gc iam roles describe "$ROLE_ID" --project="$p" >/dev/null 2>&1; then
    gc iam roles update "$ROLE_ID" --project="$p" --permissions="$ROLE_PERMS" --quiet >/dev/null
  else
    gc iam roles create "$ROLE_ID" --project="$p" --title="JARVIS drill clean-up" \
      --description="Deletes only the restore drill's throw-away copy" \
      --permissions="$ROLE_PERMS" --stage=GA --quiet >/dev/null
  fi
}

grant_drill() {  # the clean-up grant first: no restore is granted that couldn't be cleaned up
  local p="$1" member cond
  member="$(run_sa "$p")"
  cleanup_role "$p" || return 1
  cond="expression=resource.name==\"projects/${p}/databases/${DRILL_DB}\",title=jarvis-drill only"
  bind "$p" "$member" "projects/${p}/roles/${ROLE_ID}" "$cond" || return 1
  bind "$p" "$member" roles/datastore.restoreAdmin None || return 1
  bind "$p" "$member" roles/datastore.backupSchedulesViewer None || return 1
  [[ "$(access_word "$(grants_of "$p" || true)")" == "on" ]]
}

setup() {
  local line answer p backups="could not turn on" protection="could not" access="could not"
  for line in "${COST_LINES[@]}"; do
    echo "$line"
  done
  printf 'Type YES to go on (anything else stops with nothing changed): '
  IFS= read -r answer || answer=""
  if [[ "$answer" != "YES" ]]; then
    echo "Stopped. Nothing was changed."
    return 0
  fi
  p="$(project)"
  if [[ -z "$p" ]]; then
    echo "Could not tell which project this is. Run: gcloud config set project YOUR_PROJECT_ID. Nothing was changed."
    return 0
  fi
  backups="$(make_schedule)" || backups="could not turn on"
  protect_live && protection="on"
  grant_drill "$p" && access="on"
  echo "Backups: ${backups} · Delete protection: ${protection} · Drill access: ${access}"
  echo "If a line says \"could not\" or \"send this\", send this screen to the Workshop; nothing else breaks."
  return 0
}

case "${1:-}" in
  --status) status ;;
  "") setup ;;
  *) echo "usage: bash deploy/backup_setup.sh [--status]" >&2; exit 2 ;;
esac
