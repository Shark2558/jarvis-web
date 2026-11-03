#!/usr/bin/env bash
# deploy/cloudrun.sh — deploy JARVIS to Google Cloud Run from Cloud Shell. Safe to re-run.
#
# Does: enable APIs → store secrets in Secret Manager → build from this repo → deploy a PUBLIC
# URL (the app does its own Google sign-in, owner-only) capped at ONE instance and scale-to-zero.
# Google tools (slice 6): the owner links Calendar + Gmail from the console. Their tokens are
# stored encrypted (AES-256-GCM) under the key in secret jarvis-token-key, generated here once.
# Memory: conversations, pending approvals and the audit chain live in Firestore (Native mode)
# in THIS project, region asia-south1, inside the free tier. No key: the service account is used.
# Runs as its own service account (jarvis-run), which may read only JARVIS's own secrets (granted
# per secret) and use Firestore. After a successful deploy the build account (default compute
# account) has those two permissions removed. Note: an OLD revision (before slice 5) ran as the
# build account, so rolling back to one would fail to start; roll forward instead.
# Why still one instance: rate limiting and the per-conversation write queue are per process.
# Raise --max-instances only after sessions gain a cross-process concurrency check.
#
# Re-runs ask nothing: answers are kept in the live service and Secret Manager. To change them:
#   bash deploy/cloudrun.sh --reconfigure
# The one exception is a NEW optional feature that has no saved answer yet: web search (slice 10)
# asks once for a Tavily key (Enter = skip; the skip is remembered). To be asked again:
#   bash deploy/cloudrun.sh --web-search
# Step 7 sets up deploy-on-merge: GitHub Actions proves who it is with a short-lived token
# (Workload Identity Federation) that Google accepts only from this repository's main branch.
# No key exists. The deployer account may only roll out new revisions of this service, push
# images to the build repository, and run them as jarvis-run. Inherent to any deploy-on-merge:
# whoever can change main can ship code that runs as jarvis-run (secrets, memory, audit), so
# protect main (pull requests only, no force-push) and keep your GitHub account on 2-step sign-in.
# Step 8 sets up the morning brief's clock (slice 7): one Cloud Scheduler job (3 jobs are free per
# billing account) calls JARVIS every 30 minutes from 04:00 to 11:30, signed with a Google token for
# its own account jarvis-scheduler, which has NO project roles: all it can do is prove to JARVIS
# "I am your clock". JARVIS decides whether the owner's brief is due. If this step fails, JARVIS
# still works and makes the brief when the Brief panel is opened.
# Voice (slice 9): JARVIS speaks with Google Cloud Text-to-Speech and listens with Speech-to-Text
# v1, as jarvis-run (no key). Step 2 switches both APIs on and step 5 lets jarvis-run use the
# project's services (serviceusage.serviceUsageConsumer) — each in its own command that may fail
# (an organisation policy can block them) without stopping the deploy. Free up to 90 % of Google's
# monthly allowance; above it the cost counts toward the owner's monthly limit in rupees. Without
# them the console falls back to the browser's own voice.
# --reconfigure rewrites ALL settings and secret bindings from your answers (it does not merge).
set -euo pipefail

SERVICE="${SERVICE:-jarvis}"
REGION="${REGION:-asia-south1}"   # Mumbai; Tier-1 region, covered by the monthly free allowance
GH_REPO="Shark2558/jarvis-web"
GH_REPO_ID="1441253681"           # numeric id: survives renames, can't be re-registered by others
POOL="github"; PROVIDER="jarvis-web"; AR_REPO="cloud-run-source-deploy"
BRIEF_JOB="jarvis-morning-brief"
BRIEF_TZ="${BRIEF_TZ:-Asia/Kolkata}"   # the clock's window (04:00-11:30) is read in this time zone

RECONFIGURE=no; ASK_WEB=no
for arg in "$@"; do
  case "$arg" in
    --reconfigure) RECONFIGURE=yes ;;
    --web-search) ASK_WEB=yes ;;
    -h|--help) echo "Usage: bash deploy/cloudrun.sh [--reconfigure] [--web-search]"; exit 0 ;;
    *) printf 'Unknown option: %s (try --help)\n' "$arg" >&2; exit 2 ;;
  esac
done

say() { printf '\n\033[1m%s\033[0m\n' "$*"; }
die() { printf '\nERROR: %s\n' "$*" >&2; exit 1; }

command -v gcloud >/dev/null || die "gcloud not found. Run this inside Google Cloud Shell."
PROJECT="$(gcloud config get-value project 2>/dev/null || true)"
[ -n "$PROJECT" ] && [ "$PROJECT" != "(unset)" ] || die "No project selected. Run: gcloud config set project YOUR_PROJECT_ID"
PROJECT_NUMBER="$(gcloud projects describe "$PROJECT" --format='value(projectNumber)')"
BASE_URL="https://${SERVICE}-${PROJECT_NUMBER}.${REGION}.run.app"

BILLING="$(gcloud billing projects describe "$PROJECT" --format='value(billingEnabled)' 2>/dev/null || true)"
[ "$BILLING" = "True" ] || die "Billing is not enabled on project $PROJECT. Cloud Run needs a billing account (you stay inside the free allowance). Enable it in Billing, then re-run."

say "1/8  Project: $PROJECT   Region: $REGION   Address will be: $BASE_URL"

say "2/8  Switching on the Google services JARVIS needs (takes ~1 minute)"
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com \
  secretmanager.googleapis.com firestore.googleapis.com iam.googleapis.com \
  iamcredentials.googleapis.com sts.googleapis.com \
  calendar-json.googleapis.com gmail.googleapis.com tasks.googleapis.com --quiet
# Voice (slice 9) on its own: an organisation policy may block these, and JARVIS works without them.
gcloud services enable texttospeech.googleapis.com speech.googleapis.com --quiet \
  || say "Note: the Google speech APIs could not be switched on; the browser voice will be used."
# Google Drive (slice 12) on its own too: JARVIS reads folders you share with it, as jarvis-run.
# JARVIS_DRIVE is on for this deploy only when the Drive API was switched on in THIS run.
DRIVE_STATE=off
if gcloud services enable drive.googleapis.com --quiet; then
  DRIVE_STATE=on
else
  say "Note: the Google Drive API could not be switched on, so Drive is off for this deploy. Re-run this script to try again."
fi
# Contacts (slice 12): People API for contacts_search; WhatsApp drafts to typed numbers work without.
gcloud services enable people.googleapis.com --quiet \
  || say "Note: the People API could not be switched on; contact look-ups stay off."

# Quick (prompt-free) only for a service this script fully set up before: it has the owner set.
QUICK=no
if [ "$RECONFIGURE" = no ] && \
   SVC_JSON="$(gcloud run services describe "$SERVICE" --region "$REGION" --format=json 2>/dev/null)" && \
   printf '%s' "$SVC_JSON" | grep -q '"JARVIS_OWNER_EMAILS"'; then
  QUICK=yes
fi

secret_exists() { gcloud secrets describe "$1" >/dev/null 2>&1; }
put_secret() { # name value
  if secret_exists "$1"; then printf '%s' "$2" | gcloud secrets versions add "$1" --data-file=- --quiet >/dev/null
  else printf '%s' "$2" | gcloud secrets create "$1" --data-file=- --replication-policy=automatic --quiet >/dev/null; fi
}
ask_secret() { # secret-name prompt
  local v=""; read -r -s -p "$2: " v; echo
  if [ -z "$v" ]; then secret_exists "$1" || die "$2 is required."; else put_secret "$1" "$v"; fi
}
rand() { head -c 48 /dev/urandom | base64 | tr -d '\n=+/' | head -c 48; }
rand_key() { head -c 32 /dev/urandom | base64 | tr -d '\n'; }   # exactly 32 bytes: AES-256 key

if [ "$QUICK" = yes ]; then
say "3/8  Using your saved answers - nothing to type (to change them: bash deploy/cloudrun.sh --reconfigure)"
else
say "3/8  Your details (typing is hidden for secrets; Enter keeps the saved value on a re-run)"
read -r -p "Your Gmail address (the only account allowed to sign in): " OWNER_EMAIL
[ -n "$OWNER_EMAIL" ] || die "Gmail address is required."
read -r -p "Google OAuth Client ID (ends with .apps.googleusercontent.com): " CLIENT_ID
[ -n "$CLIENT_ID" ] || die "Client ID is required."
ask_secret jarvis-google-client-secret "Google OAuth Client secret"
echo
echo "AI brains. You can set up several and switch between them from the dropdown in JARVIS."
echo "For each one: paste the key, or press Enter to keep a saved key, or type 'skip' to leave it out."
# optional_secret secret-name prompt  -> sets HAVE_SECRET=yes|no (no subshell: a gcloud failure must stop the script)
optional_secret() {
  local v=""; read -r -s -p "$2: " v; echo
  case "$v" in
    skip|SKIP|Skip|none|NONE|None) HAVE_SECRET=no; SECRET_SOURCE=none ;;
    "") if secret_exists "$1"; then echo "  (keeping the saved key in secret $1)"; HAVE_SECRET=yes; SECRET_SOURCE=saved
        else HAVE_SECRET=no; SECRET_SOURCE=none; fi ;;
    *) put_secret "$1" "$v" || die "Could not store the key in Secret Manager ($1)."; HAVE_SECRET=yes; SECRET_SOURCE=new ;;
  esac
}
BRAIN_ENV=""; BRAIN_SECRET=""; HAVE=""
optional_secret jarvis-anthropic-key "Claude - Anthropic API key (sk-ant-..., needs prepaid credit)"
if [ "$HAVE_SECRET" = yes ]; then
  BRAIN_SECRET="${BRAIN_SECRET}JARVIS_ANTHROPIC_API_KEY=jarvis-anthropic-key:latest,"; HAVE="${HAVE}anthropic "
fi
optional_secret jarvis-gemini-key "Gemini - API key from aistudio.google.com/apikey (free; made in a NEW project)"
if [ "$HAVE_SECRET" = yes ]; then
  BRAIN_SECRET="${BRAIN_SECRET}JARVIS_GEMINI_API_KEY=jarvis-gemini-key:latest,"; HAVE="${HAVE}gemini "
fi
echo
read -r -p "Add an OpenAI-compatible brain (Groq, OpenRouter, Ollama via tunnel)? Type y or press Enter for no: " ADD_CUSTOM
if [ "${ADD_CUSTOM:-n}" = "y" ] || [ "${ADD_CUSTOM:-n}" = "Y" ]; then
  read -r -p "  Base URL (e.g. https://api.groq.com/openai/v1): " C_URL
  read -r -p "  Model id for everyday chat (e.g. llama-3.3-70b-versatile): " C_MODEL
  read -r -p "  Name to show in the dropdown [Custom]: " C_LABEL; C_LABEL="${C_LABEL:-Custom}"
  read -r -p "  May this vendor use your messages to improve its products? y = yes/unsure (tools stay off), n = no [y]: " C_TRAIN
  C_TRAIN_BOOL=true
  case "${C_TRAIN:-y}" in n|N) C_TRAIN_BOOL=false ;; esac
  [ -n "$C_URL" ] && [ -n "$C_MODEL" ] || die "Base URL and model id are required for the custom brain."
  case "$C_URL" in
    https://*) ;;
    http://localhost*|http://127.0.0.1*|http://*.internal*|http://*.ts.net*) ;;
    *) die "Base URL must start with https:// (plain http is only allowed for local addresses)." ;;
  esac
  # The saved key belongs to ONE vendor. If the URL changed, do not reuse it against the new host.
  LAST_URL="$(gcloud secrets describe jarvis-openai-compat-key --format='value(labels.host)' 2>/dev/null || true)"
  HOST="$(printf '%s' "$C_URL" | sed -E 's#^https?://([^/:]+).*#\1#' | tr 'A-Z' 'a-z' | tr -c 'a-z0-9_\n-' '_' | cut -c1-63)"
  if [ -n "$LAST_URL" ] && [ "$LAST_URL" != "$HOST" ]; then
    echo "  The saved API key was for ${LAST_URL}, not ${HOST}: paste the key for this server, or type none."
  fi
  optional_secret jarvis-openai-compat-key "  API key for ${HOST} (type none if the server has no key)"
  if [ "$HAVE_SECRET" = yes ]; then
    if [ -n "$LAST_URL" ] && [ "$LAST_URL" != "$HOST" ] && [ "$SECRET_SOURCE" = saved ]; then
      die "Refusing to send the key saved for ${LAST_URL} to ${HOST}. Re-run and paste the right key (or type none)."
    fi
    gcloud secrets update jarvis-openai-compat-key --update-labels="host=${HOST}" --quiet >/dev/null 2>&1 || true
    BRAIN_SECRET="${BRAIN_SECRET}JARVIS_OPENAI_COMPAT_API_KEY=jarvis-openai-compat-key:latest,"
  fi
  # commas are the env-var separator for gcloud; labels/URLs must not contain one
  case "${C_URL}${C_MODEL}${C_LABEL}" in *,*) die "Please avoid commas in the URL, model id and name." ;; esac
  BRAIN_ENV="${BRAIN_ENV}JARVIS_OPENAI_COMPAT_BASE_URL=${C_URL},JARVIS_OPENAI_COMPAT_MODEL_BALANCED=${C_MODEL},JARVIS_OPENAI_COMPAT_LABEL=${C_LABEL},JARVIS_OPENAI_COMPAT_TRAINS_ON_CONTENT=${C_TRAIN_BOOL},"
  HAVE="${HAVE}custom "
fi
[ -n "$HAVE" ] || die "At least one brain is needed. Re-run and paste a key."
echo
echo "Configured brains: $HAVE"
FIRST="${HAVE%% *}"
read -r -p "Which one should be the default? (claude / gemini / custom) [$FIRST]: " DEFAULT_BRAIN
DEFAULT_BRAIN="${DEFAULT_BRAIN:-$FIRST}"
case "$DEFAULT_BRAIN" in claude|Claude|CLAUDE) DEFAULT_BRAIN=anthropic ;; Gemini|GEMINI) DEFAULT_BRAIN=gemini ;; Custom|CUSTOM) DEFAULT_BRAIN=custom ;; esac
case " $HAVE" in *" $DEFAULT_BRAIN "*) ;; *) die "Default must be one of: $HAVE" ;; esac
BRAIN_ENV="${BRAIN_ENV}JARVIS_LLM_BACKEND=${DEFAULT_BRAIN}"
fi
secret_exists jarvis-session-secret || put_secret jarvis-session-secret "$(rand)"
secret_exists jarvis-api-token || put_secret jarvis-api-token "$(rand)"
# Encrypts the owner's Google tokens at rest. Generated once; rotating it unlinks Google.
secret_exists jarvis-token-key || put_secret jarvis-token-key "$(rand_key)"

# Web search (slice 10): the one question a quick re-run may ask, and only while there is no saved
# answer. Saved answer = the jarvis-tavily-key secret, or a remembered skip (the live service has
# JARVIS_WEB_SEARCH_ENABLED). The key goes straight to Secret Manager, never to a file or the log.
WEB_SECRET=""; WEB_ENV="JARVIS_WEB_SEARCH_ENABLED=false"; WEB_REMOVE=()
web_search_answer() {
  local v=""
  if [ "$QUICK" = yes ] && [ "${ASK_WEB:-no}" = no ]; then
    if secret_exists jarvis-tavily-key; then
      WEB_SECRET="JARVIS_TAVILY_API_KEY=jarvis-tavily-key:latest,"; WEB_ENV="JARVIS_WEB_SEARCH_ENABLED=true"
      return 0
    fi
    case "${SVC_JSON:-}" in *'"JARVIS_WEB_SEARCH_ENABLED"'*) return 0 ;; esac   # skipped before
  fi
  echo
  echo "NEW: web search with numbered sources needs a Tavily API key (free: 1,000 searches a month,"
  echo "no card). Sign up at https://app.tavily.com and copy the key that starts with tvly-"
  if secret_exists jarvis-tavily-key; then
    read -r -s -p "Tavily API key (Enter keeps the saved key; type skip to switch web search off): " v || true; echo
  else
    read -r -s -p "Tavily API key (Enter = skip, web search stays off): " v || true; echo
  fi
  case "$v" in
    skip|SKIP|Skip|none|NONE|None) echo "  (web search off)"; return 0 ;;
    "") if secret_exists jarvis-tavily-key; then echo "  (keeping the saved key in secret jarvis-tavily-key)"
        else echo "  (skipped: web search stays off; JARVIS will say it is not set up)"; return 0; fi ;;
    *) put_secret jarvis-tavily-key "$v" || die "Could not store the Tavily key in Secret Manager (jarvis-tavily-key)." ;;
  esac
  WEB_SECRET="JARVIS_TAVILY_API_KEY=jarvis-tavily-key:latest,"; WEB_ENV="JARVIS_WEB_SEARCH_ENABLED=true"
}
web_search_answer

# Maps + YouTube (slice 12 D2): ONE API key, jarvis-maps-yt, restricted to Places (New), Routes and
# YouTube Data v3 — not Geocoding: Routes geocodes address waypoints itself. No question: made (or
# reused) here, its string kept only in Secret Manager (jarvis-google-api-key, readable by
# jarvis-run alone via the grant loop in step 5), never printed. The key is mounted ONLY when, in
# THIS run, its allowed APIs read back as exactly these three and the stored secret is that key's
# string (security review SEC-2: a saved secret is never mounted on trust); in every other case (a
# service that can't be switched on, a key list that FAILS - never read as "no key yet", so no
# second key is made (code review CR-5) - no key, a failed create, read or store, a read-back that
# doesn't match, or a grant that fails in step 5) Maps and YouTube are off for this deploy
# (`maps_off`): unmounted on a quick re-run (removed), left out of the full deploy's secret list,
# and one plain line says so. Every part may fail without stopping the deploy.
MAPS_SECRET=""; MAPS_STATE=off; MAPS_REMOVE=(--remove-secrets JARVIS_GOOGLE_API_KEY)
MAPS_APIS="places.googleapis.com routes.googleapis.com youtube.googleapis.com"
maps_key_allows_only() { # key-name: its allowed APIs, read back, are exactly MAPS_APIS
  local got want
  got="$(gcloud services api-keys describe "$1" --format='value(restrictions.apiTargets[].service)' 2>/dev/null \
    | tr ';, ' '\n\n\n' | sed '/^$/d' | sort -u | tr '\n' ' ' || true)"
  # shellcheck disable=SC2086  # MAPS_APIS is a list of service names
  want="$(printf '%s\n' $MAPS_APIS | sort -u | tr '\n' ' ')"
  [ -n "$got" ] && [ "$got" = "$want" ]
}
maps_off() { # reason: Maps and YouTube are off and unmounted for this deploy
  MAPS_SECRET=""; MAPS_STATE=off; MAPS_REMOVE=(--remove-secrets JARVIS_GOOGLE_API_KEY)
  echo "  Note: $1, so Maps and YouTube are off for this deploy. Re-run this script to try again."
}
maps_key_name() { # prints the key's name ("" = none yet); fails when the list itself failed
  gcloud services api-keys list --filter='displayName=jarvis-maps-yt' --format='value(name)' --limit=1 2>/dev/null
}
setup_maps_key() {
  local name="" key="" saved="" svc
  local -a targets=()
  MAPS_SECRET=""; MAPS_STATE=off; MAPS_REMOVE=(--remove-secrets JARVIS_GOOGLE_API_KEY)
  for svc in $MAPS_APIS; do targets+=("--api-target=service=${svc}"); done
  # shellcheck disable=SC2086  # MAPS_APIS is a list of service names
  if ! gcloud services enable $MAPS_APIS apikeys.googleapis.com --quiet >/dev/null 2>&1; then
    maps_off "the Maps, YouTube and API Keys services could not be switched on"; return 0
  fi
  if ! name="$(maps_key_name)"; then   # a failed list is not an empty one: never a second key
    maps_off "the project's API keys could not be listed, so no new key was made"; return 0
  fi
  if [ -z "$name" ]; then
    name="$(gcloud services api-keys create --display-name=jarvis-maps-yt "${targets[@]}" \
      --format='value(response.name)' --quiet 2>/dev/null || true)"
    [ -n "$name" ] || name="$(maps_key_name || true)"
  else   # keep its restrictions exactly these three APIs
    gcloud services api-keys update "$name" "${targets[@]}" --quiet >/dev/null 2>&1 || \
      echo "  Note: could not update the Maps/YouTube key's restrictions."
  fi
  if [ -z "$name" ]; then
    maps_off "the Maps/YouTube key could not be created"; return 0
  fi
  if ! maps_key_allows_only "$name"; then
    maps_off "the Maps/YouTube key could not be confirmed to allow exactly Places, Routes and YouTube"; return 0
  fi
  key="$(gcloud services api-keys get-key-string "$name" --format='value(keyString)' 2>/dev/null || true)"
  if [ -z "$key" ]; then
    maps_off "the Maps/YouTube key could not be read"; return 0
  fi
  saved="$(gcloud secrets versions access latest --secret=jarvis-google-api-key 2>/dev/null || true)"
  if [ "$saved" != "$key" ] && ! put_secret jarvis-google-api-key "$key"; then
    maps_off "the Maps/YouTube key could not be stored in Secret Manager"; return 0
  fi
  # the read-back matched and the stored secret is this key's string: mount it
  MAPS_SECRET="JARVIS_GOOGLE_API_KEY=jarvis-google-api-key:latest,"; MAPS_STATE=on; MAPS_REMOVE=()
}
setup_maps_key

# Which of Google's Maps price lists applies (slice 12 D2): India's free allowance (35,000 searches
# and car routes a month) only when the billing account bills in Indian rupees; anywhere else, or
# when that can't be checked, the global one (5,000 each) — JARVIS then stops early, never late.
MAPS_PRICING=global; BILLING_ACCOUNT=""
maps_pricing() {
  local currency=""
  BILLING_ACCOUNT="$(gcloud billing projects describe "$PROJECT" --format='value(billingAccountName)' 2>/dev/null || true)"
  BILLING_ACCOUNT="${BILLING_ACCOUNT#billingAccounts/}"
  if [ -n "$BILLING_ACCOUNT" ]; then
    currency="$(gcloud billing accounts describe "$BILLING_ACCOUNT" --format='value(currencyCode)' 2>/dev/null || true)"
  fi
  if [ "$currency" = INR ]; then
    MAPS_PRICING=india
  else
    MAPS_PRICING=global
    echo "  Note: your Cloud billing account is not billed in Indian rupees (or this could not be checked), so JARVIS keeps to Google's smaller global Maps free allowance. India's larger one applies only to a billing account in India."
  fi
}
maps_pricing
if [ "$MAPS_PRICING" = india ]; then
  MAPS_STOPS="31,500 place searches and 31,500 car routes a month (6,300 two-wheeler and 63,000 walking routes)"
else
  MAPS_STOPS="4,500 place searches and 4,500 car routes a month (900 two-wheeler and 9,000 walking routes)"
fi

# A budget alert as a second brake (slice 12 D2): JARVIS keeps inside free allowances, so a budget
# of 1 in the billing account's own currency (1 rupee for an Indian account) emails the billing
# account's admins as soon as anything at all is charged to this project. Made once; it never
# caps spending and never stops the deploy.
setup_budget_alert() {
  local found=""
  if [ -z "$BILLING_ACCOUNT" ]; then
    echo "  Note: no budget alert was added (the billing account could not be read)."; return 0
  fi
  if ! gcloud services enable billingbudgets.googleapis.com --quiet >/dev/null 2>&1; then
    echo "  Note: no budget alert was added (budgets could not be switched on); add one in Billing, Budgets and alerts."; return 0
  fi
  # a list that FAILS is not an empty one (code review CR-5): never a second alert
  if ! found="$(gcloud billing budgets list --billing-account="$BILLING_ACCOUNT" --filter='displayName=jarvis-any-charge' --format='value(name)' 2>/dev/null)"; then
    echo "  Note: could not check for the budget alert, so none was added this time; re-run this script to try again (or add one in Billing, Budgets and alerts)."; return 0
  fi
  [ -z "$found" ] || return 0
  gcloud billing budgets create --billing-account="$BILLING_ACCOUNT" --display-name=jarvis-any-charge \
    --budget-amount=1 --filter-projects="projects/${PROJECT}" \
    --threshold-rule=percent=0.01 --threshold-rule=percent=1.0 --quiet >/dev/null 2>&1 \
    || echo "  Note: could not add the budget alert (it needs a billing account admin); add one in Billing, Budgets and alerts."
}
setup_budget_alert

# Google's free Maps / YouTube allowances may be counted per billing account, while JARVIS's counter
# sees only this deployment (security review SEC-4): say so when other projects share the account.
# Never stops the deploy; "unknown" when the list can't be read.
SHARED_BILLING=no
billing_shared() {
  local projects="" others=""
  [ -n "$BILLING_ACCOUNT" ] || { SHARED_BILLING=unknown; return 0; }
  if ! projects="$(gcloud billing projects list --billing-account="$BILLING_ACCOUNT" --format='value(projectId)' 2>/dev/null)"; then
    SHARED_BILLING=unknown; return 0
  fi
  others="$(printf '%s\n' "$projects" | grep -v -x -F -e "$PROJECT" -e '' || true)"
  if [ -n "$others" ]; then SHARED_BILLING=yes; else SHARED_BILLING=no; fi
}
billing_shared

say "4/8  Setting up JARVIS's memory (a Firestore database in your project)"
if DBTYPE="$(gcloud firestore databases describe --database='(default)' --format='value(type)' 2>/dev/null)"; then
  [ "$DBTYPE" = "FIRESTORE_NATIVE" ] || die "This project already has a database in '$DBTYPE' mode; JARVIS needs Firestore Native mode. Send this message to Claude."
  echo "  (memory database already exists - keeping it and everything in it)"
else
  echo "  Creating it in $REGION (Mumbai). This location is permanent."
  gcloud firestore databases create --database='(default)' --location="$REGION" \
    --type=firestore-native --quiet >/dev/null || die "Could not create the Firestore database."
fi
# Lets the conversation list sort on the server. Builds in the background (a few minutes);
# until it is ready JARVIS sorts in the app, so nothing waits for it.
IDX_OUT="$(gcloud firestore indexes composite create --database='(default)' --collection-group=jarvis_sessions \
  --field-config=field-path=user_id,order=ascending --field-config=field-path=updated_at,order=descending \
  --async --quiet 2>&1)" || case "$IDX_OUT" in
    *already*exists*|*ALREADY_EXISTS*) ;;
    *) echo "  Note: the conversation-list index could not be created yet (JARVIS works without it):"
       printf '  %s\n' "$IDX_OUT" | tail -2 ;;
  esac

say "5/8  Permissions: JARVIS's own account reads secrets + memory; the build account only builds"
bind() { # member role  (a brand-new service account can take a few seconds to be visible)
  for _ in 1 2 3 4 5 6; do
    gcloud projects add-iam-policy-binding "$PROJECT" --member="$1" --role="$2" \
      --condition=None --quiet >/dev/null 2>&1 && return 0
    sleep 5
  done
  die "Could not grant $2 to $1."
}
try_bind() { # member role: like bind, but a failure is reported to the caller, not fatal
  for _ in 1 2 3; do
    gcloud projects add-iam-policy-binding "$PROJECT" --member="$1" --role="$2" \
      --condition=None --quiet >/dev/null 2>&1 && return 0
    sleep 5
  done
  return 1
}
RUN_SA="jarvis-run@${PROJECT}.iam.gserviceaccount.com"
gcloud iam service-accounts describe "$RUN_SA" >/dev/null 2>&1 || \
  gcloud iam service-accounts create jarvis-run --display-name="JARVIS (runtime)" --quiet >/dev/null \
  || die "Could not create the jarvis-run service account."
for role in roles/datastore.user roles/logging.logWriter; do
  bind "serviceAccount:${RUN_SA}" "$role"
done
# serviceUsageConsumer: lets JARVIS call the (already enabled) speech APIs as itself; harmless if
# not needed, and voice falls back to the browser if it can't be granted.
try_bind "serviceAccount:${RUN_SA}" roles/serviceusage.serviceUsageConsumer \
  || echo "  Note: could not let JARVIS use the speech APIs; the browser voice will be used."
# An optional part never stops the deploy (code review CR-5): when JARVIS can't be let read the
# Tavily or the Maps/YouTube key, that one is left unmounted (a quick re-run removes it) with a
# plain note. Every other secret is required: failing to grant it stops here.
grant_failed() { # secret
  case "$1" in
    jarvis-tavily-key)
      echo "  Note: could not let JARVIS read the secret $1, so web search stays off this time; re-run this script to try again."
      WEB_SECRET=""; WEB_ENV="JARVIS_WEB_SEARCH_ENABLED=false"; WEB_REMOVE=(--remove-secrets JARVIS_TAVILY_API_KEY) ;;
    jarvis-google-api-key)
      maps_off "could not let JARVIS read the secret $1" ;;
    *) die "Could not let JARVIS read the secret $1." ;;
  esac
}
for secret in jarvis-google-client-secret jarvis-anthropic-key jarvis-gemini-key \
              jarvis-openai-compat-key jarvis-session-secret jarvis-api-token jarvis-token-key \
              jarvis-tavily-key jarvis-google-api-key; do
  secret_exists "$secret" || continue
  ok=no
  for _ in 1 2 3 4 5 6; do
    gcloud secrets add-iam-policy-binding "$secret" --member="serviceAccount:${RUN_SA}" \
      --role=roles/secretmanager.secretAccessor --quiet >/dev/null 2>&1 && { ok=yes; break; }
    sleep 5
  done
  [ "$ok" = yes ] || grant_failed "$secret"
done
SA="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"  # builds the container
for role in roles/cloudbuild.builds.builder roles/artifactregistry.writer roles/logging.logWriter \
            roles/storage.objectViewer; do
  bind "serviceAccount:${SA}" "$role"
done

say "6/8  Building and deploying (3-6 minutes the first time)"
cd "$(dirname "$0")/.."
show_logs() {
  printf '\nDeploy failed. Last log lines from the service (copy these to Claude):\n'
  gcloud run services logs read "$SERVICE" --region "$REGION" --limit 40 2>/dev/null || true
}
# Settings this script owns (safe to refresh on every run). The owner's answers (email, client
# id, brains) and the secret bindings are only (re)written when questions were asked.
# JARVIS_BRIEF_SCHEDULER_SA is only the clock account's address: JARVIS accepts a wake-up call
# signed for exactly this account. It is just text here, so the account itself can be created in
# step 8 (after this deploy) without anything failing on a first run.
SCHED_SA="jarvis-scheduler@${PROJECT}.iam.gserviceaccount.com"
INFRA_ENV="JARVIS_ENV=prod,JARVIS_LOG_JSON=true,JARVIS_AUTH_MODE=google,JARVIS_PUBLIC_BASE_URL=${BASE_URL},JARVIS_SESSION_BACKEND=firestore,JARVIS_FIRESTORE_PROJECT=${PROJECT},JARVIS_DEFAULT_TIER=balanced,JARVIS_EFFORT=low,JARVIS_LLM_TIMEOUT_S=20,JARVIS_BRIEF_SCHEDULER_SA=${SCHED_SA},JARVIS_DRIVE=${DRIVE_STATE}"
INFRA_ENV="${INFRA_ENV},${WEB_ENV}"   # the web-search answer (on / remembered skip), both paths
INFRA_ENV="${INFRA_ENV},JARVIS_MAPS_PRICING=${MAPS_PRICING}"   # Google's Maps price list (india / global)
if [ "$QUICK" = yes ]; then
  CONFIG_FLAGS=(
    --update-env-vars "$INFRA_ENV"
    --update-secrets "JARVIS_GOOGLE_CLIENT_SECRET=jarvis-google-client-secret:latest,JARVIS_SESSION_SECRET=jarvis-session-secret:latest,JARVIS_API_TOKEN=jarvis-api-token:latest,${MAPS_SECRET}${WEB_SECRET}JARVIS_TOKEN_KEY=jarvis-token-key:latest"
    "${MAPS_REMOVE[@]}" "${WEB_REMOVE[@]}"
  )
else
  CONFIG_FLAGS=(
    --set-env-vars "${INFRA_ENV},JARVIS_OWNER_EMAILS=${OWNER_EMAIL},JARVIS_GOOGLE_CLIENT_ID=${CLIENT_ID},${BRAIN_ENV}"
    --set-secrets "JARVIS_GOOGLE_CLIENT_SECRET=jarvis-google-client-secret:latest,${BRAIN_SECRET}JARVIS_SESSION_SECRET=jarvis-session-secret:latest,JARVIS_API_TOKEN=jarvis-api-token:latest,${MAPS_SECRET}${WEB_SECRET}JARVIS_TOKEN_KEY=jarvis-token-key:latest"
  )
fi
gcloud run deploy "$SERVICE" --source . --region "$REGION" \
  --service-account "$RUN_SA" \
  --allow-unauthenticated \
  --min-instances 0 --max-instances 1 \
  --memory 512Mi --cpu 1 --timeout 300 \
  "${CONFIG_FLAGS[@]}" \
  --quiet || { show_logs; exit 1; }

# Only now that JARVIS runs as jarvis-run: earlier versions ran as (and let) the build account
# read the secrets; it no longer needs to, nor the database. Done after the deploy so a failed
# deploy never leaves the previous version unable to start. ("not found" = already removed.)
for role in roles/secretmanager.secretAccessor roles/datastore.user; do
  if ! OUT="$(gcloud projects remove-iam-policy-binding "$PROJECT" --member="serviceAccount:${SA}" \
       --role="$role" --condition=None --quiet 2>&1 >/dev/null)"; then
    case "$OUT" in *not\ found*|*NOT_FOUND*|*does\ not\ exist*) ;;
      *) echo "  Note: could not remove $role from the build account (JARVIS still works):"
         printf '  %s\n' "$OUT" | tail -1 ;;
    esac
  fi
done

say "7/8  Automatic updates: let GitHub deploy JARVIS when you merge (no keys involved)"
DEPLOY_SA="jarvis-deployer@${PROJECT}.iam.gserviceaccount.com"
retry() { # command...  (new accounts/pools take a few seconds to become visible)
  for _ in 1 2 3 4 5 6; do "$@" >/dev/null 2>&1 && return 0; sleep 5; done
  "$@" >/dev/null   # last try shows the error
}
setup_autodeploy() {
  # Only this repository (by numeric id), only main, only a push or a manual run of ci.yml on
  # GitHub's own runners. pull_request(_target), forks, other branches and workflows: refused.
  local cond="assertion.repository_id=='${GH_REPO_ID}' && assertion.ref=='refs/heads/main' && assertion.event_name in ['push','workflow_dispatch'] && assertion.job_workflow_ref=='${GH_REPO}/.github/workflows/ci.yml@refs/heads/main' && assertion.runner_environment=='github-hosted'"
  local map="google.subject=assertion.sub,attribute.repository=assertion.repository,attribute.repository_id=assertion.repository_id,attribute.ref=assertion.ref"
  gcloud iam workload-identity-pools describe "$POOL" --location=global >/dev/null 2>&1 || \
    gcloud iam workload-identity-pools create "$POOL" --location=global \
      --display-name="GitHub Actions" --quiet >/dev/null || return 1
  if gcloud iam workload-identity-pools providers describe "$PROVIDER" --location=global \
       --workload-identity-pool="$POOL" >/dev/null 2>&1; then
    gcloud iam workload-identity-pools providers update-oidc "$PROVIDER" --location=global \
      --workload-identity-pool="$POOL" --attribute-mapping="$map" --attribute-condition="$cond" \
      --quiet >/dev/null || return 1
  else
    gcloud iam workload-identity-pools providers create-oidc "$PROVIDER" --location=global \
      --workload-identity-pool="$POOL" --display-name="${GH_REPO} (main only)" \
      --issuer-uri="https://token.actions.githubusercontent.com" \
      --attribute-mapping="$map" --attribute-condition="$cond" --quiet >/dev/null || return 1
  fi
  gcloud iam service-accounts describe "$DEPLOY_SA" >/dev/null 2>&1 || \
    gcloud iam service-accounts create jarvis-deployer --display-name="JARVIS (deploy from GitHub)" \
      --quiet >/dev/null || return 1
  retry gcloud iam service-accounts add-iam-policy-binding "$DEPLOY_SA" \
    --role=roles/iam.workloadIdentityUser \
    --member="principalSet://iam.googleapis.com/projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/${POOL}/attribute.repository_id/${GH_REPO_ID}" \
    --quiet || return 1
  retry gcloud iam service-accounts add-iam-policy-binding "$RUN_SA" \
    --member="serviceAccount:${DEPLOY_SA}" --role=roles/iam.serviceAccountUser --quiet || return 1
  retry gcloud run services add-iam-policy-binding "$SERVICE" --region "$REGION" \
    --member="serviceAccount:${DEPLOY_SA}" --role=roles/run.developer --quiet || return 1
  retry gcloud artifacts repositories add-iam-policy-binding "$AR_REPO" --location "$REGION" \
    --member="serviceAccount:${DEPLOY_SA}" --role=roles/artifactregistry.writer --quiet || return 1
  # lets gcloud check that the Cloud Run API is on (read-only; grants no resource access)
  retry gcloud projects add-iam-policy-binding "$PROJECT" --member="serviceAccount:${DEPLOY_SA}" \
    --role=roles/serviceusage.serviceUsageConsumer --condition=None --quiet || return 1
  # Keep the 10 newest images always; delete older ones after 30 days (stays near the free 0.5 GB).
  local policy; policy="$(mktemp)"
  cat > "$policy" <<'JSON'
[{"name":"keep-newest-10","action":{"type":"Keep"},"mostRecentVersions":{"keepCount":10}},
 {"name":"delete-older","action":{"type":"Delete"},"condition":{"olderThan":"30d"}}]
JSON
  gcloud artifacts repositories set-cleanup-policies "$AR_REPO" --location "$REGION" \
    --policy="$policy" --no-dry-run --quiet >/dev/null 2>&1 || \
    echo "  Note: could not set the image clean-up rule (harmless; old images just stay)."
  rm -f "$policy"
}
AUTODEPLOY_OK=no
if setup_autodeploy; then AUTODEPLOY_OK=yes
else echo "  Note: automatic updates could not be set up (JARVIS itself is deployed and fine)."
fi

say "8/8  Morning brief schedule: a clock that wakes JARVIS every 30 minutes, 04:00-11:30 (free)"
TICK_URL="${BASE_URL}/internal/brief/tick"
setup_brief_clock() {
  gcloud services enable cloudscheduler.googleapis.com --quiet >/dev/null || return 1
  # Its own account with no project roles: it can only prove "I am JARVIS's clock" to JARVIS.
  gcloud iam service-accounts describe "$SCHED_SA" >/dev/null 2>&1 || \
    gcloud iam service-accounts create jarvis-scheduler --display-name="JARVIS (morning brief clock)" \
      --quiet >/dev/null || return 1
  # The token's audience is the exact address it is sent to, so it is useless anywhere else.
  local flags=(--location "$REGION" --schedule "0,30 4-11 * * *" --time-zone "$BRIEF_TZ"
    --uri "$TICK_URL" --http-method POST
    --oidc-service-account-email "$SCHED_SA" --oidc-token-audience "$TICK_URL"
    --attempt-deadline 180s --quiet)
  if gcloud scheduler jobs describe "$BRIEF_JOB" --location "$REGION" >/dev/null 2>&1; then
    retry gcloud scheduler jobs update http "$BRIEF_JOB" "${flags[@]}" || return 1
  else   # a brand-new account can take a few seconds to be usable: retry waits for it
    retry gcloud scheduler jobs create http "$BRIEF_JOB" --description="JARVIS morning brief: checks if a brief is due" \
      "${flags[@]}" || return 1
  fi
}
BRIEF_CLOCK_OK=no; BRIEF_CLOCK_TEST=no
if setup_brief_clock; then
  BRIEF_CLOCK_OK=yes
  # One test call now. Harmless: JARVIS decides whether a brief is due (nothing is made twice,
  # nothing outside the morning window), so this only proves the clock can reach JARVIS's door.
  if gcloud scheduler jobs run "$BRIEF_JOB" --location "$REGION" --quiet >/dev/null 2>&1; then BRIEF_CLOCK_TEST=yes; fi
else echo "  Note: the morning-brief clock could not be set up. JARVIS works; the brief is made when you open the Brief panel. Re-run this script later to try again."
fi

say "DONE. Open JARVIS at:  $BASE_URL"
if [ "$BRIEF_CLOCK_OK" = yes ]; then
  if [ "$BRIEF_CLOCK_TEST" = yes ]; then
    BRIEF_CHECK="Test run just now: Google Cloud Scheduler accepted it (JARVIS itself answers within a minute; Brief panel shows the result)."
  else
    BRIEF_CHECK="The test run didn't go through just now (a new schedule can take a minute). Nothing to do: it runs by itself every 30 minutes from 04:00."
  fi
cat <<MSG

Morning brief: ready. JARVIS prepares it every morning at the time you pick in the Brief panel
(07:00 to start; clock time zone ${BRIEF_TZ}). Paid extras stay off until you switch them on there.
${BRIEF_CHECK}
MSG
else
cat <<'MSG'

Morning brief: NOT scheduled. Step 8 could not set up the clock that makes it each morning.
JARVIS works, and the brief is still made whenever you open the Brief panel.
Re-run this script later to add the schedule (nothing else changes).
MSG
fi
if [ "$AUTODEPLOY_OK" = yes ]; then
cat <<MSG

Automatic updates are ready on Google's side. Last switch (once): tell Claude
"auto-deploy is ready", or in GitHub open ${GH_REPO} -> Settings -> Secrets and variables
-> Actions -> Variables and add  AUTODEPLOY = on,  GCP_PROJECT_ID = ${PROJECT},
GCP_PROJECT_NUMBER = ${PROJECT_NUMBER}. After that, merging on GitHub is the whole update.
MSG
fi
if [ "$QUICK" = no ]; then
cat <<MSG

FIRST INSTALL ONLY: tell Google this address. Google Cloud Console -> APIs & Services ->
Credentials -> jarvis-web, then add:
   Authorised JavaScript origin :  $BASE_URL
   Authorised redirect URI      :  $BASE_URL/auth/callback
   Authorised redirect URI      :  $BASE_URL/connect/google/callback
and press Save (can take up to 5 minutes). Already done? Nothing to do.
MSG
fi
if [ "$WEB_ENV" = "JARVIS_WEB_SEARCH_ENABLED=true" ]; then
cat <<'MSG'

WEB SEARCH: on (Tavily key in secret jarvis-tavily-key). JARVIS stops at 900 searches a month
(90 % of the free 1,000) and never uses pay-as-you-go: it costs nothing. Vitals shows the count.
MSG
else
cat <<'MSG'

WEB SEARCH: off (no Tavily key). To switch it on later: sign up free at https://app.tavily.com,
copy the key (tvly-...), then run:  bash deploy/cloudrun.sh --web-search
(the key is kept in secret jarvis-tavily-key).
MSG
fi
if [ "$DRIVE_STATE" = on ]; then
cat <<MSG

GOOGLE DRIVE (your chosen folders, read-only): JARVIS reads Drive as its own Google account,
only folders you share with it and switch on. For each folder: open it in Google Drive -> Share
-> paste this address -> Viewer -> Send:
   ${RUN_SA}
then in JARVIS: Integrations -> Google Drive -> Use. Switching a folder off in JARVIS stops
access at once. Un-sharing in Drive also stops it (within a minute) unless someone else has
shared it too.
MSG
else
cat <<'MSG'

GOOGLE DRIVE: off (the Google Drive API could not be switched on). Re-run this script to try again.
MSG
fi
if [ "$MAPS_STATE" = on ]; then
cat <<MSG

MAPS + YOUTUBE: on (key jarvis-maps-yt, restricted to Places, Routes and YouTube; kept in secret
jarvis-google-api-key). JARVIS stops at 90 % of Google's free allowance: ${MAPS_STOPS}, and
90 YouTube searches a day. Maps price list: ${MAPS_PRICING} (India's larger allowance applies
only when your Cloud billing account is in India and bills in rupees). Vitals shows the counts.
MSG
else
cat <<'MSG'

MAPS + YOUTUBE: off for this deploy (the Maps/YouTube key could not be confirmed; see the note
above). Re-run this script to try again.
MSG
fi
if [ "$SHARED_BILLING" = yes ]; then
cat <<'MSG'

Note: Other projects share this billing account. If they also use Maps or YouTube, JARVIS's
free-allowance counter can't see their use (Google may count the free allowance per billing
account) - the 1-rupee budget alert (jarvis-any-charge) will still email you on any charge.
MSG
elif [ "$SHARED_BILLING" = unknown ]; then
cat <<'MSG'

Note: could not check whether other projects share this billing account. JARVIS counts only its
own Maps and YouTube use; the 1-rupee budget alert (jarvis-any-charge) still emails you on any
charge.
MSG
fi
cat <<'MSG'

VOICE: switched on above (Text-to-Speech + Speech-to-Text). If the Voice panel says cloud voice
is off ("api_disabled"), run once in Cloud Shell:
   gcloud services enable texttospeech.googleapis.com speech.googleapis.com
JARVIS uses the browser's own voice until then (it checks again within 10 minutes).

GOOGLE CALENDAR + GMAIL (once): APIs & Services -> OAuth consent screen (Google Auth Platform)
  1. Data Access -> Add or remove scopes -> add these and Save:
       https://www.googleapis.com/auth/calendar.events
       https://www.googleapis.com/auth/calendar.readonly
       https://www.googleapis.com/auth/gmail.readonly
       https://www.googleapis.com/auth/gmail.compose   (drafts AND sending)
       https://www.googleapis.com/auth/gmail.insert    (optional: only needed for the brief in your inbox)
       https://www.googleapis.com/auth/tasks           (optional: your to-do list in Google Tasks)
       https://www.googleapis.com/auth/contacts.readonly  (optional: look up your contacts, read only)
       https://www.googleapis.com/auth/youtube.readonly   (optional: your YouTube playlists, read only)
     When you connect, leave every box ticked: JARVIS refuses a partial link. The four optional
     ones are the exception: without gmail.insert the brief simply stays in JARVIS; without
     tasks there is no to-do list; without contacts.readonly or youtube.readonly there are no
     contact look-ups or playlists. Linked before? Integrations -> To-do list -> Grant adds it.
     Contacts and YouTube playlists are asked for only by their own Grant (Integrations ->
     Contacts -> Grant, or YouTube playlists -> Grant); a reconnect keeps what you granted.
  2. Audience -> Test users -> add your own Gmail address (the one JARVIS signs in with).
  3. In JARVIS: panel -> Integrations -> Connect Google.
  While the app stays in "Testing", Google expires the link every 7 days: JARVIS will show
  "Needs reconnecting" - press Connect Google again. Publishing the app removes that limit.
MSG
