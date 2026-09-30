#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# pSSID Credential Manager — one-command installer.
# Takes a fresh box to a working HTTPS deployment (PRD 9.8 / G7).
#
#   ./install.sh                 interactive
#   HOSTNAME=credmgr.example.edu TLS=self-signed SSO=false ./install.sh -y
# ---------------------------------------------------------------------------
set -euo pipefail

cd "$(dirname "$0")"

# Git Bash (MSYS) rewrites arguments that look like Unix paths (e.g. the
# openssl -subj "/CN=host") into Windows paths; disable that. No-op on Linux.
export MSYS_NO_PATHCONV=1

ASSUME_YES=false
[[ "${1:-}" == "-y" ]] && ASSUME_YES=true

prompt() { # name default question
  local var="$1" def="$2" q="$3" val="${!1:-}"
  if [[ -n "$val" ]]; then echo "$val"; return; fi
  if $ASSUME_YES; then echo "$def"; return; fi
  read -r -p "$q [$def]: " ans </dev/tty || true
  echo "${ans:-$def}"
}

echo "=== pSSID Credential Manager installer ==="

command -v docker >/dev/null || { echo "ERROR: docker is required"; exit 1; }
docker compose version >/dev/null 2>&1 || { echo "ERROR: docker compose plugin is required"; exit 1; }

# Hostname needs its own variable name. bash SETS $HOSTNAME itself (to the local
# machine name) whenever it is not already in the environment, so an empty
# $HOSTNAME can never mean "the operator has not chosen one" -- prompting on it
# was unreachable, and an interactive install silently baked the box's own
# hostname into BASE_URL and the TLS certificate CN.
#
# So: CREDMGR_HOSTNAME is the explicit override, and $HOSTNAME is demoted to the
# suggested default. `HOSTNAME=x ./install.sh -y` keeps working (with -y the
# default is what gets used), and an interactive run now actually asks.
HOSTNAME_VAL="$(prompt CREDMGR_HOSTNAME "${HOSTNAME:-credmgr.local}" "Public hostname")"
TLS="$(prompt TLS "self-signed" "TLS mode (self-signed|letsencrypt|none)")"
SSO="$(prompt SSO "false" "Enable OIDC SSO? (true|false)")"

mkdir -p secrets config certs

# --- Master key (KEK): 32 random bytes, mode 0400 (PRD R1) ---
if [[ ! -f secrets/master.key ]]; then
  echo "Generating master key -> secrets/master.key (0400)"
  head -c 32 /dev/urandom > secrets/master.key
  chmod 0400 secrets/master.key
else
  echo "Keeping existing secrets/master.key"
fi
echo ">>> BACK UP secrets/master.key SEPARATELY from the database. Without it, all secrets are unrecoverable."

# --- roles.json ---
[[ -f config/roles.json ]] || cp -n config/roles.example.json config/roles.json 2>/dev/null || cat > config/roles.json <<'EOF'
{ "groups": { "credmgr-admin": "write", "credmgr-view": "read" } }
EOF

# --- Self-signed certs ---
if [[ "$TLS" == "self-signed" && ( ! -f certs/fullchain.pem ) ]]; then
  echo "Generating self-signed certificate for $HOSTNAME_VAL"
  openssl req -x509 -newkey rsa:2048 -nodes -days 825 \
    -keyout certs/privkey.pem -out certs/fullchain.pem \
    -subj "/CN=$HOSTNAME_VAL" >/dev/null 2>&1
fi

SESSION_SECRET="$(head -c 32 /dev/urandom | base64)"

# --- .env ---
if [[ ! -f .env ]]; then
  echo "Writing .env"
  cat > .env <<EOF
PORT=8080
NODE_ENV=production
BASE_URL=https://$HOSTNAME_VAL
MONGO_URL=mongodb://mongo:27017
MONGO_DB=credmgr
KEK_FILE=/run/secrets/master.key
ROLE_MAP_FILE=/etc/pssid-credmgr/roles.json
SSO_ENABLED=$SSO
OPEN_WRITE=false
SESSION_SECRET=$SESSION_SECRET
ROTATION_WARN_DAYS=180
# When SSO_ENABLED=true, also set:
# OIDC_ISSUER_BASE_URL=
# OIDC_CLIENT_ID=
# OIDC_CLIENT_SECRET=
EOF
  chmod 0600 .env
else
  echo "Keeping existing .env"
fi

echo "Building and starting the stack..."
docker compose up -d --build

# --- Wait for the stack to actually answer -------------------------------
# "Started the containers" is not the same as "the app works": a bad KEK, an
# unreachable Mongo, or a bad OIDC block all leave the containers up and the API
# dead. Reporting success without checking is how an operator finds out from a
# browser error ten minutes later instead of from the installer.
echo
HEALTHY=false
HEALTH_URL=""

if ! command -v curl >/dev/null 2>&1; then
  # No curl: skip the check rather than fail an otherwise-good install.
  echo "NOTE: curl not found, skipping the health check."
  echo "      Verify manually once curl is available:"
  echo "        curl -k https://$HOSTNAME_VAL/api/health"
  HEALTHY=true
  HEALTH_URL="(not verified - curl is not installed)"
else
  # Tunable: a first run that builds images on a slow box legitimately needs
  # longer, and CI wants to fail fast rather than sit on a dead stack.
  HEALTH_TIMEOUT_SECS="${HEALTH_TIMEOUT_SECS:-120}"
  attempts=$(( HEALTH_TIMEOUT_SECS / 2 ))
  [[ "$attempts" -lt 1 ]] && attempts=1

  echo -n "Waiting up to ${HEALTH_TIMEOUT_SECS}s for the API to become healthy"
  for _ in $(seq 1 "$attempts"); do
    # Try HTTPS first, then plain HTTP, so this works for every TLS mode.
    for url in "https://localhost/api/health" "http://localhost/api/health"; do
      if curl -skf --max-time 3 "$url" 2>/dev/null | grep -q '"status":"ok"'; then
        HEALTHY=true
        HEALTH_URL="$url"
        break 2
      fi
    done
    echo -n "."
    sleep 2
  done
  echo
fi

if $HEALTHY; then
  echo "=== Done ==="
  [[ -n "$HEALTH_URL" ]] && echo "  Reached $HEALTH_URL"
else
  echo "=== Started, but the API never became healthy ==="
  echo "The containers are up; the application is not answering. Check:"
  echo "  docker compose ps"
  echo "  docker compose logs --tail=50 app"
fi
echo

echo "URL:     https://$HOSTNAME_VAL/"
echo "Health:  https://$HOSTNAME_VAL/api/health"
if [[ "$SSO" == "false" ]]; then
  echo "NOTE: SSO is off and OPEN_WRITE=false -> the app is READ-ONLY."
  echo "      Set OPEN_WRITE=true in .env for lab write access, or configure OIDC."
fi
echo "Remember to back up secrets/master.key separately from your MongoDB dumps."

# Exit non-zero on an unhealthy stack so CI and `bootstrap`-style callers notice.
$HEALTHY
