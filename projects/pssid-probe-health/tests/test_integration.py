"""
Integration tests: the real CLI against a real filesystem.

``test_checks.py`` proves the logic against an in-memory fake. This proves the
TOOL -- real files, real ``stat``, real ``/proc`` parsing, real argument
handling, real exit codes -- by building fixture probe trees and pointing
``--root`` at them.

The distinction matters. A fake that agrees with a buggy implementation of
``exists()`` would let both pass; these tests would not.
"""

from __future__ import annotations

import json
import os
import shutil
import stat
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pssid_probe_health import cli  # noqa: E402
from pssid_probe_health.checks import Environment  # noqa: E402
from pssid_probe_health.model import Status  # noqa: E402


def build_probe_tree(root, hostname="probe-1", declared=("eduroam",), delivered=("eduroam",),
                     interface="wlan0", daemon_running=True, mode=0o600):
    """Create a fixture probe filesystem under ``root``."""
    os.makedirs(os.path.join(root, "etc/pssid"), exist_ok=True)
    os.makedirs(os.path.join(root, "etc/wpa_supplicant"), exist_ok=True)
    os.makedirs(os.path.join(root, "sys/class/net"), exist_ok=True)

    if interface and not interface.startswith("$"):
        open(os.path.join(root, "sys/class/net", interface), "w").close()

    # A realistic process table. Even a probe with no daemon has other
    # processes -- an EMPTY /proc means enumeration failed, which is a
    # different (UNKNOWN) verdict, exercised separately below.
    for pid, cmdline in [(1, b"/sbin/init\x00"), (900, b"/usr/sbin/sshd\x00-D\x00")]:
        d = os.path.join(root, "proc", str(pid))
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "cmdline"), "wb") as fh:
            fh.write(cmdline)

    if daemon_running:
        proc = os.path.join(root, "proc/4242")
        os.makedirs(proc, exist_ok=True)
        with open(os.path.join(proc, "cmdline"), "wb") as fh:
            fh.write(b"python3\x00/usr/bin/pssid/pssid-daemon.py\x00")

    config = {
        "hosts": [{"name": hostname, "batches": ["batch_A"], "data": {"interface": interface}}],
        "host_groups": [],
        "schedules": [{"name": "s", "repeat": "*/2 * * * *"}],
        "ssid_profiles": [{"name": p, "ssid": p} for p in declared],
        "tests": [{"name": "t", "type": "http", "spec": {"url": "x"}}],
        "jobs": [{"name": "j", "parallel": "True", "tests": ["t"], "continue-if": "false"}],
        "batches": [{
            "name": "batch_A", "priority": 1, "test_interface": interface,
            "ssid_profiles": list(declared), "schedules": ["s"], "jobs": ["j"],
        }],
    }
    with open(os.path.join(root, "etc/pssid/pssid_config.json"), "w") as fh:
        json.dump(config, fh)

    for profile in delivered:
        path = os.path.join(root, "etc/wpa_supplicant", f"wpa_supplicant_{profile}.conf")
        with open(path, "w") as fh:
            fh.write(
                'network={\n'
                f'    ssid="{profile}"\n'
                '    identity="pssid-probe@example.edu"\n'
                '    password=hash:8846f7eaee8fb117ad06bdd830b7586c\n'
                '}\n'
            )
        os.chmod(path, mode)

    return root


class FixtureProbeTestCase(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="pssid-probe-")
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)

    def report_for(self, **kwargs):
        hostname = kwargs.pop("hostname", "probe-1")
        build_probe_tree(self.root, hostname=hostname, **kwargs)
        env = Environment(hostname=hostname, root=self.root)
        return cli.run_checks(env)


class TestHealthyProbe(FixtureProbeTestCase):
    def test_fully_provisioned_probe_is_testing(self):
        report = self.report_for()
        self.assertTrue(report.is_testing, report.to_text())
        self.assertEqual(report.status, Status.OK, report.to_text())
        self.assertEqual(report.exit_code, 0)

    def test_every_check_reports_ok(self):
        report = self.report_for()
        not_ok = [c.name for c in report.checks if c.status is not Status.OK]
        self.assertEqual(not_ok, [], report.to_text())


class TestSilentSkipOnRealFiles(FixtureProbeTestCase):
    """The headline failure, on a real filesystem rather than a mock."""

    def test_missing_profile_is_detected_and_named(self):
        report = self.report_for(declared=("eduroam", "MWireless"), delivered=("eduroam",))
        self.assertFalse(report.is_testing)
        self.assertEqual(report.exit_code, 2)

        wpa = next(c for c in report.checks if c.name == "wpa.configs")
        self.assertEqual(wpa.status, Status.CRITICAL)
        self.assertEqual(wpa.evidence["missing"], ["MWireless"])
        self.assertIn("MWireless", wpa.remedy)

    def test_zero_byte_file_counts_as_missing(self):
        build_probe_tree(self.root, declared=("eduroam",), delivered=("eduroam",))
        path = os.path.join(self.root, "etc/wpa_supplicant/wpa_supplicant_eduroam.conf")
        open(path, "w").close()  # truncate to zero, like the shipped placeholder
        self.assertEqual(os.stat(path).st_size, 0)

        report = cli.run_checks(Environment(hostname="probe-1", root=self.root))
        wpa = next(c for c in report.checks if c.name == "wpa.configs")
        self.assertEqual(wpa.status, Status.CRITICAL)
        self.assertIn("eduroam", wpa.evidence["missing"])

    def test_all_profiles_present_is_ok(self):
        report = self.report_for(declared=("a", "b", "c"), delivered=("a", "b", "c"))
        wpa = next(c for c in report.checks if c.name == "wpa.configs")
        self.assertEqual(wpa.status, Status.OK)


class TestRealFileModes(FixtureProbeTestCase):
    @unittest.skipIf(os.name == "nt", "POSIX file modes required")
    def test_world_readable_credential_warns(self):
        report = self.report_for(mode=0o644)
        wpa = next(c for c in report.checks if c.name == "wpa.configs")
        self.assertEqual(wpa.status, Status.WARN)
        self.assertEqual(wpa.evidence["insecure"], ["eduroam"])

    @unittest.skipIf(os.name == "nt", "POSIX file modes required")
    def test_mode_is_reported_from_a_real_stat(self):
        report = self.report_for(mode=0o600)
        wpa = next(c for c in report.checks if c.name == "wpa.configs")
        self.assertEqual(wpa.evidence["present"]["eduroam"]["mode"], oct(0o600))


class TestProcessTable(FixtureProbeTestCase):
    def test_daemon_detected_from_a_real_proc_tree(self):
        report = self.report_for(daemon_running=True)
        daemon = next(c for c in report.checks if c.name == "daemon.running")
        self.assertEqual(daemon.status, Status.OK)

    def test_absent_daemon_is_critical(self):
        """Other processes present, pssid-daemon among them absent."""
        report = self.report_for(daemon_running=False)
        daemon = next(c for c in report.checks if c.name == "daemon.running")
        self.assertEqual(daemon.status, Status.CRITICAL)
        self.assertGreater(daemon.evidence["processes_scanned"], 0)

    def test_unreadable_process_table_is_unknown_not_critical(self):
        """
        The distinction that keeps this honest: "no daemon" and "I could not
        look" are different answers, and only the first is a failure. Caught by
        a real test failure while writing this suite.
        """
        empty = tempfile.mkdtemp(prefix="pssid-noproc-")
        self.addCleanup(shutil.rmtree, empty, ignore_errors=True)
        build_probe_tree(empty)
        shutil.rmtree(os.path.join(empty, "proc"))

        report = cli.run_checks(Environment(hostname="probe-1", root=empty))
        daemon = next(c for c in report.checks if c.name == "daemon.running")
        self.assertEqual(daemon.status, Status.UNKNOWN)


class TestCliBehaviour(FixtureProbeTestCase):
    def test_exit_code_zero_for_healthy(self):
        build_probe_tree(self.root)
        rc = cli.main(["--root", self.root, "--hostname", "probe-1", "--quiet"])
        self.assertEqual(rc, 0)

    def test_exit_code_two_for_missing_credentials(self):
        build_probe_tree(self.root, declared=("a", "b"), delivered=("a",))
        rc = cli.main(["--root", self.root, "--hostname", "probe-1", "--quiet"])
        self.assertEqual(rc, 2)

    def test_unknown_hostname_exits_two(self):
        build_probe_tree(self.root, hostname="probe-1")
        rc = cli.main(["--root", self.root, "--hostname", "not-me", "--quiet"])
        self.assertEqual(rc, 2)

    def test_warn_days_flag_actually_changes_the_verdict(self):
        """
        Regression guard. This flag was originally parsed and never passed to the
        check -- exactly the dead-flag defect pinned as D4 in the daemon suite.
        """
        build_probe_tree(self.root)
        env_strict = Environment(hostname="probe-1", root=self.root, warn_days=-1)
        env_lax = Environment(hostname="probe-1", root=self.root, warn_days=3650)

        strict = next(c for c in cli.run_checks(env_strict).checks if c.name == "config.age")
        lax = next(c for c in cli.run_checks(env_lax).checks if c.name == "config.age")

        self.assertEqual(strict.status, Status.WARN)
        self.assertEqual(lax.status, Status.OK)

    def test_json_output_parses(self):
        build_probe_tree(self.root)
        env = Environment(hostname="probe-1", root=self.root)
        doc = json.loads(cli.run_checks(env).to_json())
        self.assertEqual(doc["probe_id"], "probe-1")
        self.assertTrue(doc["is_testing"])

    def test_root_prefix_isolates_from_the_real_host(self):
        """
        With --root set, nothing outside the fixture tree is consulted. Proven by
        pointing at an empty root and requiring every filesystem check to fail.
        """
        empty = tempfile.mkdtemp(prefix="pssid-empty-")
        self.addCleanup(shutil.rmtree, empty, ignore_errors=True)
        report = cli.run_checks(Environment(hostname="probe-1", root=empty))
        config = next(c for c in report.checks if c.name == "config.present")
        self.assertEqual(config.status, Status.CRITICAL)


class TestNoSecretsOnRealFiles(FixtureProbeTestCase):
    """The no-leak property, verified against real file content on disk."""

    SECRETS = ("8846f7eaee8fb117ad06bdd830b7586c", "pssid-probe@example.edu",
               "password=", "network={")

    def test_json_report_leaks_nothing(self):
        report = self.report_for()
        blob = report.to_json()
        for secret in self.SECRETS:
            self.assertNotIn(secret, blob, f"leaked {secret!r}")

    def test_text_report_leaks_nothing(self):
        report = self.report_for()
        text = report.to_text()
        for secret in self.SECRETS:
            self.assertNotIn(secret, text, f"leaked {secret!r}")

    def test_leaks_nothing_even_when_reporting_a_problem(self):
        """The failure path formats more strings, so it gets its own check."""
        report = self.report_for(declared=("eduroam", "MWireless"), delivered=("eduroam",))
        blob = report.to_json() + report.to_text()
        for secret in self.SECRETS:
            self.assertNotIn(secret, blob, f"leaked {secret!r} on the failure path")


if __name__ == "__main__":
    unittest.main()
