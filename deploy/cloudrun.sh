#!/usr/bin/env bash
# deploy/cloudrun.sh — deploy JARVIS to Google Cloud Run from Cloud Shell. Safe to re-run.
#
# Does: enable APIs → store secrets in Secret Manager → build from this repo → deploy a PUBLIC
# URL (the app does its own Google sign-in, owner-only) capped at ONE instance and scale-to-zero.
# Why one instance: sessions, pending approvals and the audit chain are in memory until the
# Postgres slice; a second instance would not see the first one's approvals.
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

say "1/5  Project: $PROJECT   Region: $REGION   Address will be: $BASE_URL"

say "2/5  Switching on the Google services JARVIS needs (takes ~1 minute)"
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com \
  secretmanager.googleapis.com --quiet

say "3/5  Your details (typing is hidden for secrets; Enter keeps the saved value on a re-run)"
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
ask_secret jarvis-anthropic-key "Anthropic API key (sk-ant-...)"
secret_exists jarvis-session-secret || put_secret jarvis-session-secret "$(rand)"
secret_exists jarvis-api-token || put_secret jarvis-api-token "$(rand)"

say "4/5  Giving the service permission to read the secrets and build the app"
SA="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"
for role in roles/secretmanager.secretAccessor roles/cloudbuild.builds.builder \
            roles/artifactregistry.writer roles/logging.logWriter roles/storage.objectViewer; do
  gcloud projects add-iam-policy-binding "$PROJECT" --member="serviceAccount:${SA}" --role="$role" \
    --condition=None --quiet >/dev/null
done

say "5/5  Building and deploying (3-6 minutes the first time)"
cd "$(dirname "$0")/.."
show_logs() {
  printf '\nDeploy failed. Last log lines from the service (copy these to Claude):\n'
  gcloud run services logs read "$SERVICE" --region "$REGION" --limit 40 2>/dev/null || true
}
gcloud run deploy "$SERVICE" --source . --region "$REGION" \
  --allow-unauthenticated \
  --min-instances 0 --max-instances 1 \
  --memory 512Mi --cpu 1 --timeout 300 \
  --set-env-vars "JARVIS_ENV=prod,JARVIS_LOG_JSON=true,JARVIS_AUTH_MODE=google,JARVIS_PUBLIC_BASE_URL=${BASE_URL},JARVIS_OWNER_EMAILS=${OWNER_EMAIL},JARVIS_GOOGLE_CLIENT_ID=${CLIENT_ID},JARVIS_SESSION_BACKEND=memory,JARVIS_DEFAULT_TIER=balanced,JARVIS_EFFORT=low" \
  --set-secrets "JARVIS_GOOGLE_CLIENT_SECRET=jarvis-google-client-secret:latest,JARVIS_ANTHROPIC_API_KEY=jarvis-anthropic-key:latest,JARVIS_SESSION_SECRET=jarvis-session-secret:latest,JARVIS_API_TOKEN=jarvis-api-token:latest" \
  --quiet || { show_logs; exit 1; }

say "DONE. Open JARVIS at:  $BASE_URL"
cat <<MSG

LAST STEP (once): tell Google this address. Google Cloud Console -> APIs & Services -> Credentials
-> jarvis-web, then add:
   Authorised JavaScript origin :  $BASE_URL
   Authorised redirect URI      :  $BASE_URL/auth/callback
and press Save (can take up to 5 minutes).
MSG
