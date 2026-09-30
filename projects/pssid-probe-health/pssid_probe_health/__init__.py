"""
pssid-probe-health -- answer "is this probe actually testing?"

Nothing else in the pSSID system can answer that question. The daemon skips a
batch silently when a wpa_supplicant config is missing (pssid-daemon.py:483),
the GUI's delivery script reports delivery and explicitly not adoption, and
syslog is never aggregated. A probe with a broken config looks exactly like a
healthy one.

Standard library only, on purpose: this runs on probes that are provisioned by
Ansible and should not need a pip install to report their own health.
"""

from .model import CheckResult, HealthReport, Status

__all__ = ["CheckResult", "HealthReport", "Status", "__version__"]
__version__ = "1.0.0"
