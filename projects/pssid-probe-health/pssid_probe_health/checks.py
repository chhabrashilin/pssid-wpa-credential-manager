"""
The individual health checks.

Every check takes an :class:`Environment` rather than touching the filesystem or
the process table directly. That is what makes them testable without a probe --
and this whole project exists because the daemon is *not* written that way.
"""

from __future__ import annotations

import datetime
import json
import os
import re
import stat
from typing import Any, Callable, Iterable

from .model import CheckResult, Status

# Paths fixed by the daemon and by ansible-role-pssid-daemon.
DEFAULT_CONFIG_PATH = "/etc/pssid/pssid_config.json"
WPA_DIR = "/etc/wpa_supplicant"
WPA_CONF_TEMPLATE = "/etc/wpa_supplicant/wpa_supplicant_{profile}.conf"


class Environment:
    """
    Everything a check is allowed to touch, in one injectable object.

    The real implementation reads the real filesystem. Tests pass a fake.
    """

    def __init__(
        self,
        hostname: str,
        config_path: str = DEFAULT_CONFIG_PATH,
        now: datetime.datetime | None = None,
        root: str = "",
        warn_days: int = 30,
    ):
        self.hostname = hostname
        self.config_path = config_path
        self._now = now
        #: Age at which pssid_config.json is considered suspiciously stale.
        self.warn_days = warn_days
        # Prefix applied to every absolute path. Lets the tool run against a
        # fixture tree instead of a real probe, which is how the demo and the
        # integration test exercise it without root or hardware.
        self.root = root.rstrip("/")

    def resolve(self, path: str) -> str:
        """Apply the root prefix. Identity when no root is set."""
        if not self.root:
            return path
        return self.root + path if path.startswith("/") else os.path.join(self.root, path)

    # -- overridable primitives --------------------------------------------

    def now(self) -> datetime.datetime:
        return self._now or datetime.datetime.now(datetime.timezone.utc)

    def exists(self, path: str) -> bool:
        return os.path.exists(self.resolve(path))

    def read_text(self, path: str) -> str:
        with open(self.resolve(path), "r", encoding="utf-8") as fh:
            return fh.read()

    def stat(self, path: str) -> os.stat_result:
        return os.stat(self.resolve(path))

    def listdir(self, path: str) -> list[str]:
        return sorted(os.listdir(self.resolve(path)))

    def processes(self) -> list[str]:
        """
        Command lines of running processes. Empty when unavailable.

        Honours the root prefix, so a fixture tree can supply its own /proc and
        the process check is exercised the same way as every other check rather
        than being the one thing that cannot be simulated.
        """
        out: list[str] = []
        proc = self.resolve("/proc")
        if not os.path.isdir(proc):
            return out
        for entry in os.listdir(proc):
            if not entry.isdigit():
                continue
            try:
                with open(f"{proc}/{entry}/cmdline", "rb") as fh:
                    out.append(fh.read().replace(b"\x00", b" ").decode("utf-8", "replace").strip())
            except OSError:
                continue
        return out


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


def check_config_present(env: Environment) -> CheckResult:
    """The daemon exits 1 without this file (daemon lines 33-36)."""
    path = env.config_path
    if not env.exists(path):
        return CheckResult(
            name="config.present",
            status=Status.CRITICAL,
            summary=f"{path} is missing",
            evidence={"path": path},
            remedy="Deliver it: sudo scripts/provision-probes.sh --limit <this probe>",
        )

    try:
        raw = env.read_text(path)
    except OSError as exc:
        return CheckResult(
            name="config.present",
            status=Status.UNKNOWN,
            summary=f"{path} exists but could not be read: {exc.strerror}",
            evidence={"path": path},
            remedy="Check permissions; the daemon runs as root.",
        )

    try:
        json.loads(raw)
    except json.JSONDecodeError as exc:
        return CheckResult(
            name="config.present",
            status=Status.CRITICAL,
            summary=f"{path} is not valid JSON (line {exc.lineno})",
            evidence={"path": path, "error": exc.msg, "line": exc.lineno},
            remedy="Regenerate from the GUI; do not hand-edit.",
        )

    return CheckResult(
        name="config.present",
        status=Status.OK,
        summary=f"{path} present and parses",
        evidence={"path": path, "bytes": len(raw)},
    )


def load_config(env: Environment) -> dict[str, Any] | None:
    try:
        return json.loads(env.read_text(env.config_path))
    except (OSError, json.JSONDecodeError):
        return None


def check_config_age(env: Environment) -> CheckResult:
    """
    A config far older than the GUI's is a sign provisioning silently stopped.
    This can only observe the local mtime -- it cannot know what the GUI holds.
    """
    warn_days = env.warn_days
    path = env.config_path
    if not env.exists(path):
        return CheckResult(
            name="config.age",
            status=Status.UNKNOWN,
            summary="no config to age",
            evidence={"path": path},
        )
    try:
        mtime = datetime.datetime.fromtimestamp(
            env.stat(path).st_mtime, datetime.timezone.utc
        )
    except OSError as exc:
        return CheckResult(
            name="config.age",
            status=Status.UNKNOWN,
            summary=f"could not stat {path}: {exc.strerror}",
        )

    age_days = (env.now() - mtime).days
    status = Status.WARN if age_days > warn_days else Status.OK
    return CheckResult(
        name="config.age",
        status=status,
        summary=f"config last changed {age_days}d ago",
        evidence={"mtime": mtime.replace(microsecond=0).isoformat(), "age_days": age_days},
        remedy=(
            f"Older than {warn_days}d. Confirm provisioning still reaches this probe."
            if status is Status.WARN
            else ""
        ),
    )


# ---------------------------------------------------------------------------
# Host identity -- mirrors the daemon's own matching
# ---------------------------------------------------------------------------


def find_matching_regex(regexes: Iterable[str], hostname: str) -> bool:
    """
    Reimplementation of the daemon's ``find_matching_regex`` (daemon lines
    52-59), including its use of ``re.match`` -- a PREFIX match, not a full
    match. Kept identical on purpose: this check is only meaningful if it agrees
    with the daemon exactly.
    """
    for regex in regexes:
        try:
            if re.match(regex, hostname) is not None:
                return True
        except re.error:
            continue
    return False


def resolve_batches(config: dict[str, Any], hostname: str) -> tuple[set[str], bool]:
    """
    Which batches this probe should run, and whether the host was found at all.

    Mirrors ``process_gui_conf`` (daemon lines 289-311): the host's own batches,
    plus every group the host belongs to by name or by regex.
    """
    matched = False
    batches: set[str] = set()

    for host in config.get("hosts", []):
        if host.get("name") == hostname:
            matched = True
            batches.update(host.get("batches", []))

    if not matched:
        return set(), False

    for group in config.get("host_groups", []):
        in_group = hostname in group.get("hosts", []) or find_matching_regex(
            group.get("hosts_regex", []), hostname
        )
        if in_group:
            batches.update(group.get("batches", []))

    return batches, True


def resolve_expected_profiles(config: dict[str, Any], hostname: str) -> set[str]:
    """Every SSID profile named by a batch this probe is supposed to run."""
    batch_names, matched = resolve_batches(config, hostname)
    if not matched:
        return set()

    by_name = {b.get("name"): b for b in config.get("batches", [])}
    profiles: set[str] = set()
    for name in batch_names:
        batch = by_name.get(name)
        if batch:
            profiles.update(batch.get("ssid_profiles", []))
    return profiles


def check_host_known(env: Environment, config: dict[str, Any] | None) -> CheckResult:
    """
    The daemon ``sys.exit(1)``s on an unrecognised hostname (daemon lines
    299-302), so this is fatal rather than cosmetic.
    """
    if config is None:
        return CheckResult(
            name="host.known",
            status=Status.UNKNOWN,
            summary="config unavailable",
        )

    batches, matched = resolve_batches(config, env.hostname)
    if not matched:
        known = [h.get("name") for h in config.get("hosts", [])]
        return CheckResult(
            name="host.known",
            status=Status.CRITICAL,
            summary=f"hostname {env.hostname!r} is not in the config",
            evidence={"hostname": env.hostname, "known_hosts": known[:10]},
            remedy=(
                "The daemon exits 1 on startup. Add this host in the GUI, or "
                "correct the probe's hostname to match."
            ),
        )

    if not batches:
        return CheckResult(
            name="host.known",
            status=Status.WARN,
            summary=f"{env.hostname} is known but has no batches",
            evidence={"hostname": env.hostname},
            remedy=(
                "This probe will start and test nothing. Assign a batch, or a "
                "host group that carries one."
            ),
        )

    return CheckResult(
        name="host.known",
        status=Status.OK,
        summary=f"{env.hostname} runs {len(batches)} batch(es)",
        evidence={"hostname": env.hostname, "batches": sorted(batches)},
    )


# ---------------------------------------------------------------------------
# The silent skip
# ---------------------------------------------------------------------------


def check_wpa_configs(env: Environment, config: dict[str, Any] | None) -> CheckResult:
    """
    **The check this project exists for.**

    ``pssid-daemon.py`` lines 483-486: if
    ``/etc/wpa_supplicant/wpa_supplicant_<profile>.conf`` is absent, the batch
    ``return``s. No exception, no retry, no signal off the probe. The daemon
    keeps running, the probe stays up, and it tests nothing -- forever.

    Nothing else in the pSSID system detects this. The GUI validates that a
    batch references a defined SSID profile but has no idea whether the probe
    holds the credential file; ``provision-probes.sh`` explicitly reports
    delivery only.

    Reports existence, mode and size. Never content: these files hold a
    network-equivalent secret.
    """
    if config is None:
        return CheckResult(
            name="wpa.configs",
            status=Status.UNKNOWN,
            summary="config unavailable, cannot tell which profiles are needed",
        )

    expected = resolve_expected_profiles(config, env.hostname)
    if not expected:
        return CheckResult(
            name="wpa.configs",
            status=Status.UNKNOWN,
            summary="no SSID profiles resolved for this host",
            remedy="Check host.known -- this probe may not be assigned any batch.",
        )

    present: dict[str, Any] = {}
    missing: list[str] = []
    insecure: list[str] = []

    for profile in sorted(expected):
        path = WPA_CONF_TEMPLATE.format(profile=profile)
        if not env.exists(path):
            missing.append(profile)
            continue
        entry: dict[str, Any] = {"path": path}
        try:
            st = env.stat(path)
            entry["bytes"] = st.st_size
            entry["mode"] = oct(stat.S_IMODE(st.st_mode))
            if st.st_size == 0:
                missing.append(profile)  # an empty file is not a config
                entry["empty"] = True
            # 0600 root is the documented placement.
            if stat.S_IMODE(st.st_mode) & 0o077:
                insecure.append(profile)
        except OSError as exc:
            entry["error"] = exc.strerror
        present[profile] = entry

    if missing:
        return CheckResult(
            name="wpa.configs",
            status=Status.CRITICAL,
            summary=(
                f"{len(missing)} of {len(expected)} SSID profile(s) have no "
                f"wpa_supplicant config: {', '.join(missing)}"
            ),
            evidence={
                "expected": sorted(expected),
                "missing": missing,
                "present": present,
            },
            remedy=(
                "Batches using these profiles are being SILENTLY SKIPPED. "
                "Deliver them: CREDMGR_TOKEN=... pssid-credmgr-pull.sh <base-url> "
                + missing[0]
            ),
        )

    if insecure:
        return CheckResult(
            name="wpa.configs",
            status=Status.WARN,
            summary=f"all {len(expected)} config(s) present, but {len(insecure)} are group/world readable",
            evidence={"expected": sorted(expected), "present": present, "insecure": insecure},
            remedy="These hold network-equivalent secrets: chmod 0600 and chown root.",
        )

    return CheckResult(
        name="wpa.configs",
        status=Status.OK,
        summary=f"all {len(expected)} SSID profile(s) have a config",
        evidence={"expected": sorted(expected), "present": present},
    )


# ---------------------------------------------------------------------------
# Daemon liveness
# ---------------------------------------------------------------------------


def check_daemon_running(env: Environment) -> CheckResult:
    """
    A probe with no daemon is indistinguishable from a healthy one at the
    network level, which is the entire problem.
    """
    procs = env.processes()
    if not procs:
        return CheckResult(
            name="daemon.running",
            status=Status.UNKNOWN,
            summary="cannot enumerate processes (no /proc?)",
            remedy="Run on the probe as root.",
        )

    matches = [p for p in procs if "pssid-daemon" in p or "pssid_daemon" in p]
    if not matches:
        return CheckResult(
            name="daemon.running",
            status=Status.CRITICAL,
            summary="pssid-daemon is not running",
            evidence={"processes_scanned": len(procs)},
            remedy="systemctl status pssid-daemon; journalctl -u pssid-daemon -n 50",
        )

    return CheckResult(
        name="daemon.running",
        status=Status.OK,
        summary="pssid-daemon is running",
        evidence={"command": matches[0][:200]},
    )


def check_interfaces(env: Environment, config: dict[str, Any] | None) -> CheckResult:
    """
    Every interface the probe's batches test on must exist.

    ``test_interface`` may still be an unresolved ``$placeholder`` when host
    metadata is missing; that is reported rather than treated as a device name.
    """
    if config is None:
        return CheckResult(
            name="interfaces",
            status=Status.UNKNOWN,
            summary="config unavailable",
        )

    batch_names, matched = resolve_batches(config, env.hostname)
    if not matched or not batch_names:
        return CheckResult(
            name="interfaces",
            status=Status.UNKNOWN,
            summary="no batches resolved for this host",
        )

    by_name = {b.get("name"): b for b in config.get("batches", [])}
    wanted = {
        by_name[n].get("test_interface")
        for n in batch_names
        if n in by_name and by_name[n].get("test_interface")
    }

    unresolved = sorted(i for i in wanted if isinstance(i, str) and i.startswith("$"))
    concrete = sorted(i for i in wanted if isinstance(i, str) and not i.startswith("$"))

    if unresolved:
        return CheckResult(
            name="interfaces",
            status=Status.WARN,
            summary=f"unresolved interface placeholder(s): {', '.join(unresolved)}",
            evidence={"unresolved": unresolved, "concrete": concrete},
            remedy=(
                "The batch uses a $variable with no matching host metadata. The "
                "daemon marks such a batch invalid and will not run it."
            ),
        )

    missing = [i for i in concrete if not env.exists(f"/sys/class/net/{i}")]
    if missing:
        return CheckResult(
            name="interfaces",
            status=Status.CRITICAL,
            summary=f"test interface(s) not present: {', '.join(missing)}",
            evidence={"expected": concrete, "missing": missing},
            remedy="Check the wireless adapter is attached and named as expected (ip link).",
        )

    return CheckResult(
        name="interfaces",
        status=Status.OK,
        summary=f"test interface(s) present: {', '.join(concrete) or 'none declared'}",
        evidence={"expected": concrete},
    )


def check_credmgr_sync(env: Environment, config: dict[str, Any] | None) -> CheckResult:
    """
    Whether the credential-manager pull has ever run for each expected profile.

    ``scripts/pssid-credmgr-pull.sh`` writes ``.credmgr.<bundle>.etag`` beside
    the config it installs. Its presence means a pull succeeded at least once;
    its absence means the file arrived by some other route (Ansible vault, hand
    copy), which is worth knowing during a migration.

    Advisory only -- a probe provisioned by other means is not unhealthy.
    """
    if config is None:
        return CheckResult(
            name="credmgr.sync", status=Status.UNKNOWN, summary="config unavailable"
        )

    expected = resolve_expected_profiles(config, env.hostname)
    if not expected:
        return CheckResult(
            name="credmgr.sync", status=Status.UNKNOWN, summary="no profiles resolved"
        )

    managed, unmanaged = [], []
    for profile in sorted(expected):
        etag = f"{WPA_DIR}/.credmgr.{profile}.etag"
        (managed if env.exists(etag) else unmanaged).append(profile)

    if not managed:
        return CheckResult(
            name="credmgr.sync",
            status=Status.OK,
            summary="no profiles are credential-manager managed",
            evidence={"unmanaged": unmanaged},
        )

    return CheckResult(
        name="credmgr.sync",
        status=Status.OK,
        summary=f"{len(managed)} of {len(expected)} profile(s) pulled from the credential manager",
        evidence={"managed": managed, "unmanaged": unmanaged},
    )


#: Registry used by the CLI. Checks needing the parsed config take it second.
ALL_CHECKS: list[tuple[str, Callable[..., CheckResult], bool]] = [
    ("config.present", check_config_present, False),
    ("config.age", check_config_age, False),
    ("host.known", check_host_known, True),
    ("wpa.configs", check_wpa_configs, True),
    ("daemon.running", check_daemon_running, False),
    ("interfaces", check_interfaces, True),
    ("credmgr.sync", check_credmgr_sync, True),
]
