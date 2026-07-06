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

HOSTNAME_VAL="$(prompt HOSTNAME "credmgr.local" "Public hostname")"
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

echo
echo "=== Done ==="
echo "URL:     https://$HOSTNAME_VAL/"
echo "Health:  https://$HOSTNAME_VAL/api/health"
[[ "$SSO" == "false" ]] && echo "NOTE: SSO is off and OPEN_WRITE=false -> the app is READ-ONLY. Set OPEN_WRITE=true in .env for lab write access, or configure OIDC."
echo "Remember to back up secrets/master.key separately from your MongoDB dumps."
