"""
Tests for the probe health checks.

Everything runs against a :class:`FakeEnvironment` -- an in-memory filesystem
and process table -- so the whole suite is hermetic and needs no probe, no root,
and no network.
"""

from __future__ import annotations

import datetime
import json
import os
import stat
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pssid_probe_health import checks  # noqa: E402
from pssid_probe_health.checks import Environment  # noqa: E402
from pssid_probe_health.cli import run_checks  # noqa: E402
from pssid_probe_health.model import CheckResult, HealthReport, Status  # noqa: E402


class FakeStat:
    def __init__(self, size: int = 100, mode: int = 0o600, mtime: float | None = None):
        self.st_size = size
        self.st_mode = stat.S_IFREG | mode
        self.st_mtime = mtime if mtime is not None else datetime.datetime(
            2026, 8, 1, tzinfo=datetime.timezone.utc
        ).timestamp()


class FakeEnvironment(Environment):
    """In-memory stand-in for a probe."""

    def __init__(
        self,
        hostname: str = "probe-1",
        files: dict[str, str] | None = None,
        stats: dict[str, FakeStat] | None = None,
        processes: list[str] | None = None,
        now: datetime.datetime | None = None,
        config_path: str = checks.DEFAULT_CONFIG_PATH,
    ):
        super().__init__(hostname=hostname, config_path=config_path, now=now)
        self.files = dict(files or {})
        self.stats = dict(stats or {})
        self._processes = list(processes if processes is not None else ["/usr/bin/python3 /usr/bin/pssid/pssid-daemon.py"])
        self.unreadable: set[str] = set()

    def exists(self, path: str) -> bool:
        return path in self.files

    def read_text(self, path: str) -> str:
        if path in self.unreadable:
            raise OSError(13, "Permission denied")
        if path not in self.files:
            raise FileNotFoundError(2, "No such file or directory", path)
        return self.files[path]

    def stat(self, path: str):
        if path in self.stats:
            return self.stats[path]
        if path in self.files:
            return FakeStat(size=len(self.files[path]))
        raise FileNotFoundError(2, "No such file or directory", path)

    def listdir(self, path: str) -> list[str]:
        prefix = path.rstrip("/") + "/"
        return sorted({f[len(prefix):].split("/")[0] for f in self.files if f.startswith(prefix)})

    def processes(self) -> list[str]:
        return list(self._processes)


# --- Config helpers --------------------------------------------------------


def make_config(hostname="probe-1", batches=("batch_A",), profiles=("eduroam",), interface="wlan0"):
    return {
        "hosts": [{"name": hostname, "batches": list(batches), "data": {"interface": interface}}],
        "host_groups": [],
        "schedules": [{"name": "s", "repeat": "*/2 * * * *"}],
        "ssid_profiles": [{"name": p, "ssid": p} for p in profiles],
        "tests": [{"name": "t", "type": "http", "spec": {"url": "x"}}],
        "jobs": [{"name": "j", "parallel": "True", "tests": ["t"], "continue-if": "false"}],
        "batches": [
            {
                "name": b,
                "priority": 1,
                "test_interface": interface,
                "ssid_profiles": list(profiles),
                "schedules": ["s"],
                "jobs": ["j"],
            }
            for b in batches
        ],
    }


def env_with_config(config, **kwargs):
    files = kwargs.pop("files", {})
    files = dict(files)
    files[checks.DEFAULT_CONFIG_PATH] = json.dumps(config)
    files.setdefault("/sys/class/net/wlan0", "")
    return FakeEnvironment(files=files, **kwargs)


def wpa_path(profile):
    return checks.WPA_CONF_TEMPLATE.format(profile=profile)


# ---------------------------------------------------------------------------


class TestStatusModel(unittest.TestCase):
    def test_severity_ordering(self):
        self.assertLess(Status.OK, Status.UNKNOWN)
        self.assertLess(Status.UNKNOWN, Status.WARN)
        self.assertLess(Status.WARN, Status.CRITICAL)

    def test_unknown_outranks_ok(self):
        """A check that could not run is not evidence of health."""
        self.assertEqual(max([Status.OK, Status.UNKNOWN]), Status.UNKNOWN)

    def test_report_status_is_the_worst_check(self):
        r = HealthReport(probe_id="p", generated_at=datetime.datetime.now())
        r.add(CheckResult("a", Status.OK, "fine"))
        r.add(CheckResult("b", Status.CRITICAL, "broken"))
        r.add(CheckResult("c", Status.WARN, "meh"))
        self.assertEqual(r.status, Status.CRITICAL)

    def test_empty_report_is_unknown_not_ok(self):
        r = HealthReport(probe_id="p", generated_at=datetime.datetime.now())
        self.assertEqual(r.status, Status.UNKNOWN)

    def test_is_testing_false_only_on_critical(self):
        r = HealthReport(probe_id="p", generated_at=datetime.datetime.now())
        r.add(CheckResult("a", Status.WARN, "meh"))
        self.assertTrue(r.is_testing)
        r.add(CheckResult("b", Status.CRITICAL, "broken"))
        self.assertFalse(r.is_testing)

    def test_exit_codes(self):
        for status, expected in [(Status.OK, 0), (Status.UNKNOWN, 0), (Status.WARN, 1), (Status.CRITICAL, 2)]:
            r = HealthReport(probe_id="p", generated_at=datetime.datetime.now())
            r.add(CheckResult("a", status, "x"))
            self.assertEqual(r.exit_code, expected, f"{status} should exit {expected}")


class TestConfigChecks(unittest.TestCase):
    def test_missing_config_is_critical(self):
        result = checks.check_config_present(FakeEnvironment(files={}))
        self.assertEqual(result.status, Status.CRITICAL)
        self.assertIn("missing", result.summary)
        self.assertTrue(result.remedy)

    def test_malformed_json_is_critical_and_names_the_line(self):
        env = FakeEnvironment(files={checks.DEFAULT_CONFIG_PATH: '{"hosts": [,]}'})
        result = checks.check_config_present(env)
        self.assertEqual(result.status, Status.CRITICAL)
        self.assertIn("line", result.evidence)

    def test_unreadable_config_is_unknown_not_critical(self):
        """Cannot-tell must not be reported as broken."""
        env = FakeEnvironment(files={checks.DEFAULT_CONFIG_PATH: "{}"})
        env.unreadable.add(checks.DEFAULT_CONFIG_PATH)
        result = checks.check_config_present(env)
        self.assertEqual(result.status, Status.UNKNOWN)

    def test_valid_config_is_ok(self):
        env = env_with_config(make_config())
        self.assertEqual(checks.check_config_present(env).status, Status.OK)

    def test_old_config_warns(self):
        old = datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)
        env = env_with_config(
            make_config(),
            now=datetime.datetime(2026, 8, 1, tzinfo=datetime.timezone.utc),
            stats={checks.DEFAULT_CONFIG_PATH: FakeStat(mtime=old.timestamp())},
        )
        result = checks.check_config_age(env)
        self.assertEqual(result.status, Status.WARN)
        self.assertGreater(result.evidence["age_days"], 200)

    def test_recent_config_is_ok(self):
        now = datetime.datetime(2026, 8, 1, tzinfo=datetime.timezone.utc)
        env = env_with_config(
            make_config(),
            now=now,
            stats={checks.DEFAULT_CONFIG_PATH: FakeStat(mtime=(now - datetime.timedelta(days=2)).timestamp())},
        )
        self.assertEqual(checks.check_config_age(env).status, Status.OK)


class TestHostResolution(unittest.TestCase):
    """Must agree with the daemon exactly, or every downstream check is wrong."""

    def test_host_batches_are_found(self):
        batches, matched = checks.resolve_batches(make_config(), "probe-1")
        self.assertTrue(matched)
        self.assertEqual(batches, {"batch_A"})

    def test_unknown_host_is_not_matched(self):
        batches, matched = checks.resolve_batches(make_config(), "other")
        self.assertFalse(matched)
        self.assertEqual(batches, set())

    def test_group_batches_are_added(self):
        cfg = make_config()
        cfg["host_groups"] = [
            {"name": "g", "batches": ["batch_G"], "hosts": ["probe-1"], "hosts_regex": [], "data": {}}
        ]
        batches, _ = checks.resolve_batches(cfg, "probe-1")
        self.assertEqual(batches, {"batch_A", "batch_G"})

    def test_group_regex_matches(self):
        cfg = make_config(hostname="probe-42")
        cfg["host_groups"] = [
            {"name": "g", "batches": ["batch_G"], "hosts": [], "hosts_regex": [".*-42$"], "data": {}}
        ]
        batches, _ = checks.resolve_batches(cfg, "probe-42")
        self.assertIn("batch_G", batches)

    def test_regex_is_a_prefix_match_like_the_daemon(self):
        """The daemon uses re.match, not fullmatch. We must match that."""
        self.assertTrue(checks.find_matching_regex(["probe"], "probe-1"))
        self.assertFalse(checks.find_matching_regex(["robe"], "probe-1"))

    def test_invalid_regex_is_skipped_not_raised(self):
        self.assertFalse(checks.find_matching_regex(["[unclosed"], "probe-1"))

    def test_unknown_host_is_critical(self):
        env = env_with_config(make_config(hostname="probe-1"), hostname="wrong-name")
        result = checks.check_host_known(env, make_config(hostname="probe-1"))
        self.assertEqual(result.status, Status.CRITICAL)
        self.assertIn("wrong-name", result.summary)

    def test_known_host_with_no_batches_warns(self):
        cfg = make_config(batches=())
        env = env_with_config(cfg)
        result = checks.check_host_known(env, cfg)
        self.assertEqual(result.status, Status.WARN)
        self.assertIn("no batches", result.summary)


class TestSilentSkipDetection(unittest.TestCase):
    """
    The headline feature: catch what pssid-daemon.py:483 does silently.
    """

    def test_missing_wpa_config_is_critical(self):
        cfg = make_config(profiles=("eduroam",))
        env = env_with_config(cfg)  # no wpa file at all
        result = checks.check_wpa_configs(env, cfg)

        self.assertEqual(result.status, Status.CRITICAL)
        self.assertIn("eduroam", result.summary)
        self.assertEqual(result.evidence["missing"], ["eduroam"])
        self.assertIn("SILENTLY SKIPPED", result.remedy)

    def test_present_wpa_config_is_ok(self):
        cfg = make_config(profiles=("eduroam",))
        env = env_with_config(cfg, files={wpa_path("eduroam"): "network={}\n"})
        result = checks.check_wpa_configs(env, cfg)
        self.assertEqual(result.status, Status.OK)

    def test_partial_coverage_names_only_the_missing_ones(self):
        cfg = make_config(profiles=("eduroam", "MWireless", "guest"))
        env = env_with_config(
            cfg,
            files={
                wpa_path("eduroam"): "network={}\n",
                wpa_path("guest"): "network={}\n",
            },
        )
        result = checks.check_wpa_configs(env, cfg)
        self.assertEqual(result.status, Status.CRITICAL)
        self.assertEqual(result.evidence["missing"], ["MWireless"])
        self.assertIn("1 of 3", result.summary)

    def test_empty_file_counts_as_missing(self):
        """
        ansible-playbook-pssid-daemon ships a ZERO-BYTE placeholder SSID profile.
        A file that exists but is empty is not a config, and wpa_supplicant will
        fail on it just as surely as on an absent one.
        """
        cfg = make_config(profiles=("eduroam",))
        env = env_with_config(cfg, files={wpa_path("eduroam"): ""})
        env.stats[wpa_path("eduroam")] = FakeStat(size=0)
        result = checks.check_wpa_configs(env, cfg)
        self.assertEqual(result.status, Status.CRITICAL)
        self.assertIn("eduroam", result.evidence["missing"])

    def test_world_readable_config_warns(self):
        cfg = make_config(profiles=("eduroam",))
        env = env_with_config(cfg, files={wpa_path("eduroam"): "network={}\n"})
        env.stats[wpa_path("eduroam")] = FakeStat(size=50, mode=0o644)
        result = checks.check_wpa_configs(env, cfg)
        self.assertEqual(result.status, Status.WARN)
        self.assertEqual(result.evidence["insecure"], ["eduroam"])

    def test_correct_mode_does_not_warn(self):
        cfg = make_config(profiles=("eduroam",))
        env = env_with_config(cfg, files={wpa_path("eduroam"): "network={}\n"})
        env.stats[wpa_path("eduroam")] = FakeStat(size=50, mode=0o600)
        self.assertEqual(checks.check_wpa_configs(env, cfg).status, Status.OK)

    def test_profiles_come_from_group_batches_too(self):
        cfg = make_config(profiles=("eduroam",))
        cfg["host_groups"] = [
            {"name": "g", "batches": ["batch_G"], "hosts": ["probe-1"], "hosts_regex": [], "data": {}}
        ]
        cfg["batches"].append(
            {
                "name": "batch_G",
                "priority": 1,
                "test_interface": "wlan0",
                "ssid_profiles": ["group-only-profile"],
                "schedules": ["s"],
                "jobs": ["j"],
            }
        )
        expected = checks.resolve_expected_profiles(cfg, "probe-1")
        self.assertEqual(expected, {"eduroam", "group-only-profile"})

    def test_no_config_is_unknown_not_ok(self):
        env = FakeEnvironment(files={})
        result = checks.check_wpa_configs(env, None)
        self.assertEqual(result.status, Status.UNKNOWN)


class TestNoSecretsLeak(unittest.TestCase):
    """
    A wpa_supplicant config holds a network-equivalent secret (a 64-hex PSK or
    an NT hash). The report must describe these files, never quote them.
    """

    SECRET_CONF = (
        'network={\n'
        '    ssid="eduroam"\n'
        '    psk=1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef\n'
        '    password=hash:8846f7eaee8fb117ad06bdd830b7586c\n'
        '    identity="probe@example.edu"\n'
        '}\n'
    )

    def test_report_never_contains_config_content(self):
        cfg = make_config(profiles=("eduroam",))
        env = env_with_config(cfg, files={wpa_path("eduroam"): self.SECRET_CONF})
        report = run_checks(env)
        blob = report.to_json()

        for secret in (
            "1234567890abcdef",
            "8846f7eaee8fb117ad06bdd830b7586c",
            "probe@example.edu",
            "psk=",
            "password=",
        ):
            self.assertNotIn(secret, blob, f"report leaked {secret!r}")

    def test_report_still_describes_the_file(self):
        cfg = make_config(profiles=("eduroam",))
        env = env_with_config(cfg, files={wpa_path("eduroam"): self.SECRET_CONF})
        result = checks.check_wpa_configs(env, cfg)
        entry = result.evidence["present"]["eduroam"]
        self.assertEqual(entry["path"], wpa_path("eduroam"))
        self.assertIn("bytes", entry)
        self.assertIn("mode", entry)

    def test_text_output_never_contains_secrets(self):
        cfg = make_config(profiles=("eduroam",))
        env = env_with_config(cfg, files={wpa_path("eduroam"): self.SECRET_CONF})
        text = run_checks(env).to_text()
        self.assertNotIn("1234567890abcdef", text)
        self.assertNotIn("8846f7ea", text)


class TestDaemonAndInterfaces(unittest.TestCase):
    def test_daemon_not_running_is_critical(self):
        env = FakeEnvironment(processes=["/sbin/init", "/usr/sbin/sshd"])
        result = checks.check_daemon_running(env)
        self.assertEqual(result.status, Status.CRITICAL)

    def test_daemon_running_is_ok(self):
        env = FakeEnvironment(processes=["python3 /usr/bin/pssid/pssid-daemon.py --config /etc/pssid/x.json"])
        self.assertEqual(checks.check_daemon_running(env).status, Status.OK)

    def test_no_process_table_is_unknown(self):
        env = FakeEnvironment(processes=[])
        self.assertEqual(checks.check_daemon_running(env).status, Status.UNKNOWN)

    def test_missing_interface_is_critical(self):
        cfg = make_config(interface="wlan9")
        env = env_with_config(cfg)  # only /sys/class/net/wlan0 exists
        result = checks.check_interfaces(env, cfg)
        self.assertEqual(result.status, Status.CRITICAL)
        self.assertEqual(result.evidence["missing"], ["wlan9"])

    def test_present_interface_is_ok(self):
        cfg = make_config(interface="wlan0")
        env = env_with_config(cfg)
        self.assertEqual(checks.check_interfaces(env, cfg).status, Status.OK)

    def test_unresolved_placeholder_warns(self):
        """
        A batch whose test_interface is still "$interface" means host metadata
        never resolved -- the daemon marks such a batch invalid and skips it.
        """
        cfg = make_config(interface="$interface")
        env = env_with_config(cfg)
        result = checks.check_interfaces(env, cfg)
        self.assertEqual(result.status, Status.WARN)
        self.assertEqual(result.evidence["unresolved"], ["$interface"])


class TestCredmgrSync(unittest.TestCase):
    def test_etag_marks_a_profile_as_managed(self):
        cfg = make_config(profiles=("eduroam",))
        env = env_with_config(
            cfg,
            files={
                wpa_path("eduroam"): "network={}\n",
                f"{checks.WPA_DIR}/.credmgr.eduroam.etag": '"abc123"',
            },
        )
        result = checks.check_credmgr_sync(env, cfg)
        self.assertEqual(result.status, Status.OK)
        self.assertEqual(result.evidence["managed"], ["eduroam"])

    def test_absent_etag_is_reported_but_not_a_failure(self):
        """A probe provisioned by Ansible instead is not unhealthy."""
        cfg = make_config(profiles=("eduroam",))
        env = env_with_config(cfg, files={wpa_path("eduroam"): "network={}\n"})
        result = checks.check_credmgr_sync(env, cfg)
        self.assertEqual(result.status, Status.OK)
        self.assertEqual(result.evidence["unmanaged"], ["eduroam"])


class TestFullReport(unittest.TestCase):
    def test_healthy_probe_reports_testing(self):
        cfg = make_config(profiles=("eduroam",))
        now = datetime.datetime(2026, 8, 1, tzinfo=datetime.timezone.utc)
        env = env_with_config(
            cfg,
            now=now,
            files={
                wpa_path("eduroam"): "network={}\n",
                "/sys/class/net/wlan0": "",
            },
            stats={
                checks.DEFAULT_CONFIG_PATH: FakeStat(mtime=(now - datetime.timedelta(days=1)).timestamp()),
                wpa_path("eduroam"): FakeStat(size=50, mode=0o600),
            },
        )
        report = run_checks(env)
        self.assertTrue(report.is_testing, report.to_text())
        self.assertEqual(report.exit_code, 0)

    def test_probe_missing_credentials_reports_not_testing(self):
        cfg = make_config(profiles=("eduroam",))
        env = env_with_config(cfg)
        report = run_checks(env)
        self.assertFalse(report.is_testing)
        self.assertEqual(report.exit_code, 2)
        names = [c.name for c in report.by_status(Status.CRITICAL)]
        self.assertIn("wpa.configs", names)

    def test_every_check_runs_even_if_one_raises(self):
        cfg = make_config()
        env = env_with_config(cfg)

        original = checks.check_daemon_running

        def exploding(_env):
            raise RuntimeError("boom")

        checks.ALL_CHECKS[4] = ("daemon.running", exploding, False)
        try:
            report = run_checks(env)
        finally:
            checks.ALL_CHECKS[4] = ("daemon.running", original, False)

        self.assertEqual(len(report.checks), len(checks.ALL_CHECKS))
        failed = [c for c in report.checks if c.name == "daemon.running"][0]
        self.assertEqual(failed.status, Status.UNKNOWN)
        self.assertIn("RuntimeError", failed.summary)

    def test_json_shape_is_stable(self):
        cfg = make_config()
        env = env_with_config(cfg)
        doc = json.loads(run_checks(env).to_json())

        for key in ("schema", "probe_id", "generated_at", "status", "is_testing", "checks"):
            self.assertIn(key, doc)
        self.assertEqual(doc["schema"], 1)
        self.assertIsInstance(doc["checks"], list)
        for check in doc["checks"]:
            self.assertIn("name", check)
            self.assertIn("status", check)
            self.assertIn("summary", check)

    def test_text_output_states_the_verdict_plainly(self):
        cfg = make_config(profiles=("eduroam",))
        env = env_with_config(cfg)
        text = run_checks(env).to_text()
        self.assertIn("NOT TESTING", text)
        self.assertIn("eduroam", text)


if __name__ == "__main__":
    unittest.main()
