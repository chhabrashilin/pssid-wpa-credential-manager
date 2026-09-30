"""
The daemon's contract with the credential manager and the pSSID layer tools.

This is the suite that matters most to *this* repository. The credential manager
renders a ``wpa_supplicant`` config and delivers it to a probe; the daemon reads
it. Nothing but convention connects the two, and these tests turn that
convention into an executable assertion: if the daemon ever changes the filename
it opens, ``scripts/pssid-credmgr-pull.sh`` and
``ansible/probe-pull-example.yml`` are wrong and this suite says so.

The layer tools (``pssid-80211``, ``pssid-dhcp``) live in
``ansible-role-pssid-VT-tools`` and are not installed here, so every assertion is
made against the shell command STRING the daemon builds, captured by patching
``subprocess.run``.
"""

from __future__ import annotations

import os
import tempfile
from unittest import mock

from harness import DaemonTestCase, fixtures


class TestWpaSupplicantFileContract(DaemonTestCase):
    """
    The exact path the credential manager must write to.

    Daemon line 482::

        wpa_supplicant_conf_file = f"/etc/wpa_supplicant/wpa_supplicant_{ssid_profile}.conf"

    One file per SSID profile, named after the profile. This is the contract
    encoded in ``docs/integration.md`` and implemented by
    ``scripts/pssid-credmgr-pull.sh``.
    """

    #: Kept in sync with scripts/pssid-credmgr-pull.sh DEST.
    EXPECTED = "/etc/wpa_supplicant/wpa_supplicant_%s.conf"

    def test_missing_conf_file_is_a_silent_skip(self):
        """
        **The failure mode this whole ecosystem is blind to.**

        Daemon lines 483-486: if the file is absent the function ``return``s.
        No exception, no retry, no layer-2 attempt, and -- critically -- no
        signal anywhere off the probe. The batch simply does not run.

        An operator sees a probe that is up, a daemon that is running, and no
        results. That is what ``projects/pssid-probe-health`` exists to surface.
        """
        batch = fixtures.batch(test_interface="wlan0")

        with self.fake_subprocess() as run:
            with mock.patch.object(self.daemon.os.path, "exists", return_value=False):
                result = self.daemon.process_on_layer_2(batch, "eduroam")

        self.assertIsNone(result)
        # Nothing was executed: no wpa_supplicant, no layer 3, nothing.
        self.assertEqual(run.call_count, 0)
        self.assertSyslogContains(
            "wpa_supplicant conf file /etc/wpa_supplicant/wpa_supplicant_eduroam.conf does not exist"
        )

    def test_layer2_command_uses_the_contracted_path(self):
        batch = fixtures.batch(test_interface="wlan0")

        with self.fake_subprocess() as run:
            with mock.patch.object(self.daemon.os.path, "exists", return_value=True):
                with mock.patch.object(self.daemon, "process_on_layer_3"):
                    self.daemon.process_on_layer_2(batch, "eduroam")

        commands = self.commands_from(run)
        self.assertTrue(commands, "expected the daemon to shell out")
        expected_path = self.EXPECTED % "eduroam"
        self.assertIn(expected_path, commands[0])
        self.assertIn("pssid-80211", commands[0])
        self.assertIn("-i wlan0", commands[0])

    def test_layer2_runs_inside_the_probe_namespace(self):
        batch = fixtures.batch(test_interface="wlan0")

        with self.fake_subprocess() as run:
            with mock.patch.object(self.daemon.os.path, "exists", return_value=True):
                with mock.patch.object(self.daemon, "process_on_layer_3"):
                    self.daemon.process_on_layer_2(batch, "eduroam")

        self.assertIn("ip netns exec pssid_wlan0", self.commands_from(run)[0])

    def test_teardown_uses_the_same_file_with_dash_d(self):
        batch = fixtures.batch(test_interface="wlan0")

        with self.fake_subprocess() as run:
            with mock.patch.object(self.daemon.os.path, "exists", return_value=True):
                with mock.patch.object(self.daemon, "process_on_layer_3"):
                    self.daemon.process_on_layer_2(batch, "eduroam")

        commands = self.commands_from(run)
        teardown = [c for c in commands if c.rstrip().endswith("-d")]
        self.assertEqual(len(teardown), 1, f"expected exactly one teardown in {commands}")
        self.assertIn(self.EXPECTED % "eduroam", teardown[0])

    def test_the_service_is_never_restarted(self):
        """
        Probes keep the ``wpa_supplicant`` SERVICE disabled -- the daemon drives
        ``pssid-80211`` directly per batch. The pull tooling therefore must not
        restart anything after installing a render, and the daemon must not
        either. Asserted so a future "helpful" change is caught.
        """
        batch = fixtures.batch(test_interface="wlan0")

        with self.fake_subprocess() as run:
            with mock.patch.object(self.daemon.os.path, "exists", return_value=True):
                with mock.patch.object(self.daemon, "process_on_layer_3"):
                    self.daemon.process_on_layer_2(batch, "eduroam")

        joined = " ".join(self.commands_from(run))
        for forbidden in ("systemctl", "service ", "wpa_cli", "reboot"):
            self.assertNotIn(forbidden, joined)

    def test_profile_name_decides_the_filename_for_every_profile_in_the_batch(self):
        """
        ``execute_batch`` (daemon line 631) loops over the batch's profiles, so a
        two-profile batch needs two delivered files. This is why the credential
        manager's convention is one bundle per profile.
        """
        batch = fixtures.batch(ssid_profiles=["eduroam", "MWireless"])
        seen = []

        with self.fake_subprocess():
            with mock.patch.object(self.daemon.os.path, "exists", return_value=True):
                with mock.patch.object(self.daemon, "setup_netns"):
                    with mock.patch.object(
                        self.daemon,
                        "process_on_layer_2",
                        side_effect=lambda b, s: seen.append(s),
                    ):
                        self.daemon.execute_batch(batch)

        self.assertEqual(seen, ["eduroam", "MWireless"])


class TestNamespaceSetup(DaemonTestCase):
    """``setup_netns`` -- the network namespace each batch runs inside."""

    def test_namespace_is_named_after_the_interface(self):
        batch = fixtures.batch(test_interface="wlan1")

        with self.fake_subprocess(returncode=0, stdout="wlan1") as run:
            with mock.patch.object(self.daemon.os.path, "exists", return_value=False):
                self.daemon.setup_netns(batch, "eduroam")

        self.assertIn("pssid_wlan1", " ".join(self.commands_from(run)))

    def test_existing_namespace_is_not_recreated(self):
        """``ip netns list | grep`` returning 0 means it exists."""
        batch = fixtures.batch(test_interface="wlan0")

        with self.fake_subprocess(returncode=0, stdout="wlan0") as run:
            with mock.patch.object(self.daemon.os.path, "exists", return_value=False):
                self.daemon.setup_netns(batch, "eduroam")

        self.assertNotIn("ip netns add", " ".join(self.commands_from(run)))

    def test_layer3_teardown_passes_the_profile(self):
        """
        ``pssid-dhcp`` is given ``-s <profile>``; the profile name reaches the
        DHCP tool as well as wpa_supplicant.
        """
        batch = fixtures.batch(test_interface="wlan0")

        with self.fake_subprocess(returncode=0, stdout="pids") as run:
            with mock.patch.object(self.daemon.os.path, "exists", return_value=False):
                self.daemon.setup_netns(batch, "eduroam")

        dhcp = [c for c in self.commands_from(run) if "pssid-dhcp" in c]
        self.assertTrue(dhcp)
        self.assertIn("-s eduroam", dhcp[0])


class TestShellInjectionSurface(DaemonTestCase):
    """
    **Security characterisation: profile names reach a root shell unescaped.**

    The daemon builds every command by f-string interpolation and runs it with
    ``shell=True`` (23 call sites). ``ssid_profile`` and ``test_interface`` come
    straight from ``pssid_config.json``, which is generated by the GUI and
    delivered over SSH -- so this is not remotely reachable today, and it is
    NOT being reported as an exploitable vulnerability.

    It is being pinned because it makes the GUI's input validation
    load-bearing for root safety on every probe, which is a property that should
    be deliberate and tested rather than incidental. ``pssid-gui2`` does validate
    (``isValidRfc1123Name``, ``isValidSsidName`` in
    ``ssid_profiles.controllers.ts``); the daemon trusts it completely.

    Fix, in order of value: pass argument LISTS with ``shell=False``; failing
    that, ``shlex.quote`` every interpolated value.
    """

    def test_profile_name_is_interpolated_into_the_shell_string_unescaped(self):
        batch = fixtures.batch(test_interface="wlan0")
        hostile = "eduroam; touch /tmp/pwned"

        with self.fake_subprocess() as run:
            with mock.patch.object(self.daemon.os.path, "exists", return_value=True):
                with mock.patch.object(self.daemon, "process_on_layer_3"):
                    self.daemon.process_on_layer_2(batch, hostile)

        command = self.commands_from(run)[0]
        self.assertIn("; touch /tmp/pwned", command)
        # And it really is handed to a shell.
        self.assertTrue(run.call_args_list[0].kwargs.get("shell"))

    def test_interface_name_is_also_interpolated(self):
        batch = fixtures.batch(test_interface="wlan0; id")

        with self.fake_subprocess() as run:
            with mock.patch.object(self.daemon.os.path, "exists", return_value=True):
                with mock.patch.object(self.daemon, "process_on_layer_3"):
                    self.daemon.process_on_layer_2(batch, "eduroam")

        self.assertIn("; id", self.commands_from(run)[0])

    def test_every_subprocess_call_uses_shell_true(self):
        """If a future change introduces a list form, this test should be updated."""
        source = self.daemon.__file__
        with open(source, "r", encoding="utf-8") as fh:
            text = fh.read()
        self.assertEqual(text.count("subprocess.run"), text.count("shell=True"))


class TestRealConfigFileLoads(DaemonTestCase):
    """The checked-in ``pssid_config.json`` must remain loadable and processable."""

    def test_load_json_reads_the_shipped_config(self):
        from harness import loader

        config_path = loader.daemon_dir() / "pssid_config.json"
        if not config_path.is_file():
            self.skipTest("pssid_config.json not present in the daemon checkout")

        data = self.daemon.load_json(str(config_path))
        for key in (
            "hosts",
            "host_groups",
            "schedules",
            "ssid_profiles",
            "tests",
            "jobs",
            "batches",
        ):
            self.assertIn(key, data, f"shipped config lost its '{key}' section")

    def test_load_json_exits_1_on_a_missing_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = os.path.join(tmp, "nope.json")
            with self.assertRaises(SystemExit) as ctx:
                self.daemon.load_json(missing)
            self.assertEqual(ctx.exception.code, 1)
