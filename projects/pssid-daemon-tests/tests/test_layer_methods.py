"""
Which layer 2 / layer 3 helper the daemon runs for an SSID profile.

``pssid-gui2`` writes the chosen methods onto every SSID profile as
``layer2_script`` / ``layer3_script`` -- the name of a file in its
``plugins/layer2/`` or ``plugins/layer3/`` directory. The daemon maps that name
to ``<HELPER_DIR>/layer2/<name>`` or ``<HELPER_DIR>/layer3/<name>`` and to
nothing else, so what is installed in those directories is the allow-list.

These tests install real files in a temporary ``HELPER_DIR`` rather than
mocking the filesystem, because the checks under test (is it a file, is it
executable, is it world-writable) are the point.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from unittest import mock

from harness import DaemonTestCase, fixtures, stubs


class HelperDirTestCase(DaemonTestCase):
    """Points the daemon's ``HELPER_DIR`` at an empty temporary directory."""

    def setUp(self) -> None:
        super().setUp()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.helper_dir = tmp.name
        patcher = mock.patch.object(self.daemon, "HELPER_DIR", self.helper_dir)
        patcher.start()
        self.addCleanup(patcher.stop)

    def install(self, relative_path: str, mode: int = 0o555) -> str:
        """
        Create a helper at ``HELPER_DIR/relative_path``.

        The default 0o555 is executable and not world-writable on Linux, and
        read-only (so also not world-writable) on Windows.
        """
        path = os.path.join(self.helper_dir, *relative_path.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("#!/bin/sh\n")
        os.chmod(path, mode)
        return path

    def install_starters(self) -> dict:
        """The GUI's starter methods, as the probe should have them."""
        return {
            "layer2": self.install("layer2/wpa_supplicant"),
            "layer3": self.install("layer3/dhcp_client"),
        }


class TestMethodResolution(HelperDirTestCase):

    def test_method_names_map_to_the_layer_subdirectories(self):
        expected = self.install_starters()
        cfg = fixtures.minimal_config()

        self.assertEqual(self.daemon.get_layer_helpers(cfg, "MWireless"), expected)

    def test_profiles_in_one_batch_use_their_own_methods(self):
        self.install_starters()
        eap = self.install("layer2/wpa_supplicant_eap")
        static = self.install("layer3/static_ip")
        cfg = fixtures.config_with(
            ssid_profiles=[
                fixtures.ssid_profile("MWireless"),
                fixtures.ssid_profile("eduroam", layer2_script="wpa_supplicant_eap", layer3_script="static_ip"),
            ],
            batches=[fixtures.batch(ssid_profiles=["MWireless", "eduroam"])],
        )
        used = {}

        with mock.patch.object(self.daemon, "setup_netns"):
            with mock.patch.object(
                self.daemon,
                "process_on_layer_2",
                side_effect=lambda b, s, h: used.__setitem__(s, h),
            ):
                self.daemon.execute_batch(cfg["batches"][0], cfg)

        self.assertEqual(used["MWireless"]["layer2"], os.path.join(self.helper_dir, "layer2", "wpa_supplicant"))
        self.assertEqual(used["eduroam"], {"layer2": eap, "layer3": static})

    def test_names_that_are_not_plain_file_names_are_rejected(self):
        # Real executables exist outside layer2/, so rejection is by name, not
        # by the target happening to be missing.
        self.install("pssid-80211")
        self.install("layer2/.hidden")
        for name in ("../pssid-80211", "/bin/sh", "..", ".", ".hidden", "a/b", "x;id", "x y"):
            with self.subTest(name=name):
                stubs.reset()
                self.assertIsNone(self.daemon.resolve_layer_helper("layer2", name))
                self.assertIn(f"Invalid layer2 method name '{name}'", stubs.syslog_errors())

    def test_missing_helper_is_refused(self):
        cfg = fixtures.minimal_config()

        self.assertIsNone(self.daemon.get_layer_helpers(cfg, "MWireless"))
        self.assertSyslogContains("wpa_supplicant does not exist or is not executable")

    def test_one_missing_layer_refuses_the_profile(self):
        self.install("layer2/wpa_supplicant")
        cfg = fixtures.minimal_config()

        self.assertIsNone(self.daemon.get_layer_helpers(cfg, "MWireless"))
        self.assertSyslogContains("dhcp_client does not exist or is not executable")

    def test_directory_named_like_a_method_is_refused(self):
        os.makedirs(os.path.join(self.helper_dir, "layer2", "wpa_supplicant"))

        self.assertIsNone(self.daemon.resolve_layer_helper("layer2", "wpa_supplicant"))

    @unittest.skipIf(os.name == "nt", "Windows has no execute permission bit")
    def test_non_executable_helper_is_refused(self):
        self.install("layer2/wpa_supplicant", mode=0o444)

        self.assertIsNone(self.daemon.resolve_layer_helper("layer2", "wpa_supplicant"))
        self.assertSyslogContains("does not exist or is not executable")

    def test_world_writable_helper_is_refused(self):
        self.install("layer2/wpa_supplicant", mode=0o757)

        self.assertIsNone(self.daemon.resolve_layer_helper("layer2", "wpa_supplicant"))
        self.assertSyslogContains("Refusing to run world-writable layer2 helper")

    def test_unknown_profile_is_refused(self):
        self.install_starters()
        cfg = fixtures.minimal_config()

        self.assertIsNone(self.daemon.get_layer_helpers(cfg, "NoSuchProfile"))
        self.assertSyslogContains("SSID profile 'NoSuchProfile' not found.")


class TestLegacyConfig(HelperDirTestCase):
    """
    Configs written before the GUI emitted methods have no ``layer2_script`` /
    ``layer3_script``. They keep running on the original tools.
    """

    def test_profile_without_methods_uses_the_original_tools(self):
        l2 = self.install("pssid-80211")
        l3 = self.install("pssid-dhcp")
        profile = fixtures.ssid_profile()
        del profile["layer2_script"], profile["layer3_script"]
        cfg = fixtures.config_with(ssid_profiles=[profile])

        self.assertEqual(self.daemon.get_layer_helpers(cfg, "MWireless"), {"layer2": l2, "layer3": l3})
        self.assertSyslogContains("No layer2 method in SSID profile, using legacy helper")

    def test_shipped_sample_config_names_the_starter_methods(self):
        from harness import loader

        config_path = loader.daemon_dir() / "pssid_config.json"
        if not config_path.is_file():
            self.skipTest("pssid_config.json not present in the daemon checkout")
        for profile in self.daemon.load_json(str(config_path))["ssid_profiles"]:
            self.assertEqual(profile.get("layer2_script"), "wpa_supplicant")
            self.assertEqual(profile.get("layer3_script"), "dhcp_client")


class TestExecuteBatchSkipsUnusableProfiles(HelperDirTestCase):

    def test_profile_without_helpers_is_skipped_and_others_still_run(self):
        self.install_starters()
        cfg = fixtures.config_with(
            ssid_profiles=[
                fixtures.ssid_profile("MWireless"),
                fixtures.ssid_profile("eduroam", layer2_script="not_installed"),
            ],
            batches=[fixtures.batch(ssid_profiles=["eduroam", "MWireless"])],
        )
        ran = []

        with self.fake_subprocess() as run:
            with mock.patch.object(self.daemon, "setup_netns", side_effect=lambda b, s, h: ran.append(("netns", s))):
                with mock.patch.object(self.daemon, "process_on_layer_2", side_effect=lambda b, s, h: ran.append(("l2", s))):
                    self.daemon.execute_batch(cfg["batches"][0], cfg)

        self.assertEqual(ran, [("netns", "MWireless"), ("l2", "MWireless")])
        self.assertEqual(run.call_count, 0)
        self.assertSyslogContains("Skipping SSID profile 'eduroam' in batch 'batch_A'")


class TestHelperFailsToStart(DaemonTestCase):
    """
    With an argument list, a program that cannot be started raises ``OSError``
    instead of returning exit 127 from a shell. It is logged like any other
    helper failure rather than killing the daemon's scheduler loop.
    """

    HELPERS = {"layer2": "/gone/layer2/x", "layer3": "/gone/layer3/y"}

    def test_layer2_start_failure_is_logged_not_raised(self):
        batch = fixtures.batch(test_interface="wlan0")

        with mock.patch.object(self.daemon.subprocess, "run", side_effect=FileNotFoundError("gone")):
            with mock.patch.object(self.daemon.os.path, "exists", return_value=True):
                self.assertIsNone(self.daemon.process_on_layer_2(batch, "MWireless", self.HELPERS))

        self.assertSyslogContains("Error in building layer 2")

    def test_namespace_cleanup_start_failure_is_logged_not_raised(self):
        batch = fixtures.batch(test_interface="wlan0")
        pids = mock.Mock(returncode=0, stdout="1234")

        def run(command, **kwargs):
            if isinstance(command, list):
                raise PermissionError("not executable")
            return pids

        with mock.patch.object(self.daemon.subprocess, "run", side_effect=run):
            with mock.patch.object(self.daemon.os.path, "exists", return_value=False):
                self.daemon.setup_netns(batch, "MWireless", self.HELPERS)

        # layer 3 is torn down first, and its failure ends the cleanup
        self.assertSyslogContains("failure of tearing down layer 3")


class TestStartupCheck(HelperDirTestCase):

    def write_config(self, cfg: dict) -> str:
        path = os.path.join(self.helper_dir, "pssid_config.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(cfg, fh)
        return path

    def run_validate(self, cfg: dict) -> int:
        argv = ["pssid-daemon.py", "--validate", "--hostname", "probe-1", "--config", self.write_config(cfg)]
        with self.in_daemon_dir():
            with mock.patch.object(sys, "argv", argv):
                with self.assertRaises(SystemExit) as ctx:
                    self.daemon.main()
        return ctx.exception.code

    def test_check_layer_helpers(self):
        cfg = fixtures.minimal_config()
        self.assertFalse(self.daemon.check_layer_helpers(cfg, {"batch_A"}))
        self.assertSyslogContains("Batch 'batch_A': no usable layer 2 / layer 3 helpers for SSID profile 'MWireless'")

        self.install_starters()
        self.assertTrue(self.daemon.check_layer_helpers(cfg, {"batch_A"}))

    def test_validate_exits_1_when_a_helper_is_missing(self):
        self.assertEqual(self.run_validate(fixtures.minimal_config()), 1)
        self.assertSyslogContains("helpers that are not usable on this host")

    def test_validate_exits_0_when_helpers_are_installed(self):
        self.install_starters()
        self.assertEqual(self.run_validate(fixtures.minimal_config()), 0)
        self.assertSyslogContains("The config file is validated.")
