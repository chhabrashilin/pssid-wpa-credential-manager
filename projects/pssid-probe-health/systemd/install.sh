#!/usr/bin/env bash
# Install the reporter and its timer on a probe. Idempotent.
set -euo pipefail

[[ $EUID -eq 0 ]] || { echo "Run as root." >&2; exit 1; }

SRC="$(cd "$(dirname "$0")/.." && pwd)"

echo "Installing the package to /usr/local/lib/pssid_probe_health"
rm -rf /usr/local/lib/pssid_probe_health
cp -r "$SRC/pssid_probe_health" /usr/local/lib/pssid_probe_health

cat > /usr/local/bin/pssid-probe-health <<'LAUNCHER'
#!/usr/bin/env python3
import sys
sys.path.insert(0, "/usr/local/lib")
from pssid_probe_health.cli import main
raise SystemExit(main())
LAUNCHER
chmod 0755 /usr/local/bin/pssid-probe-health

install -m 0644 "$SRC/systemd/pssid-probe-health.service" /etc/systemd/system/
install -m 0644 "$SRC/systemd/pssid-probe-health.timer"   /etc/systemd/system/

if [[ ! -f /etc/pssid/health.env ]]; then
  install -d -m 0755 /etc/pssid
  cat > /etc/pssid/health.env <<'ENVEOF'
# Extra arguments for pssid-probe-health.
# To ship reports to a collector:
#   PSSID_HEALTH_ARGS=--post https://credmgr.example.edu/api/v1/probe-health
PSSID_HEALTH_ARGS=
ENVEOF
  chmod 0644 /etc/pssid/health.env
fi

systemctl daemon-reload
systemctl enable --now pssid-probe-health.timer

echo
echo "Installed. Check it now with:"
echo "  pssid-probe-health"
echo "  systemctl list-timers pssid-probe-health.timer"
