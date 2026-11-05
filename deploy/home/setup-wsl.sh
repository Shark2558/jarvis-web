#!/usr/bin/env bash
# JARVIS home kit, the Ubuntu (WSL2) half of the setup. setup-windows.ps1 runs this for you; you
# can also run it by hand:  bash setup-wsl.sh install | configure | up | link CODE ADDRESS | status | camera | passwords
# Re-runnable: every step checks first and skips what is already done.
#
#   install    Docker Engine (from Docker's apt repository) and systemd for Ubuntu
#   configure  copies the kit to ~/jarvis-home, writes bridge.env (passwords made here, kept here),
#              the Mosquitto password file, and fills in the camera address
#   up         pulls the images, records each image's digest in images.env, starts everything
#   link       links the bridge to JARVIS with the code from Integrations -> Home -> Link
#   status     says in plain words what is running
#   camera     says "Camera works" once Frigate is receiving the phone's picture
#   passwords  prints the Frigate login the first start made (write it down)
#
# Environment (set by setup-windows.ps1, all optional):
#   KIT_DIR        where the kit is (default: this script's folder)
#   HOME_DIR       where the running copy lives (default: ~/jarvis-home)
#   CAMERA_URL     the phone camera's RTSP address, with its login (kept only in Frigate's config)
#   HA_TOKEN       the Home Assistant token for the "JARVIS bridge" user (Enter = skip = camera only)
set -euo pipefail

KIT_DIR="${KIT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"
HOME_DIR="${HOME_DIR:-$HOME/jarvis-home}"
COMPOSE=(docker compose --env-file bridge.env --env-file images.env)

say() { printf '\n== %s\n' "$*"; }
fail() { printf '\nSomething went wrong: %s\n' "$*" >&2; exit 1; }

# ---- install --------------------------------------------------------------------------------
step_install() {
  say "Installing Docker Engine (free, from Docker's own apt repository)"
  if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
    echo "Docker is already installed."
  else
    sudo apt-get update
    sudo apt-get install -y ca-certificates curl openssl
    sudo install -m 0755 -d /etc/apt/keyrings
    sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
    sudo chmod a+r /etc/apt/keyrings/docker.asc
    # shellcheck disable=SC1091
    codename="$(. /etc/os-release && echo "${VERSION_CODENAME:-noble}")"
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu ${codename} stable" \
      | sudo tee /etc/apt/sources.list.d/docker.list >/dev/null
    sudo apt-get update
    sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
  fi
  if ! grep -qs '^systemd *= *true' /etc/wsl.conf 2>/dev/null; then
    printf '[boot]\nsystemd=true\n' | sudo tee -a /etc/wsl.conf >/dev/null
    echo "RESTART_WSL: Ubuntu must restart once so Docker starts by itself (the Windows script does it)."
  fi
  sudo systemctl enable --now docker >/dev/null 2>&1 || echo "Docker will start after the restart."
}

# ---- configure ------------------------------------------------------------------------------
random_secret() { openssl rand -base64 24 | tr -d '/+=\n' | cut -c1-24; }

set_env() { # file key value : replaces KEY=... or appends it, without printing the value
  local file="$1" key="$2" value="$3"
  if grep -qs "^${key}=" "$file"; then
    # a value never holds a newline or "|", so | is a safe sed separator
    sed -i "s|^${key}=.*|${key}=${value}|" "$file"
  else
    printf '%s=%s\n' "$key" "$value" >> "$file"
  fi
}

get_env() { grep -s "^$2=" "$1" | head -n1 | cut -d= -f2- || true; }

step_configure() {
  say "Preparing the home folder $HOME_DIR"
  mkdir -p "$HOME_DIR"
  cp -a "$KIT_DIR"/. "$HOME_DIR"/
  cd "$HOME_DIR"
  mkdir -p bridge-data mosquitto-data frigate/config frigate/media homeassistant
  sudo chown 10001:10001 bridge-data
  chmod 700 bridge-data
  if [ ! -f bridge.env ]; then cp bridge.env.example bridge.env; fi
  chmod 600 bridge.env
  if [ -z "$(get_env bridge.env MQTT_PASSWORD)" ]; then set_env bridge.env MQTT_PASSWORD "$(random_secret)"; fi
  if [ -n "${HA_TOKEN:-}" ]; then set_env bridge.env HA_TOKEN "$HA_TOKEN"; fi
  touch images.env
  chmod 600 images.env

  say "Making the Mosquitto password file (the broker accepts nobody without a password)"
  local mqtt_pw; mqtt_pw="$(get_env bridge.env MQTT_PASSWORD)"
  : > mosquitto/passwd
  docker run --rm -v "$HOME_DIR/mosquitto:/work" "${MOSQUITTO_IMAGE:-eclipse-mosquitto:2.0.20}" \
    mosquitto_passwd -b -c /work/passwd jarvis "$mqtt_pw" >/dev/null
  chmod 600 mosquitto/passwd || true

  if [ -n "${CAMERA_URL:-}" ] && [ -f frigate/config.yml ]; then
    say "Writing Frigate's camera address (only Frigate's file on this laptop holds it)"
    if [ ! -f frigate/config/config.yml ]; then
      sed "s|__CAMERA_URL__|${CAMERA_URL}|g" frigate/config.yml > frigate/config/config.yml
      chmod 600 frigate/config/config.yml
    fi
  fi
  echo "Configured."
}

# ---- up -------------------------------------------------------------------------------------
pin_digest() { # VARIABLE image : records image@sha256 in images.env after a pull
  local var="$1" image="$2" digest
  digest="$(docker image inspect --format '{{index .RepoDigests 0}}' "$image" 2>/dev/null || true)"
  if [ -n "$digest" ]; then set_env images.env "$var" "$digest"; fi
}

step_up() {
  cd "$HOME_DIR"
  say "Downloading the programs (a few minutes the first time)"
  "${COMPOSE[@]}" pull --ignore-buildable || fail "couldn't download the images. Check the internet and run this again."
  pin_digest MOSQUITTO_IMAGE "${MOSQUITTO_IMAGE:-eclipse-mosquitto:2.0.20}"
  pin_digest FRIGATE_IMAGE "${FRIGATE_IMAGE:-ghcr.io/blakeblackshear/frigate:0.17.2}"
  pin_digest HOMEASSISTANT_IMAGE "${HOMEASSISTANT_IMAGE:-ghcr.io/home-assistant/home-assistant:2026.10.0}"
  say "Starting JARVIS Home"
  "${COMPOSE[@]}" up -d --build || fail "couldn't start. Run  bash setup-wsl.sh status  and tell Claude what it says."
  echo "Started."
}

# ---- link -----------------------------------------------------------------------------------
step_link() {
  local code="${1:-}" address="${2:-}"
  [ -n "$code" ] && [ -n "$address" ] || fail "usage: bash setup-wsl.sh link CODE https://your-laptop.your-tailnet.ts.net:8443"
  cd "$HOME_DIR"
  say "Linking to JARVIS (the first time Tailscale's address can take up to 10 minutes to start working)"
  local tries=0
  until "${COMPOSE[@]}" exec -T bridge python -m jarvis.homebridge link "$code" "$address"; do
    tries=$((tries + 1))
    if [ "$tries" -ge 22 ]; then fail "still not linked after about 10 minutes. Make a new code in JARVIS and run this again."; fi
    echo "Not yet. Trying again in 30 seconds ($tries)..."
    sleep 30
  done
  echo "Linked. JARVIS should now say Online."
}

# ---- status ---------------------------------------------------------------------------------
step_status() {
  cd "$HOME_DIR"
  "${COMPOSE[@]}" ps
}

# ---- camera, passwords ---------------------------------------------------------------------
step_camera() {
  cd "$HOME_DIR"
  local tries=0 stats=""
  while [ "$tries" -lt 12 ]; do
    stats="$("${COMPOSE[@]}" exec -T frigate curl -s http://127.0.0.1:5000/api/stats 2>/dev/null || true)"
    if printf '%s' "$stats" | grep -Eq '"camera_fps": *[1-9]'; then echo "Camera works."; return 0; fi
    tries=$((tries + 1))
    sleep 5
  done
  echo "Frigate does not see the camera's picture yet. Check the phone's address, login and password,"
  echo "that the IP Webcam app says it is running, and that both are on the same Wi-Fi."
  return 1
}

step_passwords() {
  cd "$HOME_DIR"
  "${COMPOSE[@]}" logs frigate 2>/dev/null | grep -i -m1 'password' || echo "Frigate has not printed a password yet."
}

case "${1:-}" in
  install) step_install ;;
  configure) step_configure ;;
  up) step_up ;;
  link) shift; step_link "$@" ;;
  status) step_status ;;
  camera) step_camera ;;
  passwords) step_passwords ;;
  *) echo "Usage: bash setup-wsl.sh install | configure | up | link CODE ADDRESS | status | camera | passwords" >&2; exit 2 ;;
esac
