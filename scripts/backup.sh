#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Database backup (PRD 9.8).
#
# IMPORTANT: this dumps the MongoDB database only. Encrypted payloads stay
# encrypted in the dump — they are USELESS without the KEK. You MUST back up
# secrets/master.key SEPARATELY (different medium, different access control).
# A dump + KEK together reconstitute every secret; keep them apart.
# ---------------------------------------------------------------------------
set -euo pipefail
cd "$(dirname "$0")/.."

OUT_DIR="${1:-./backups}"
STAMP="$(date +%Y%m%d-%H%M%S)"
mkdir -p "$OUT_DIR"

echo "Dumping MongoDB -> $OUT_DIR/credmgr-$STAMP.archive.gz"
docker compose exec -T mongo mongodump --db=credmgr --archive --gzip > "$OUT_DIR/credmgr-$STAMP.archive.gz"

echo "Done. Reminder: back up secrets/master.key separately — it is NOT in this dump."
echo "Restore with: docker compose exec -T mongo mongorestore --gzip --archive < <dump>"
