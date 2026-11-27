#!/usr/bin/env bash
# deploy/local-speech/start-kit.sh -- R5.2 laptop speech kit, macOS / Linux (the same steps as
# start-kit.ps1). The pinned requirements are Windows wheels, so on these systems you install the
# kit's packages into $JARVIS_SPEECH_KIT_DIR/venv yourself (README "Not on Windows?").
#
# Runs the kit's speech server (127.0.0.1:11437) and the gate in front of it (Caddy, 127.0.0.1:11436,
# checks the key), publishes the gate with Tailscale Funnel on https port 10000 (or
# JARVIS_SPEECH_KIT_HTTPS_PORT: 443, 8443 or 10000, only when that port is free: the home bridge
# keeps 8443 and the offline brain 443), then prints the address and key to give JARVIS.
# Leave this window open; Ctrl+C stops the kit and closes Funnel on that port.
set -euo pipefail
umask 077

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DIR="${JARVIS_SPEECH_KIT_DIR:-$HOME/.jarvis-local-speech}"
PY="$DIR/venv/bin/python"
KEYFILE="$DIR/key"
GATE_PORT=11436
SERVER_PORT=11437
HTTPS_PORT="${JARVIS_SPEECH_KIT_HTTPS_PORT:-10000}"
WAIT_S="${JARVIS_SPEECH_KIT_WAIT_S:-30}"

case "$HTTPS_PORT" in
  443 | 8443 | 10000) ;;
  *)
    echo "Funnel's https port must be 443, 8443 or 10000." >&2
    exit 1
    ;;
esac

need() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing: $1. $2" >&2
    exit 1
  fi
}
need caddy "Install it from https://caddyserver.com/docs/install"
need tailscale "Install it from https://tailscale.com/download and sign in."
if [ ! -x "$PY" ]; then
  echo "The kit is not installed yet: make $DIR/venv with the kit's packages (README)." >&2
  exit 1
fi

port_open() { (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null; }

# Refuse to start twice: a second run would fight the first over the ports, and its exit would
# close the first run's Funnel.
for port in "$GATE_PORT" "$SERVER_PORT"; do
  if port_open "$port"; then
    echo "Port $port is already in use, probably by a kit that is already running." >&2
    echo "Close that window (or stop whatever uses the port), then run this again." >&2
    exit 1
  fi
done

# Never take over a Funnel port that already serves something else: one door each, the kit 10000,
# the home bridge 8443, the offline brain 443 (R5.2 review). Funnel's status names port 443's door
# with no ":port".
taken="$(tailscale funnel status 2>/dev/null | awk -v port="$HTTPS_PORT" -v gate="127.0.0.1:$GATE_PORT" '
  /^https:\/\// {
    here = ($1 ~ (":" port "/?$")) || (port == "443" && $1 !~ /:[0-9]+\/?$/)
  }
  here && /proxy/ && index($0, gate) == 0 { print "yes"; exit }
' || true)"
if [ "$taken" = "yes" ]; then
  echo "Tailscale Funnel's port $HTTPS_PORT already serves something else on this laptop" >&2
  echo "(the home bridge keeps 8443 and the offline brain 443; the kit's own is 10000)." >&2
  echo "See what uses it with: tailscale funnel status" >&2
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
if [ "${#KEY}" -lt 32 ]; then
  echo "The key in $KEYFILE is too short (it needs 32+ characters). Delete that file and run this" >&2
  echo "again to make a new key (then give JARVIS the new key)." >&2
  exit 1
fi

SERVER_PID=""
CADDY_PID=""
FUNNEL_ON=0
cleanup() {
  if [ -n "$CADDY_PID" ]; then
    kill "$CADDY_PID" 2>/dev/null || true
  fi
  if [ -n "$SERVER_PID" ]; then
    kill "$SERVER_PID" 2>/dev/null || true
  fi
  # close only this port, and only if THIS run opened it; never `funnel reset`
  if [ "$FUNNEL_ON" = 1 ]; then
    tailscale funnel --https="$HTTPS_PORT" off >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT INT TERM

# The key goes to the server and to Caddy through their environment only (never on a command line).
JARVIS_LOCAL_SPEECH_KEY="$KEY" JARVIS_SPEECH_KIT_DIR="$DIR" JARVIS_SPEECH_KIT_MANIFEST="$HERE/models.json" \
  "$PY" -I -m jarvis.localspeech serve &
SERVER_PID=$!
JARVIS_LOCAL_SPEECH_KEY="$KEY" caddy run --config "$HERE/Caddyfile" --adapter caddyfile &
CADDY_PID=$!

for _ in $(seq 1 "$WAIT_S"); do
  port_open "$SERVER_PORT" && break
  sleep 1
done
if ! port_open "$SERVER_PORT"; then
  echo "The kit's server did not start. Run: JARVIS_LOCAL_SPEECH_KEY=... $PY -I -m jarvis.localspeech selftest" >&2
  exit 1
fi

if ! tailscale funnel --bg --https="$HTTPS_PORT" "$GATE_PORT" >/dev/null 2>&1; then
  echo "Tailscale Funnel did not start. Check that Funnel is allowed for your tailnet" >&2
  echo "(Tailscale admin console -> Access controls) and that you are signed in. See README.md." >&2
  exit 1
fi
FUNNEL_ON=1

SUFFIX=":$HTTPS_PORT"
[ "$HTTPS_PORT" = 443 ] && SUFFIX=""
ADDRESS="$(tailscale funnel status 2>/dev/null | grep -o "https://[A-Za-z0-9.-]*\.ts\.net$SUFFIX" | head -n 1 || true)"
echo
echo "The laptop speech kit is running."
echo "Address: ${ADDRESS:-run 'tailscale funnel status' to see it}"
echo "Key: $KEY"
echo
echo "Give both to JARVIS once (README step 6): the address is JARVIS_LOCAL_SPEECH_URL, the key"
echo "goes in the secret jarvis-local-speech-key."
echo "Keep this window open and the laptop awake. Ctrl+C stops it."

wait "$CADDY_PID"
