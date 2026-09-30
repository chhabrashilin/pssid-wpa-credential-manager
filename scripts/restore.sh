#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Restore the credential-manager database from an archive made by backup.sh.
#
# READ THIS FIRST: the archive contains only envelope-encrypted payloads. It is
# unreadable without the SAME master key (KEK) that was in use when it was
# taken. Restoring a dump against a different secrets/master.key produces a
# database that loads fine and fails to decrypt every credential -- so this
# script checks that a KEK is present and warns before touching anything.
#
#   scripts/restore.sh ./backups/credmgr-20260729-120000.archive.gz
#   scripts/restore.sh                 # pick from ./backups interactively
# ---------------------------------------------------------------------------
set -euo pipefail
cd "$(dirname "$0")/.."

BACKUP_DIR="${BACKUP_DIR:-./backups}"

DB="${MONGO_DB:-}"
if [[ -z "$DB" && -f .env ]]; then
  DB="$(grep -E '^MONGO_DB=' .env | head -1 | cut -d= -f2- | tr -d '"'"'"' \r')"
fi
DB="${DB:-credmgr}"

# --- Pick an archive -------------------------------------------------------
ARCHIVE="${1:-}"
if [[ -z "$ARCHIVE" ]]; then
  shopt -s nullglob
  CANDIDATES=("$BACKUP_DIR"/*.archive.gz "$BACKUP_DIR"/*.gz)
  if [[ ${#CANDIDATES[@]} -eq 0 ]]; then
    echo "No archives found in $BACKUP_DIR" >&2
    echo "Usage: scripts/restore.sh <archive.gz>" >&2
    exit 1
  fi
  echo "Available backups:"
  select FILE in "${CANDIDATES[@]}"; do
    [[ -n "$FILE" ]] && { ARCHIVE="$FILE"; break; }
    echo "Invalid selection."
  done
fi

[[ -f "$ARCHIVE" ]] || { echo "Archive not found: $ARCHIVE" >&2; exit 1; }
gzip -t "$ARCHIVE" 2>/dev/null || { echo "Not a valid gzip archive: $ARCHIVE" >&2; exit 1; }

# --- The KEK warning -------------------------------------------------------
# This is the failure that wastes an afternoon: the restore "works", the app
# starts, and every single credential fails to decrypt because the key that
# wrapped those DEKs is gone.
if [[ ! -f secrets/master.key ]]; then
  echo "ERROR: secrets/master.key is missing." >&2
  echo "       Restore it FIRST -- without the original KEK this archive is" >&2
  echo "       permanently unreadable, and installing a new key will not help." >&2
  exit 1
fi

echo "About to restore into database '$DB' with --drop."
echo "  archive: $ARCHIVE"
echo "  KEK:     secrets/master.key (present)"
echo
echo "This REPLACES the current contents of '$DB'."
echo "If this key is not the one that was in use when the archive was taken,"
echo "every credential will restore intact and decrypt to nothing."
echo
if [[ "${1:-}" != "--yes" && "${2:-}" != "--yes" && "${ASSUME_YES:-false}" != "true" ]]; then
  read -r -p "Type 'restore' to continue: " ans </dev/tty || ans=""
  [[ "$ans" == "restore" ]] || { echo "Aborted."; exit 1; }
fi

echo "Restoring..."
docker compose exec -T mongo mongorestore \
  --archive --gzip --drop --nsInclude="$DB.*" < "$ARCHIVE"

echo
echo "Restore complete."
echo "Verify before trusting it:"
echo "  curl -k https://localhost/api/health"
echo "  curl -k https://localhost/api/v1/networks   # fingerprints should be unchanged"
echo
echo "A fingerprint that still matches what it was before the restore proves the"
echo "KEK and the data are the matching pair."
