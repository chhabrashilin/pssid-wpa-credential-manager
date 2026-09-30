#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Run the pssid-daemon test suite.
#
# Needs python3 (3.9+) and jinja2. Nothing else -- croniter and pscheduler are
# stubbed, which is the whole point (see harness/stubs.py).
#
#   ./run-tests.sh                    # all suites
#   ./run-tests.sh tests.test_defects # one module
#   PSSID_DAEMON_PATH=/path/to/pssid-daemon.py ./run-tests.sh
# ---------------------------------------------------------------------------
set -euo pipefail
cd "$(dirname "$0")"

PYTHON="${PYTHON:-python3}"

command -v "$PYTHON" >/dev/null || {
  echo "ERROR: $PYTHON not found. Set PYTHON=... to override." >&2
  exit 1
}

if ! "$PYTHON" -c "import jinja2" 2>/dev/null; then
  echo "ERROR: jinja2 is required (the daemon imports it at module scope)." >&2
  echo "  pip install jinja2      # or: apt-get install python3-jinja2" >&2
  exit 1
fi

# Locate the daemon before running, so a missing checkout is one clear error
# rather than 66 skips that look like success.
if ! "$PYTHON" -c "from harness import loader; loader.daemon_path()" 2>/dev/null; then
  echo "ERROR: could not find pssid-daemon.py." >&2
  echo "  Expected at ../../../../pssid-daemon/pssid-daemon.py relative to harness/," >&2
  echo "  i.e. the daemon cloned beside this repository." >&2
  echo "  Override with PSSID_DAEMON_PATH=/path/to/pssid-daemon.py" >&2
  exit 1
fi

echo "Daemon under test: $("$PYTHON" -c 'from harness import loader; print(loader.daemon_path())')"
echo

if [[ $# -gt 0 ]]; then
  exec "$PYTHON" -m unittest "$@" -v
fi

# Buffer stdout: the daemon prints a great deal, and it drowns the results.
exec "$PYTHON" -m unittest discover -s tests -t . --buffer "${VERBOSE:+-v}"
