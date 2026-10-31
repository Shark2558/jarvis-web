#!/usr/bin/env bash
# deploy/cloudrun.sh — deploy JARVIS to Google Cloud Run from Cloud Shell. Safe to re-run.
#
# Does: enable APIs → store secrets in Secret Manager → build from this repo → deploy a PUBLIC
# URL (the app does its own Google sign-in, owner-only) capped at ONE instance and scale-to-zero.
# Memory: conversations, pending approvals and the audit chain live in Firestore (Native mode)
# in THIS project, region asia-south1, inside the free tier. No key: the service account is used.
# Runs as its own service account (jarvis-run): only it can read the secrets and the database;
# the build robot (default compute account) can do neither.
# Why still one instance: rate limiting and the per-conversation write queue are per process.
# Raise --max-instances only after sessions gain a cross-process concurrency check.
set -euo pipefail

SERVICE="${SERVICE:-jarvis}"
REGION="${REGION:-asia-south1}"   # Mumbai; Tier-1 region, covered by the monthly free allowance

say() { printf '\n\033[1m%s\033[0m\n' "$*"; }
die() { printf '\nERROR: %s\n' "$*" >&2; exit 1; }

command -v gcloud >/dev/null || die "gcloud not found. Run this inside Google Cloud Shell."
PROJECT="$(gcloud config get-value project 2>/dev/null || true)"
[ -n "$PROJECT" ] && [ "$PROJECT" != "(unset)" ] || die "No project selected. Run: gcloud config set project YOUR_PROJECT_ID"
PROJECT_NUMBER="$(gcloud projects describe "$PROJECT" --format='value(projectNumber)')"
BASE_URL="https://${SERVICE}-${PROJECT_NUMBER}.${REGION}.run.app"

BILLING="$(gcloud billing projects describe "$PROJECT" --format='value(billingEnabled)' 2>/dev/null || true)"
[ "$BILLING" = "True" ] || die "Billing is not enabled on project $PROJECT. Cloud Run needs a billing account (you stay inside the free allowance). Enable it in Billing, then re-run."

say "1/6  Project: $PROJECT   Region: $REGION   Address will be: $BASE_URL"

say "2/6  Switching on the Google services JARVIS needs (takes ~1 minute)"
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com \
  secretmanager.googleapis.com firestore.googleapis.com iam.googleapis.com --quiet

say "3/6  Your details (typing is hidden for secrets; Enter keeps the saved value on a re-run)"
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
secret_exists jarvis-session-secret || put_secret jarvis-session-secret "$(rand)"
secret_exists jarvis-api-token || put_secret jarvis-api-token "$(rand)"

say "4/6  Setting up JARVIS's memory (a Firestore database in your project)"
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

say "5/6  Permissions: JARVIS's own account reads secrets + memory; the build account only builds"
bind() { # member role  (a brand-new service account can take a few seconds to be visible)
  local n
  for n in 1 2 3 4 5 6; do
    gcloud projects add-iam-policy-binding "$PROJECT" --member="$1" --role="$2" \
      --condition=None --quiet >/dev/null 2>&1 && return 0
    sleep 5
  done
  die "Could not grant $2 to $1."
}
RUN_SA="jarvis-run@${PROJECT}.iam.gserviceaccount.com"
gcloud iam service-accounts describe "$RUN_SA" >/dev/null 2>&1 || \
  gcloud iam service-accounts create jarvis-run --display-name="JARVIS (runtime)" --quiet >/dev/null \
  || die "Could not create the jarvis-run service account."
for role in roles/secretmanager.secretAccessor roles/datastore.user roles/logging.logWriter; do
  bind "serviceAccount:${RUN_SA}" "$role"
done
SA="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"  # builds the container
for role in roles/cloudbuild.builds.builder roles/artifactregistry.writer roles/logging.logWriter \
            roles/storage.objectViewer; do
  bind "serviceAccount:${SA}" "$role"
done

say "6/6  Building and deploying (3-6 minutes the first time)"
cd "$(dirname "$0")/.."
show_logs() {
  printf '\nDeploy failed. Last log lines from the service (copy these to Claude):\n'
  gcloud run services logs read "$SERVICE" --region "$REGION" --limit 40 2>/dev/null || true
}
gcloud run deploy "$SERVICE" --source . --region "$REGION" \
  --service-account "$RUN_SA" \
  --allow-unauthenticated \
  --min-instances 0 --max-instances 1 \
  --memory 512Mi --cpu 1 --timeout 300 \
  --set-env-vars "JARVIS_ENV=prod,JARVIS_LOG_JSON=true,JARVIS_AUTH_MODE=google,JARVIS_PUBLIC_BASE_URL=${BASE_URL},JARVIS_OWNER_EMAILS=${OWNER_EMAIL},JARVIS_GOOGLE_CLIENT_ID=${CLIENT_ID},${BRAIN_ENV},JARVIS_SESSION_BACKEND=firestore,JARVIS_FIRESTORE_PROJECT=${PROJECT},JARVIS_DEFAULT_TIER=balanced,JARVIS_EFFORT=low,JARVIS_LLM_TIMEOUT_S=20" \
  --set-secrets "JARVIS_GOOGLE_CLIENT_SECRET=jarvis-google-client-secret:latest,${BRAIN_SECRET}JARVIS_SESSION_SECRET=jarvis-session-secret:latest,JARVIS_API_TOKEN=jarvis-api-token:latest" \
  --quiet || { show_logs; exit 1; }

# Only now that JARVIS runs as jarvis-run: earlier versions ran as (and let) the build account
# read the secrets; it no longer needs to. Done after the deploy so a failed deploy never
# leaves the previous version unable to start. (Already absent = fine.)
gcloud projects remove-iam-policy-binding "$PROJECT" --member="serviceAccount:${SA}" \
  --role=roles/secretmanager.secretAccessor --condition=None --quiet >/dev/null 2>&1 || true

say "DONE. Open JARVIS at:  $BASE_URL"
cat <<MSG

LAST STEP (once): tell Google this address. Google Cloud Console -> APIs & Services -> Credentials
-> jarvis-web, then add:
   Authorised JavaScript origin :  $BASE_URL
   Authorised redirect URI      :  $BASE_URL/auth/callback
and press Save (can take up to 5 minutes).
MSG
