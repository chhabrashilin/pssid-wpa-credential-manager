"""
The contract ``pssid_config.json`` must satisfy for the daemon to run it.

This is the suite's reason to exist: ``pssid-gui2`` GENERATES this config and
validates it in ``assertDaemonValid``
(``services/server/src/services/config.service.ts``), but that validator was
written by reading the daemon, and nothing keeps the two in sync. Every rule
asserted here is verified against the daemon's ACTUAL behaviour, so if the
daemon changes, this suite fails and the GUI's validator is known to need
updating.

Each test names the daemon line it derives from.
"""

from __future__ import annotations

from harness import DaemonTestCase, fixtures


class TestJobFlagsAreStrings(DaemonTestCase):
    """
    ``parallel`` and ``continue-if`` must be STRINGS, not JSON booleans.

    Daemon lines 262-265 compare ``job["parallel"] == "True"`` -- a string
    compare. Daemon line 223 calls ``job['continue-if'].lower()``. A real
    boolean silently fails the first and crashes the second.
    """

    def test_continue_if_boolean_raises_attribute_error(self):
        cfg = fixtures.minimal_config()
        cfg["jobs"][0]["continue-if"] = False  # a real bool, not "false"

        with self.in_daemon_dir():
            with self.assertRaises(AttributeError) as ctx:
                self.daemon.transform_job_list_for_batch_processing(
                    cfg["batches"][0], cfg, set(), "local0"
                )
        # Proves it is the .lower() call at daemon line 223.
        self.assertIn("lower", str(ctx.exception))

    def test_continue_if_string_is_lowercased(self):
        cfg = fixtures.minimal_config()
        cfg["jobs"][0]["continue-if"] = "TRUE"

        with self.in_daemon_dir():
            batch, valid = self.daemon.transform_job_list_for_batch_processing(
                cfg["batches"][0], cfg, set(), "local0"
            )
        self.assertTrue(valid)
        self.assertEqual(
            batch["batch_4_batchProcessor"][0]["continue-if"]["script"], "true"
        )

    def test_parallel_string_true_becomes_real_bool(self):
        """Daemon lines 260-265 convert the STRING back to a bool for pscheduler."""
        cfg = fixtures.minimal_config()
        cfg["jobs"][0]["parallel"] = "True"

        with self.in_daemon_dir():
            batch, valid = self.daemon.transform_job_list_for_batch_processing(
                cfg["batches"][0], cfg, set(), "local0"
            )
        self.assertTrue(valid)
        self.assertIs(batch["batch_4_batchProcessor"][0]["parallel"], True)

    def test_parallel_string_false_becomes_real_bool(self):
        cfg = fixtures.minimal_config()
        cfg["jobs"][0]["parallel"] = "False"

        with self.in_daemon_dir():
            batch, _ = self.daemon.transform_job_list_for_batch_processing(
                cfg["batches"][0], cfg, set(), "local0"
            )
        self.assertIs(batch["batch_4_batchProcessor"][0]["parallel"], False)

    def test_parallel_lowercase_is_NOT_converted(self):
        """
        Only the exact strings "True"/"False" convert. "true" survives as a
        string into the pscheduler payload -- a real trap for anyone hand-editing
        a config, and the reason the GUI must emit the capitalised form.
        """
        cfg = fixtures.minimal_config()
        cfg["jobs"][0]["parallel"] = "true"

        with self.in_daemon_dir():
            batch, _ = self.daemon.transform_job_list_for_batch_processing(
                cfg["batches"][0], cfg, set(), "local0"
            )
        parallel = batch["batch_4_batchProcessor"][0]["parallel"]
        self.assertEqual(parallel, "true")
        self.assertNotIsInstance(parallel, bool)


class TestReferencesMustResolve(DaemonTestCase):
    """Names referenced by a batch must exist, or the batch is rejected."""

    def test_missing_job_invalidates_batch(self):
        cfg = fixtures.minimal_config()
        cfg["batches"][0]["jobs"] = ["no_such_job"]

        with self.in_daemon_dir():
            _, valid = self.daemon.transform_job_list_for_batch_processing(
                cfg["batches"][0], cfg, set(), "local0"
            )
        self.assertFalse(valid)
        self.assertSyslogContains("Job 'no_such_job' not found")

    def test_missing_test_invalidates_batch(self):
        cfg = fixtures.minimal_config()
        cfg["jobs"][0]["tests"] = ["no_such_test"]

        with self.in_daemon_dir():
            _, valid = self.daemon.transform_job_list_for_batch_processing(
                cfg["batches"][0], cfg, set(), "local0"
            )
        self.assertFalse(valid)
        self.assertSyslogContains("Test 'no_such_test' not found")

    def test_empty_ssid_profiles_invalidates_batch(self):
        """
        Daemon lines 187-197: with no global ssid_profiles the batch is invalid.
        This is the GUI's "every batch must have a non-empty ssid_profiles" rule.
        """
        cfg = fixtures.minimal_config()
        cfg["ssid_profiles"] = []

        with self.in_daemon_dir():
            _, valid = self.daemon.transform_job_list_for_batch_processing(
                cfg["batches"][0], cfg, set(), "local0"
            )
        self.assertFalse(valid)
        self.assertSyslogContains("No SSID profiles found in configuration")


class TestHostIdentification(DaemonTestCase):
    """How the daemon decides which batches belong to this probe."""

    def test_unknown_host_exits_1(self):
        """Daemon lines 299-302: an unrecognised hostname is fatal."""
        cfg = fixtures.minimal_config(hostname="probe-1")
        with self.assertRaises(SystemExit) as ctx:
            self.daemon.process_gui_conf(
                cfg, None, set(), "not-this-probe", set(), "local0"
            )
        self.assertEqual(ctx.exception.code, 1)
        self.assertSyslogContains("No host with name 'not-this-probe' found")

    def test_host_batches_are_collected(self):
        identified = set()
        cfg = fixtures.minimal_config(hostname="probe-1")
        cfg["batches"] = []  # stop before scheduling; assert collection only
        self.daemon.process_gui_conf(cfg, None, set(), "probe-1", identified, "local0")
        self.assertEqual(identified, {"batch_A"})

    def test_group_membership_by_exact_host(self):
        cfg = fixtures.minimal_config(hostname="probe-1")
        cfg["hosts"][0]["batches"] = []
        cfg["host_groups"] = [
            fixtures.host_group("g1", batches=["batch_group"], hosts=["probe-1"])
        ]
        cfg["batches"] = []
        identified = set()
        self.daemon.process_gui_conf(cfg, None, set(), "probe-1", identified, "local0")
        self.assertEqual(identified, {"batch_group"})

    def test_group_membership_by_regex(self):
        cfg = fixtures.minimal_config(hostname="probe-42")
        cfg["hosts"] = [fixtures.host("probe-42", batches=[], interface="wlan0")]
        cfg["host_groups"] = [
            fixtures.host_group("g1", batches=["batch_regex"], hosts_regex=[".*-42$"])
        ]
        cfg["batches"] = []
        identified = set()
        self.daemon.process_gui_conf(cfg, None, set(), "probe-42", identified, "local0")
        self.assertEqual(identified, {"batch_regex"})

    def test_invalid_regex_is_warned_not_fatal(self):
        """Daemon lines 54-58: a bad regex warns and is skipped."""
        self.assertFalse(self.daemon.find_matching_regex(["[unclosed"], "probe-1"))
        self.assertSyslogContains("matching error")

    def test_regex_uses_match_not_fullmatch(self):
        """
        ``re.match`` anchors at the start only, so ``probe`` matches ``probe-1``.
        Operators writing group patterns need to know it is a prefix match.
        """
        self.assertTrue(self.daemon.find_matching_regex(["probe"], "probe-1"))
        self.assertFalse(self.daemon.find_matching_regex(["robe"], "probe-1"))


class TestMetadataPrecedence(DaemonTestCase):
    """
    Host metadata wins over group metadata.

    Daemon lines 280-285: ``add_metadata`` skips an lhs that is already present,
    and ``process_gui_conf`` adds the HOST's data first (line 295) then each
    group's (line 310). So a key defined on both resolves to the host's value.
    """

    def test_host_metadata_wins_over_group(self):
        cfg = fixtures.minimal_config(hostname="probe-1")
        cfg["hosts"] = [fixtures.host("probe-1", batches=[], facility="host_facility")]
        cfg["host_groups"] = [
            fixtures.host_group("g1", hosts=["probe-1"], facility="group_facility")
        ]
        cfg["batches"] = []
        metadata = set()
        self.daemon.process_gui_conf(cfg, None, metadata, "probe-1", set(), "local0")

        facility = {rhs for lhs, rhs, _ in metadata if lhs == "facility"}
        self.assertEqual(facility, {"host_facility"})

    def test_add_metadata_records_origin(self):
        metadata = set()
        self.daemon.add_metadata({"interface": "wlan0"}.items(), metadata, "probe-1")
        self.assertEqual(metadata, {("interface", "wlan0", "probe-1")})

    def test_add_metadata_is_first_write_wins(self):
        metadata = set()
        self.daemon.add_metadata({"k": "first"}.items(), metadata, "a")
        self.daemon.add_metadata({"k": "second"}.items(), metadata, "b")
        self.assertEqual(metadata, {("k", "first", "a")})
