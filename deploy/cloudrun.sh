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
# Step 7 sets up deploy-on-merge: GitHub Actions proves who it is with a short-lived token
# (Workload Identity Federation) that Google accepts only from this repository's main branch.
# No key exists. The deployer account may only roll out new revisions of this service, push
# images to the build repository, and run them as jarvis-run. Inherent to any deploy-on-merge:
# whoever can change main can ship code that runs as jarvis-run (secrets, memory, audit), so
# protect main (pull requests only, no force-push) and keep your GitHub account on 2-step sign-in.
# --reconfigure rewrites ALL settings and secret bindings from your answers (it does not merge).
set -euo pipefail

SERVICE="${SERVICE:-jarvis}"
REGION="${REGION:-asia-south1}"   # Mumbai; Tier-1 region, covered by the monthly free allowance
GH_REPO="Shark2558/jarvis-web"
GH_REPO_ID="1441253681"           # numeric id: survives renames, can't be re-registered by others
POOL="github"; PROVIDER="jarvis-web"; AR_REPO="cloud-run-source-deploy"

RECONFIGURE=no
for arg in "$@"; do
  case "$arg" in
    --reconfigure) RECONFIGURE=yes ;;
    -h|--help) echo "Usage: bash deploy/cloudrun.sh [--reconfigure]"; exit 0 ;;
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

say "1/7  Project: $PROJECT   Region: $REGION   Address will be: $BASE_URL"

say "2/7  Switching on the Google services JARVIS needs (takes ~1 minute)"
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com \
  secretmanager.googleapis.com firestore.googleapis.com iam.googleapis.com \
  iamcredentials.googleapis.com sts.googleapis.com \
  calendar-json.googleapis.com gmail.googleapis.com --quiet

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
say "3/7  Using your saved answers - nothing to type (to change them: bash deploy/cloudrun.sh --reconfigure)"
else
say "3/7  Your details (typing is hidden for secrets; Enter keeps the saved value on a re-run)"
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

say "4/7  Setting up JARVIS's memory (a Firestore database in your project)"
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

say "5/7  Permissions: JARVIS's own account reads secrets + memory; the build account only builds"
bind() { # member role  (a brand-new service account can take a few seconds to be visible)
  for _ in 1 2 3 4 5 6; do
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
for role in roles/datastore.user roles/logging.logWriter; do
  bind "serviceAccount:${RUN_SA}" "$role"
done
for secret in jarvis-google-client-secret jarvis-anthropic-key jarvis-gemini-key \
              jarvis-openai-compat-key jarvis-session-secret jarvis-api-token jarvis-token-key; do
  secret_exists "$secret" || continue
  ok=no
  for _ in 1 2 3 4 5 6; do
    gcloud secrets add-iam-policy-binding "$secret" --member="serviceAccount:${RUN_SA}" \
      --role=roles/secretmanager.secretAccessor --quiet >/dev/null 2>&1 && { ok=yes; break; }
    sleep 5
  done
  [ "$ok" = yes ] || die "Could not let JARVIS read the secret $secret."
done
SA="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"  # builds the container
for role in roles/cloudbuild.builds.builder roles/artifactregistry.writer roles/logging.logWriter \
            roles/storage.objectViewer; do
  bind "serviceAccount:${SA}" "$role"
done

say "6/7  Building and deploying (3-6 minutes the first time)"
cd "$(dirname "$0")/.."
show_logs() {
  printf '\nDeploy failed. Last log lines from the service (copy these to Claude):\n'
  gcloud run services logs read "$SERVICE" --region "$REGION" --limit 40 2>/dev/null || true
}
# Settings this script owns (safe to refresh on every run). The owner's answers (email, client
# id, brains) and the secret bindings are only (re)written when questions were asked.
INFRA_ENV="JARVIS_ENV=prod,JARVIS_LOG_JSON=true,JARVIS_AUTH_MODE=google,JARVIS_PUBLIC_BASE_URL=${BASE_URL},JARVIS_SESSION_BACKEND=firestore,JARVIS_FIRESTORE_PROJECT=${PROJECT},JARVIS_DEFAULT_TIER=balanced,JARVIS_EFFORT=low,JARVIS_LLM_TIMEOUT_S=20"
if [ "$QUICK" = yes ]; then
  CONFIG_FLAGS=(
    --update-env-vars "$INFRA_ENV"
    --update-secrets "JARVIS_GOOGLE_CLIENT_SECRET=jarvis-google-client-secret:latest,JARVIS_SESSION_SECRET=jarvis-session-secret:latest,JARVIS_API_TOKEN=jarvis-api-token:latest,JARVIS_TOKEN_KEY=jarvis-token-key:latest"
  )
else
  CONFIG_FLAGS=(
    --set-env-vars "${INFRA_ENV},JARVIS_OWNER_EMAILS=${OWNER_EMAIL},JARVIS_GOOGLE_CLIENT_ID=${CLIENT_ID},${BRAIN_ENV}"
    --set-secrets "JARVIS_GOOGLE_CLIENT_SECRET=jarvis-google-client-secret:latest,${BRAIN_SECRET}JARVIS_SESSION_SECRET=jarvis-session-secret:latest,JARVIS_API_TOKEN=jarvis-api-token:latest,JARVIS_TOKEN_KEY=jarvis-token-key:latest"
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

say "7/7  Automatic updates: let GitHub deploy JARVIS when you merge (no keys involved)"
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

say "DONE. Open JARVIS at:  $BASE_URL"
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
cat <<'MSG'

GOOGLE CALENDAR + GMAIL (once): APIs & Services -> OAuth consent screen (Google Auth Platform)
  1. Data Access -> Add or remove scopes -> add these five and Save:
       https://www.googleapis.com/auth/calendar.events
       https://www.googleapis.com/auth/calendar.readonly
       https://www.googleapis.com/auth/gmail.readonly
       https://www.googleapis.com/auth/gmail.compose
       https://www.googleapis.com/auth/gmail.send
  2. Audience -> Test users -> add your own Gmail address (the one JARVIS signs in with).
  3. In JARVIS: panel -> Integrations -> Connect Google.
  While the app stays in "Testing", Google expires the link every 7 days: JARVIS will show
  "Needs reconnecting" - press Connect Google again. Publishing the app removes that limit.
MSG
