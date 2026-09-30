"""
Config fixtures shaped exactly like a real ``pssid_config.json``.

The shape is taken from the checked-in ``pssid-daemon/pssid_config.json`` and
from what ``pssid-gui2``'s ``build_config_payload`` emits -- not invented. If
those two ever diverge from what is built here, a test in
``test_config_contract`` should be the thing that notices.

Top-level keys, in the order the daemon expects to find them::

    hosts, host_groups, archivers, schedules, ssid_profiles, tests, jobs, batches
"""

from __future__ import annotations

import copy
from typing import Any

# --- Building blocks -------------------------------------------------------


def host(name: str = "probe-1", batches: list[str] | None = None, **data: Any) -> dict:
    return {
        "name": name,
        "batches": list(batches or []),
        "data": dict(data),
    }


def host_group(
    name: str = "group-1",
    batches: list[str] | None = None,
    hosts: list[str] | None = None,
    hosts_regex: list[str] | None = None,
    **data: Any,
) -> dict:
    return {
        "name": name,
        "batches": list(batches or []),
        "hosts": list(hosts or []),
        "hosts_regex": list(hosts_regex or []),
        "data": dict(data),
    }


def schedule(name: str = "every_two_minutes", repeat: str = "*/2 * * * *") -> dict:
    return {"name": name, "repeat": repeat}


def ssid_profile(name: str = "MWireless", ssid: str | None = None, **extra: Any) -> dict:
    profile = {
        "name": name,
        "ssid": ssid if ssid is not None else name,
        "test_level": "SSID",
        "bssid_scan": "Disabled",
        "min_signal": -79,
    }
    profile.update(extra)
    return profile


def test_def(name: str = "http_google", type_: str = "http", **spec: Any) -> dict:
    return {"name": name, "type": type_, "spec": dict(spec) or {"url": "www.google.com"}}


def job(
    name: str = "job_A",
    tests: list[str] | None = None,
    parallel: str = "True",
    continue_if: str = "false",
) -> dict:
    # NOTE: `parallel` and `continue-if` are STRINGS on purpose. The daemon
    # string-compares parallel against "True"/"False" (daemon lines 262-265) and
    # calls .lower() on continue-if (line 223). Real booleans break both.
    return {
        "name": name,
        "parallel": parallel,
        "tests": list(tests or ["http_google"]),
        "continue-if": continue_if,
    }


def batch(
    name: str = "batch_A",
    priority: int = 1,
    test_interface: str = "wlan0",
    ssid_profiles: list[str] | None = None,
    schedules: list[str] | None = None,
    jobs: list[str] | None = None,
    archivers: list[str] | None = None,
) -> dict:
    return {
        "name": name,
        "priority": priority,
        "test_interface": test_interface,
        "ssid_profiles": list(ssid_profiles or ["MWireless"]),
        "schedules": list(schedules or ["every_two_minutes"]),
        "jobs": list(jobs or ["job_A"]),
        "archivers": list(archivers or ["syslog"]),
    }


def archiver(name: str = "syslog") -> dict:
    return {
        "name": name,
        "archiver": "syslog",
        "data": {"identity": "pssid", "facility": "1"},
    }


# --- Whole configs ---------------------------------------------------------


def minimal_config(hostname: str = "probe-1") -> dict:
    """
    The smallest config that the daemon will process end to end without error:
    one host, one batch, one job, one test, one schedule, one SSID profile.
    """
    return {
        "hosts": [host(hostname, batches=["batch_A"], interface="wlan0")],
        "host_groups": [],
        "archivers": [archiver()],
        "schedules": [schedule()],
        "ssid_profiles": [ssid_profile()],
        "tests": [test_def()],
        "jobs": [job()],
        "batches": [batch()],
    }


def config_with(**overrides: Any) -> dict:
    """``minimal_config`` with top-level keys replaced. Deep-copied."""
    cfg = copy.deepcopy(minimal_config())
    cfg.update(copy.deepcopy(overrides))
    return cfg


def multi_job_config() -> dict:
    """
    Two jobs, each with its own single test. Exercises the per-job boundary --
    which is where the daemon accumulates state across jobs (see
    ``test_defects.test_job_tests_accumulate_across_jobs``).
    """
    cfg = minimal_config()
    cfg["tests"] = [
        test_def("http_google", "http", url="www.google.com"),
        test_def("http_ebay", "http", url="www.ebay.com"),
    ]
    cfg["jobs"] = [
        job("job_one", tests=["http_google"]),
        job("job_two", tests=["http_ebay"]),
    ]
    cfg["batches"] = [batch(jobs=["job_one", "job_two"])]
    return cfg


def substitution_config() -> dict:
    """
    Mirrors the shipped ``pssid_config.json``, where ``test_interface`` is the
    literal string ``"$interface"`` resolved from the host's ``data`` block.
    """
    cfg = minimal_config()
    cfg["hosts"] = [host("probe-1", batches=["batch_A"], interface="wlan0")]
    cfg["batches"] = [batch(test_interface="$interface")]
    return cfg
