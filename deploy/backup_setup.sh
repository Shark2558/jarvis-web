#!/usr/bin/env bash
# deploy/backup_setup.sh -- the owner's one-time step for backups (docs/plans/r14-hardening.md D3,
# D4, owner steps 1-7). Two modes, fixed at R14 I0 so Parts A and D can't drift:
#
#   bash deploy/backup_setup.sh --status   READ ONLY, always exit 0: what is set up now (the
#                                          deploy calls only this; it never creates a schedule,
#                                          a binding or protection, and never spends anything)
#   bash deploy/backup_setup.sh            the set-up: shows the cost lines, waits for YES, then
#                                          (Part A) the daily schedule kept 7 days, delete
#                                          protection on (default), the drill's three grants
#
# I0's stub: the set-up is not built yet; nothing is created in either mode.
set -euo pipefail

COST_LINES=(
  "Backups: about Rs 5 a month at 100 MB, about Rs 40 at 1 GB (Google's charge)."
  "Monthly restore drill: about Rs 2 at 100 MB, never over Rs 100 a drill."
)

status() {
  echo "Backups: not built yet (R14 Part A). Nothing was read or changed."
  return 0
}

setup() {
  local line answer
  for line in "${COST_LINES[@]}"; do
    echo "$line"
  done
  printf 'Type YES to go on (anything else stops with nothing changed): '
  read -r answer || answer=""
  if [[ "$answer" != "YES" ]]; then
    echo "Stopped. Nothing was changed."
    return 0
  fi
  echo "Backups: the set-up is not built yet (R14 Part A). Nothing was changed."
  return 0
}

case "${1:-}" in
  --status) status ;;
  "") setup ;;
  *) echo "usage: bash deploy/backup_setup.sh [--status]" >&2; exit 2 ;;
esac
