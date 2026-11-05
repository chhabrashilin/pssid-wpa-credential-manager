#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Database backup (PRD 9.8).
#
# IMPORTANT: this dumps the MongoDB database only. Encrypted payloads stay
# encrypted in the dump - they are USELESS without the KEK. You MUST back up
# secrets/master.key SEPARATELY (different medium, different access control).
# A dump + KEK together reconstitute every secret; keep them apart.
# ---------------------------------------------------------------------------
set -euo pipefail
cd "$(dirname "$0")/.."

OUT_DIR="${1:-./backups}"
STAMP="$(date +%Y%m%d-%H%M%S)"
# NOTE: the output directory is created only once the checks below pass, so a
# refused backup leaves no trace at all -- not even an empty directory that a
# retention job might later mistake for a backup location in good standing.

# The database name is configurable in .env. Hard-coding it here meant that a
# deployment which set MONGO_DB to anything else got a backup of a database
# that does not exist -- and mongodump exits 0 on a missing database, so the
# result was a valid, well-formed, EMPTY archive reported as a success. A
# backup that silently contains nothing is worse than no backup at all.
DB="${MONGO_DB:-}"
if [[ -z "$DB" && -f .env ]]; then
  DB="$(grep -E '^MONGO_DB=' .env | head -1 | cut -d= -f2- | tr -d '"'"'"' \r')"
fi
DB="${DB:-credmgr}"

ARCHIVE="$OUT_DIR/credmgr-$STAMP.archive.gz"
TMP="$ARCHIVE.incomplete"
# Never leave a partial file looking like a finished backup.
trap 'rm -f "$TMP"' EXIT

echo "Database: $DB"

# --- Refuse to "back up" an empty database --------------------------------
# The failure this catches is a wrong DB name or a stack that came up against
# the wrong volume. Both produce a clean, empty, plausible archive.
COLLECTIONS="$(docker compose exec -T mongo mongosh "$DB" --quiet \
  --eval 'db.getCollectionNames().length' 2>/dev/null | tr -dc '0-9')"

if [[ -z "$COLLECTIONS" ]]; then
  echo "ERROR: could not query MongoDB. Is the stack running? (docker compose ps)" >&2
  exit 1
fi
if [[ "$COLLECTIONS" -eq 0 ]]; then
  echo "ERROR: database '$DB' has no collections - refusing to write an empty backup." >&2
  echo "       Check MONGO_DB in .env against the running stack." >&2
  exit 1
fi
echo "Found $COLLECTIONS collections."

mkdir -p "$OUT_DIR"

# --- Dump to a temporary name, then promote -------------------------------
# The redirection target is created the instant the shell parses the line, so
# writing straight to the final name left a 0-byte "backup" behind whenever
# mongodump failed.
echo "Dumping -> $ARCHIVE"
if ! docker compose exec -T mongo mongodump --db="$DB" --archive --gzip > "$TMP"; then
  echo "ERROR: mongodump failed; no backup written." >&2
  exit 1
fi

if ! gzip -t "$TMP" 2>/dev/null; then
  echo "ERROR: the dump is not a valid gzip stream; no backup written." >&2
  exit 1
fi

SIZE="$(wc -c < "$TMP" | tr -d ' ')"
if [[ "$SIZE" -lt 1024 ]]; then
  echo "ERROR: the dump is only ${SIZE} bytes, which cannot be a real backup." >&2
  exit 1
fi

mv "$TMP" "$ARCHIVE"
trap - EXIT

echo "Done: $ARCHIVE (${SIZE} bytes, $COLLECTIONS collections)"
echo
echo "Reminder: secrets/master.key is NOT in this dump. Back it up separately -"
echo "without it this archive is unreadable, and with it the archive is plaintext."
echo "Restore with: scripts/restore.sh $ARCHIVE"
