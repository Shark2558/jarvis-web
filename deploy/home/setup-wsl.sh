#!/usr/bin/env bash
# JARVIS home kit, the Ubuntu (WSL2) half of the setup. setup-windows.ps1 runs this for you; you
# can also run it by hand:  bash setup-wsl.sh install | configure | up | link CODE ADDRESS | status | camera | passwords | ha-token | faces-code
# Re-runnable: every step checks first and skips what is already done.
#
#   install    Docker Engine (from Docker's apt repository) and systemd for Ubuntu
#   configure  copies the kit to ~/jarvis-home, writes bridge.env and frigate.env (passwords made
#              here, kept here; the camera address only in frigate.env), the Mosquitto users
#              (frigate writes, bridge only reads; the file is the broker's own), Frigate's
#              settings, and lets the bridge clean up Frigate's face pictures
#   up         pulls the images, records each image's digest in images.env, starts everything,
#              prints the laptop Faces page's code
#   link       links the bridge to JARVIS with the code from Integrations -> Home -> Link
#   status     says in plain words what is running
#   camera     says "Camera works" once Frigate is receiving the phone's picture
#   passwords  prints the Frigate login the first start made (write it down)
#   ha-token   saves the Home Assistant token (HA_TOKEN) once Home Assistant runs; restarts the bridge
#   faces-code prints the laptop Faces page's code again
#
# Environment (set by setup-windows.ps1, all optional):
#   KIT_DIR        where the kit is (default: this script's folder)
#   HOME_DIR       where the running copy lives (default: ~/jarvis-home)
#   CAMERA_URL     the phone camera's RTSP address, with its login (kept only in frigate.env)
#   HA_TOKEN       the Home Assistant token for the "JARVIS bridge" user (ha-token, later)
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
    sudo apt-get install -y ca-certificates curl openssl acl
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
  # Docker's package makes a `docker` group but adds nobody; the later steps run docker as you
  if ! id -nG | tr ' ' '\n' | grep -qx docker; then
    sudo usermod -aG docker "$(id -un)"
    echo "RESTART_WSL: Ubuntu must restart once so you can use Docker (the Windows script does it)."
  fi
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

# Frigate (root in its container) writes face and doorstep pictures; the bridge (uid and gid 10001)
# must be able to delete them (a removed person's pictures, strangers' after 72 hours). Deleting a
# file needs write access to its folder: the folders belong to group 10001, new files and folders
# inside keep that group (setgid) and stay group-writable (default ACL).
share_face_folders() {
  say "Letting the bridge clean up Frigate's face pictures"
  local dirs=(frigate/media/clips/faces frigate/media/clips/doorstep)
  sudo mkdir -p frigate/media/clips/faces/train frigate/media/clips/doorstep/train
  sudo chgrp -R 10001 "${dirs[@]}"
  sudo chmod -R g+rwX "${dirs[@]}"
  sudo find "${dirs[@]}" -type d -exec chmod g+s {} +
  if command -v setfacl >/dev/null 2>&1; then
    sudo setfacl -R -d -m g:10001:rwX "${dirs[@]}"
  else
    echo "Note: install the acl package (sudo apt-get install acl) and run configure again."
  fi
}

step_configure() {
  say "Preparing the home folder $HOME_DIR"
  mkdir -p "$HOME_DIR"
  cp -a "$KIT_DIR"/. "$HOME_DIR"/
  cd "$HOME_DIR"
  mkdir -p bridge-data mosquitto-data frigate/config frigate/media homeassistant
  sudo chown 10001:10001 bridge-data
  sudo chmod 700 bridge-data # it is the bridge's now, so only sudo may change it
  if [ ! -f bridge.env ]; then cp bridge.env.example bridge.env; fi
  chmod 600 bridge.env
  if [ -z "$(get_env bridge.env MQTT_USER)" ]; then set_env bridge.env MQTT_USER bridge; fi
  if [ -z "$(get_env bridge.env MQTT_PASSWORD)" ]; then set_env bridge.env MQTT_PASSWORD "$(random_secret)"; fi
  if [ -n "${HA_TOKEN:-}" ]; then set_env bridge.env HA_TOKEN "$HA_TOKEN"; fi
  touch images.env
  chmod 600 images.env

  say "Writing Frigate's private settings (only Frigate reads frigate.env)"
  touch frigate.env
  chmod 600 frigate.env
  local frigate_pw camera
  frigate_pw="$(get_env frigate.env FRIGATE_MQTT_PASSWORD)"
  if [ -z "$frigate_pw" ]; then frigate_pw="$(random_secret)"; fi
  camera="${CAMERA_URL:-$(get_env frigate.env FRIGATE_GATE_RTSP)}"
  # printf, not sed: the camera's password may hold characters sed would read as commands
  printf 'FRIGATE_MQTT_USER=frigate\nFRIGATE_MQTT_PASSWORD=%s\nFRIGATE_GATE_RTSP=%s\n' \
    "$frigate_pw" "$camera" > frigate.env

  say "Making the Mosquitto users (frigate writes, bridge only reads; nobody without a password)"
  local mqtt_pw; mqtt_pw="$(get_env bridge.env MQTT_PASSWORD)"
  sudo rm -f mosquitto/passwd # a re-run replaces it (the last run gave it to the broker)
  : > mosquitto/passwd
  docker run --rm -v "$HOME_DIR/mosquitto:/work" "${MOSQUITTO_IMAGE:-eclipse-mosquitto:2.0.20}" \
    mosquitto_passwd -b -c /work/passwd frigate "$frigate_pw" >/dev/null
  docker run --rm -v "$HOME_DIR/mosquitto:/work" "${MOSQUITTO_IMAGE:-eclipse-mosquitto:2.0.20}" \
    mosquitto_passwd -b /work/passwd bridge "$mqtt_pw" >/dev/null
  # Mosquitto runs as its own user (uid 1883) and reads this file itself: its own, private
  sudo chown 1883:1883 mosquitto/passwd
  sudo chmod 600 mosquitto/passwd

  share_face_folders

  if [ -f frigate/config.yml ] && [ ! -f frigate/config/config.yml ]; then
    say "Copying Frigate's settings (the camera address stays in frigate.env, not here)"
    cp frigate/config.yml frigate/config/config.yml
  fi
  # Frigate keeps (and edits) its own copy; an install from before 10 Nov named the gate zone
  # `gate`, which Frigate 0.17 refuses (same name as the camera). Rename only that zone.
  if [ -f frigate/config/config.yml ] && grep -q '^      gate:$' frigate/config/config.yml; then
    say "Renaming the gate zone to gate_zone in Frigate's settings (Frigate 0.17 needs it)"
    sudo sed -i -e 's/^      gate:$/      gate_zone:/' -e 's/^\( *\)- gate$/\1- gate_zone/' frigate/config/config.yml
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
  docker pull "${BASE_IMAGE:-python:3.12-slim}" >/dev/null || fail "couldn't download the base image. Check the internet and run this again."
  pin_digest BASE_IMAGE "${BASE_IMAGE:-python:3.12-slim}"
  pin_digest MOSQUITTO_IMAGE "${MOSQUITTO_IMAGE:-eclipse-mosquitto:2.0.20}"
  pin_digest FRIGATE_IMAGE "${FRIGATE_IMAGE:-ghcr.io/blakeblackshear/frigate:0.17.2}"
  pin_digest HOMEASSISTANT_IMAGE "${HOMEASSISTANT_IMAGE:-ghcr.io/home-assistant/home-assistant:2026.10.0}"
  say "Starting JARVIS Home"
  "${COMPOSE[@]}" up -d --build || fail "couldn't start. Run  bash setup-wsl.sh status  and tell Claude what it says."
  # Frigate reads its settings only when it starts; `up` leaves a running Frigate alone.
  local sum; sum="$(sha256sum frigate/config/config.yml 2>/dev/null | cut -d' ' -f1 || true)"
  if [ -f .frigate-config.sha ] && [ "$(cat .frigate-config.sha)" != "$sum" ]; then
    say "Restarting Frigate with its new settings"
    "${COMPOSE[@]}" restart frigate >/dev/null || fail "couldn't restart Frigate. Run  bash setup-wsl.sh status  and tell Claude."
  fi
  printf '%s\n' "$sum" > .frigate-config.sha
  echo "Started."
  show_faces_code
}

# ---- the laptop Faces page's code ------------------------------------------------------------
show_faces_code() { # the bridge makes the code on its first start, in its private data folder
  local code="" tries=0
  while [ "$tries" -lt 10 ]; do
    code="$("${COMPOSE[@]}" exec -T bridge cat /data/faces_code.txt 2>/dev/null | tr -d '\r\n' || true)"
    if [ -n "$code" ]; then break; fi
    tries=$((tries + 1))
    sleep 3
  done
  if [ -n "$code" ]; then
    echo "Faces page on this laptop: http://localhost:8098/faces   code: $code"
  else
    echo "The Faces page code is not ready yet. Later run:  bash ~/jarvis-home/setup-wsl.sh faces-code"
  fi
}

# ---- the Home Assistant token, later ----------------------------------------------------------
step_ha_token() { # once Home Assistant runs and has its accounts (setup-windows.ps1 -HaToken)
  cd "$HOME_DIR"
  [ -n "${HA_TOKEN:-}" ] || fail "no Home Assistant token was given. Run setup-windows.ps1 -HaToken and paste it."
  set_env bridge.env HA_TOKEN "$HA_TOKEN"
  "${COMPOSE[@]}" up -d --force-recreate bridge >/dev/null || fail "couldn't restart the bridge. Run  bash setup-wsl.sh status  and tell Claude what it says."
  echo "Saved. The bridge now talks to Home Assistant."
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
  show_faces_code
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
  ha-token) step_ha_token ;;
  faces-code) cd "$HOME_DIR"; show_faces_code ;;
  *) echo "Usage: bash setup-wsl.sh install | configure | up | link CODE ADDRESS | status | camera | passwords | ha-token | faces-code" >&2; exit 2 ;;
esac
