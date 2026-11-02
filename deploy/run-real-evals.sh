#!/usr/bin/env bash
# deploy/run-real-evals.sh — test JARVIS against the real Claude models, from Google Cloud Shell.
#
# This costs real money (a few rupees for the default run). Nothing is spent before you type YES:
#   1/5  checks Cloud Shell has what it needs (gcloud, a project, Python 3.11+, your saved key)
#   2/5  prepares a private Python set-up in ~/.jarvis-evals (first time only, about 2 minutes)
#   3/5  lists what will be tested with the cost in rupees, and waits for you to type YES
#   4/5  reads your Claude key from Secret Manager (secret jarvis-anthropic-key, saved there by
#        deploy/cloudrun.sh) into this run's memory only: never printed, never written to disk
#   5/5  runs the tests and says in plain words what passed and what to do next
# A safety stop ends the run by itself if spending reaches 1.5 times the estimate.
# YES must be typed at the terminal: input from a pipe or another program is refused.
# Each test writes its detailed report to evals/<test>/report.json. Each run keeps its own plan,
# spending record and logs in a new folder ~/.jarvis-evals/run-<date>-<id>.
#
#   bash deploy/run-real-evals.sh          the Phase 0 check (everyday conversation)
#   bash deploy/run-real-evals.sh --all    also memory, voice, morning brief, calendar & email tools
set -euo pipefail
set +x  # never trace: this script holds the Claude key in memory
umask 077  # everything under ~/.jarvis-evals is readable by you only

SECRET="jarvis-anthropic-key"  # where deploy/cloudrun.sh keeps the Claude key
EVALS_HOME="${JARVIS_EVALS_HOME:-$HOME/.jarvis-evals}"

ALL_FLAG=()
for arg in "$@"; do
  case "$arg" in
    --all) ALL_FLAG=(--all) ;;
    -h|--help) echo "Usage: bash deploy/run-real-evals.sh [--all]"; exit 0 ;;
    *) printf 'Unknown option: %s (try --help)\n' "$arg" >&2; exit 2 ;;
  esac
done

say() { printf '\n\033[1m%s\033[0m\n' "$*"; }
die() { printf '\nSTOPPED: %s\nNothing was spent.\n' "$*" >&2; exit 2; }

# Spending needs a person: YES is read from the terminal, so `echo YES | ...` can never approve it.
[ -t 0 ] || die "Run this yourself in the Cloud Shell terminal: you will be asked to type YES, so input from a pipe or another program is not accepted."

cd "$(dirname "$0")/.."
REPO="$PWD"

say "1/5  Checking Cloud Shell"
command -v gcloud >/dev/null || die "gcloud not found. Run this inside Google Cloud Shell."
PROJECT="$(gcloud config get-value project 2>/dev/null || true)"
[ -n "$PROJECT" ] && [ "$PROJECT" != "(unset)" ] \
  || die "No project selected. Run: gcloud config set project YOUR_PROJECT_ID"
gcloud secrets describe "$SECRET" --project="$PROJECT" >/dev/null 2>&1 \
  || die "No Claude key is saved in project $PROJECT yet. Run: bash deploy/cloudrun.sh --reconfigure and paste it when asked."
echo "  Project: $PROJECT. Your Claude key is saved (it is not read yet)."

say "2/5  Preparing a private Python set-up in $EVALS_HOME"
mkdir -p "$EVALS_HOME"
PY="${JARVIS_EVALS_PYTHON:-}"
if [ -z "$PY" ]; then
  python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null \
    || die "Python 3.11 or newer is needed (python3 --version shows what Cloud Shell has)."
  VENV="$EVALS_HOME/venv"
  [ -x "$VENV/bin/python" ] || python3 -m venv "$VENV" || die "Could not create the Python set-up."
  STAMP="$(sha256sum pyproject.toml | cut -d' ' -f1)"
  if [ "$(cat "$EVALS_HOME/installed" 2>/dev/null || true)" != "$STAMP" ]; then
    echo "  Installing JARVIS's libraries (first time, or after an update: about 2 minutes)..."
    "$VENV/bin/pip" install --quiet --disable-pip-version-check "$REPO" \
      || die "Could not install the libraries. Check the internet connection and try again."
    printf '%s' "$STAMP" > "$EVALS_HOME/installed"
  else
    echo "  Already prepared."
  fi
  PY="$VENV/bin/python"
fi
export PYTHONPATH="$REPO/src"  # always this checkout's JARVIS (after a git pull too)
# This run's own folder: two runs at once never share (or reset) a plan or a spending record.
RUN_DIR="$(mktemp -d "$EVALS_HOME/run-$(date +%Y%m%d-%H%M%S)-XXXXXX")" \
  || die "Could not create a folder for this run in $EVALS_HOME."
STATE="$RUN_DIR/plan.json"
LEDGER="$RUN_DIR/spend.json"

say "3/5  What will be tested, and the cost"
"$PY" evals/run_real.py estimate "${ALL_FLAG[@]}" --state "$STATE" \
  || die "Could not work out the cost (see the message above)."
AMOUNT="$("$PY" evals/run_real.py amount --state "$STATE")" || die "Could not read the estimate."
cat <<MSG

To go ahead:
  1. Read the list and the estimate above.
  2. Type YES (capital letters) and press Enter to spend about ${AMOUNT}. Anything else cancels.
MSG
ANSWER=""
read -r -p "Type YES to spend about ${AMOUNT}: " ANSWER < /dev/tty || ANSWER=""
if [ "$ANSWER" != "YES" ]; then  # exactly YES, typed at the terminal, is the go-ahead
  echo
  echo "Cancelled. Nothing was spent."
  exit 0
fi

say "4/5  Reading your Claude key from Secret Manager (kept in memory for this run only)"
CLAUDE_KEY="$(gcloud secrets versions access latest --secret="$SECRET" --project="$PROJECT" 2>/dev/null)" \
  || die "Could not read the Claude key from Secret Manager (secret $SECRET)."
[ -n "$CLAUDE_KEY" ] || die "The saved Claude key is empty. Run: bash deploy/cloudrun.sh --reconfigure"
trap 'unset CLAUDE_KEY' EXIT

say "5/5  Running the tests (the Phase 0 check takes a few minutes; --all about 20 minutes)"
RC=0
JARVIS_ANTHROPIC_API_KEY="$CLAUDE_KEY" "$PY" evals/run_real.py run --state "$STATE" --ledger "$LEDGER" \
  --logs "$RUN_DIR/logs" || RC=$?
unset CLAUDE_KEY

case "$RC" in
  0) say "DONE. Every test passed." ;;
  1) say "DONE. Some tests did not pass: follow 'What to do next' above." ;;
  3) say "STOPPED at the safety stop. Nothing more was spent. Send the lines above to Claude." ;;
  4) say "STOPPED: a Claude model without a price in JARVIS was asked for. Send the lines above to Claude." ;;
  *) say "STOPPED: the tests could not run. Nothing more was spent. Send the lines above to Claude." ;;
esac
exit "$RC"
