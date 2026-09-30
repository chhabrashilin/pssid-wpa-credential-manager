#!/usr/bin/env bash
# Run the probe-health suites. Standard library only -- no pip install needed.
#
#   ./run-tests.sh            # unit + integration
#   ./run-tests.sh --demo     # also run the end-to-end demo
set -euo pipefail
cd "$(dirname "$0")"

PYTHON="${PYTHON:-python3}"
command -v "$PYTHON" >/dev/null || { echo "ERROR: $PYTHON not found" >&2; exit 1; }

echo "== unit + integration =="
"$PYTHON" -m unittest discover -s tests -t . "${VERBOSE:+-v}"

if [[ "${1:-}" == "--demo" ]]; then
  echo
  echo "== demo =="
  bash demo.sh
fi
