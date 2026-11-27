#!/usr/bin/env bash
# deploy/local-brain/start-unix.sh -- R1 offline mode, macOS / Linux (plan D10). Owner's laptop,
# no Python needed. Runs the access gate (Caddy) in front of Ollama and publishes it with
# Tailscale Funnel, then prints the address and key to paste into JARVIS:
#     Integrations -> Offline mode.
#
# Needs: Ollama running (ollama.com), Caddy (caddyserver.com), Tailscale signed in with Funnel
# allowed (see README.md). Leave this window open; Ctrl+C stops the gate and closes Funnel.
# The key is made on the first run and kept in a file only you can read.
#
# Funnel's port: 443, the brain's own (R3 plan D3). The home bridge keeps 8443 and the laptop speech
# kit 10000; this script never takes a port that already serves something else (R5.2 review).
set -euo pipefail
umask 077

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DIR="${JARVIS_LOCAL_BRAIN_DIR:-$HOME/.jarvis-local-brain}"
KEYFILE="$DIR/key"
GATE="127.0.0.1:11435"

need() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing: $1. $2" >&2
    exit 1
  fi
}
need caddy "Install it from https://caddyserver.com/docs/install"
need tailscale "Install it from https://tailscale.com/download and sign in."
need curl "Install curl with your package manager."

ollama_up() { curl -fsS --max-time 3 http://127.0.0.1:11434/api/version >/dev/null 2>&1; }

# Ollama's default context window is 4096 tokens; JARVIS's prompt and tool list need more, and an
# overflow silently drops the oldest words. A server we start here gets 8192. One that is already
# running (the Ollama app) keeps its own setting: see README.md.
OLLAMA_PID=""
if ! ollama_up && command -v ollama >/dev/null 2>&1; then
  OLLAMA_CONTEXT_LENGTH=8192 ollama serve >/dev/null 2>&1 &
  OLLAMA_PID=$!
  for _ in $(seq 1 "${JARVIS_OLLAMA_WAIT_S:-15}"); do
    ollama_up && break
    sleep 1
  done
fi
if ! ollama_up; then
  echo "Ollama is not answering on this laptop. Open the Ollama app (or run:" >&2
  echo "OLLAMA_CONTEXT_LENGTH=8192 ollama serve), then pull a model, for example: ollama pull qwen2.5:3b" >&2
  exit 1
fi

# Refuse to start twice: a second run would fight the first over the gate port, and its exit would
# close the first run's Funnel.
if (exec 3<>/dev/tcp/127.0.0.1/11435) 2>/dev/null; then
  echo "Port 11435 is already in use, probably by a gate that is already running." >&2
  echo "Close that window (or stop whatever uses the port), then run this again." >&2
  exit 1
fi

mkdir -p "$DIR"
chmod 700 "$DIR"
if [ ! -s "$KEYFILE" ]; then
  # 32 random bytes, base64url, no padding (43 characters)
  head -c 32 /dev/urandom | base64 | tr '+/' '-_' | tr -d '=\n' >"$KEYFILE"
fi
chmod 600 "$KEYFILE"
KEY="$(cat "$KEYFILE")"
if [ "${#KEY}" -lt 16 ]; then
  echo "The key in $KEYFILE is too short (it needs 16+ characters). Delete that file and run this again" >&2
  echo "to make a new key (then paste the new key into JARVIS)." >&2
  exit 1
fi

# Never take over a Funnel port that already serves something else: one door each, the brain 443,
# the home bridge 8443, the laptop speech kit 10000 (R5.2 review: the brain once took the bridge's).
# Funnel's status names port 443's door with no ":port".
taken="$(tailscale funnel status 2>/dev/null | awk -v gate="$GATE" '
  /^https:\/\// { here = ($1 !~ /:[0-9]+\/?$/ || $1 ~ /:443\/?$/) }
  here && /proxy/ && index($0, gate) == 0 { print "yes"; exit }
' || true)"
if [ "$taken" = "yes" ]; then
  echo "Tailscale Funnel's port 443 already serves something else on this laptop" >&2
  echo "(the home bridge keeps 8443, the speech kit 10000; 443 is the offline brain's)." >&2
  echo "See what uses it with: tailscale funnel status" >&2
  exit 1
fi

CADDY_PID=""
FUNNEL_ON=0
cleanup() {
  if [ -n "$CADDY_PID" ]; then
    kill "$CADDY_PID" 2>/dev/null || true
  fi
  if [ -n "$OLLAMA_PID" ]; then
    kill "$OLLAMA_PID" 2>/dev/null || true
  fi
  # close only this port, and only if THIS run opened it; never `funnel reset` (it would wipe the
  # owner's other Funnel/Serve setup)
  if [ "$FUNNEL_ON" = 1 ]; then
    tailscale funnel --https=443 off >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT INT TERM

# The key goes to Caddy through its environment only (never on a command line).
JARVIS_LOCAL_KEY="$KEY" caddy run --config "$HERE/Caddyfile" --adapter caddyfile &
CADDY_PID=$!
sleep 1

if ! tailscale funnel --bg --https=443 11435 >/dev/null 2>&1; then
  echo "Tailscale Funnel did not start. Check that Funnel is allowed for your tailnet" >&2
  echo "(Tailscale admin console -> Access controls) and that you are signed in. See README.md." >&2
  exit 1
fi
FUNNEL_ON=1

# its own door: port 443 has no ":port" in Funnel's status (the bridge's :8443 is not it)
ADDRESS="$(tailscale funnel status 2>/dev/null | awk '/^https:\/\// && $1 !~ /:[0-9]+\/?$/ { print $1; exit }' || true)"
echo
echo "Offline mode gate is running."
echo "Address: ${ADDRESS:-run 'tailscale funnel status' to see it}"
echo "Key: $KEY"
echo
echo "Paste both into JARVIS -> Integrations -> Offline mode, press Test, then switch it On."
echo "Keep this window open and the laptop awake. Ctrl+C stops it."

wait "$CADDY_PID"
