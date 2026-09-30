"""
Characterisation tests for confirmed defects in ``pssid-daemon.py``.

**These tests assert the CURRENT, WRONG behaviour on purpose.**

That is what a characterisation suite is for: the daemon runs as root on every
probe and has never had a test, so before anything can safely be changed, what
it actually does has to be written down and locked in. Each test here fails the
day someone fixes the underlying bug -- and that failure is the signal to delete
the test and move the correct behaviour into the suite next door.

Every defect below was verified by execution, not by reading. The observed
output is quoted in each docstring.

Severity is about blast radius on a real deployment, not about how hard the fix
is:

===== ================================================================ ==========
ID     Defect                                                           Severity
===== ================================================================ ==========
D1     Tests accumulate across jobs in a multi-job batch                 **High**
D2     ``reference`` SSID is always the first GLOBAL profile             **High**
D3     ``sys.exit`` missing parentheses -- "no batch found" continues     Medium
D4     ``--debug`` is a no-op; debug output is permanently on             Low
D5     Template path is relative to CWD                                   Medium
===== ================================================================ ==========

See ``../README.md`` for suggested fixes.
"""

from __future__ import annotations

import os

from harness import DaemonTestCase, fixtures, loader


class TestD1_TestsAccumulateAcrossJobs(DaemonTestCase):
    """
    **D1 (High): a batch with two jobs runs the first job's tests twice.**

    ``transform_job_list_for_batch_processing`` initialises ``job_tests = []``
    at daemon line 171 -- OUTSIDE the ``for job_name in batch["jobs"]`` loop that
    starts at line 212. Inside, line 241 appends each test to that same list and
    never clears it, so job N is rendered with the tests of jobs 1..N.

    Line 244 then sets ``iteration = job_tests.__len__()``, so the iteration
    count is wrong in exactly the same way.

    Observed with two jobs of one test each::

        job job_one: iterations=1 tests=['www.google.com']
        job job_two: iterations=2 tests=['www.google.com', 'www.ebay.com']

    Consequence on a probe: every job after the first re-runs all preceding
    tests, inflating measurement volume and attributing results to the wrong
    job. Single-job batches -- including the shipped ``pssid_config.json`` --
    are unaffected, which is presumably why it has gone unnoticed.

    Fix: move ``job_tests = []`` inside the job loop (daemon line 212).
    """

    def test_second_job_inherits_first_jobs_tests(self):
        cfg = fixtures.multi_job_config()

        with self.in_daemon_dir():
            batch, valid = self.daemon.transform_job_list_for_batch_processing(
                cfg["batches"][0], cfg, set(), "local0"
            )

        self.assertTrue(valid)
        jobs = batch["batch_4_batchProcessor"]
        self.assertEqual(len(jobs), 2)

        def urls(job):
            return [t["test"]["spec"].get("url") for t in job["task"]["reference"]["tasks"]]

        self.assertEqual(urls(jobs[0]), ["www.google.com"])

        # CORRECT would be ["www.ebay.com"]. Pinning the defect:
        self.assertEqual(
            urls(jobs[1]),
            ["www.google.com", "www.ebay.com"],
            "D1 appears to be FIXED -- job_two no longer inherits job_one's tests. "
            "Delete this test and assert the correct behaviour instead.",
        )

    def test_iteration_count_is_inflated_for_later_jobs(self):
        cfg = fixtures.multi_job_config()

        with self.in_daemon_dir():
            batch, _ = self.daemon.transform_job_list_for_batch_processing(
                cfg["batches"][0], cfg, set(), "local0"
            )

        jobs = batch["batch_4_batchProcessor"]
        self.assertEqual(jobs[0]["iterations"], 1)
        # CORRECT would be 1.
        self.assertEqual(
            jobs[1]["iterations"],
            2,
            "D1 appears to be FIXED -- iteration count is no longer cumulative.",
        )


class TestD2_ReferenceSsidIsAlwaysTheFirstGlobalProfile(DaemonTestCase):
    """
    **D2 (High): archived results are labelled with the wrong SSID.**

    Daemon lines 187-189 build the pscheduler ``reference`` block from
    ``data["ssid_profiles"][0]`` -- the first GLOBALLY defined profile -- while
    ``execute_batch`` (line 631) iterates over ``batch["ssid_profiles"]``, the
    profiles the batch actually uses.

    So the SSID recorded against every measurement is whichever profile happens
    to be first in the config file, regardless of which network was really
    joined.

    Observed with two profiles where the batch selects the second::

        batch declares ssid_profiles: ['SECOND']
        reference SSID actually sent: 'FIRST'

    Consequence: with more than one SSID profile, the data pipeline cannot
    attribute a result to the network it was measured on. Deployments with a
    single profile are unaffected.

    Fix: derive the reference SSID from the profile being executed. Note this
    needs a signature change -- ``transform_job_list_for_batch_processing`` is
    called once per batch (line 330) but the SSID varies per profile inside
    ``execute_batch``, so the transform has to move or take the profile as an
    argument.
    """

    def test_reference_ssid_ignores_the_batch_selection(self):
        cfg = fixtures.minimal_config()
        cfg["ssid_profiles"] = [
            fixtures.ssid_profile("FIRST"),
            fixtures.ssid_profile("SECOND"),
        ]
        cfg["batches"][0]["ssid_profiles"] = ["SECOND"]

        with self.in_daemon_dir():
            batch, _ = self.daemon.transform_job_list_for_batch_processing(
                cfg["batches"][0], cfg, set(), "local0"
            )

        reference = batch["batch_4_batchProcessor"][0]["task"]["reference"]["tasks"][0][
            "reference"
        ]
        # CORRECT would be "SECOND".
        self.assertEqual(
            reference["SSID"],
            "FIRST",
            "D2 appears to be FIXED -- the reference SSID now follows the batch.",
        )

    def test_single_profile_deployments_are_correct(self):
        """The common case is right, which is why this has survived."""
        cfg = fixtures.minimal_config()
        with self.in_daemon_dir():
            batch, _ = self.daemon.transform_job_list_for_batch_processing(
                cfg["batches"][0], cfg, set(), "local0"
            )
        reference = batch["batch_4_batchProcessor"][0]["task"]["reference"]["tasks"][0][
            "reference"
        ]
        self.assertEqual(reference["SSID"], "MWireless")


class TestD3_SysExitMissingParentheses(DaemonTestCase):
    """
    **D3 (Medium): "No batch found" does not exit.**

    Daemon line 319 is ``sys.exit`` with no call parentheses. It evaluates the
    built-in function object, discards it, and execution continues into the
    scheduling loop -- which then does nothing, because the batch list is empty.

    The probe therefore starts, logs an error nobody is watching, schedules
    nothing, and stays up looking healthy. This is the same silent-idle failure
    mode as the missing ``wpa_supplicant`` conf at line 483.

    Fix: ``sys.exit(1)``.
    """

    def test_line_319_is_a_bare_sys_exit(self):
        source = loader.daemon_path().read_text(encoding="utf-8").splitlines()
        bare = [
            (n, line.strip())
            for n, line in enumerate(source, 1)
            if line.strip() == "sys.exit"
        ]
        self.assertEqual(
            bare,
            [(319, "sys.exit")],
            "D3 appears to be FIXED -- no bare `sys.exit` remains.",
        )

    def test_empty_batch_list_does_not_raise_systemexit(self):
        """
        A host that matches but has no batches anywhere. The daemon reaches line
        317-319 and, because of the missing parentheses, returns normally.
        """
        cfg = fixtures.minimal_config(hostname="probe-1")
        cfg["hosts"] = [fixtures.host("probe-1", batches=[])]
        cfg["host_groups"] = []
        cfg["batches"] = []

        # CORRECT would be assertRaises(SystemExit).
        self.daemon.process_gui_conf(cfg, None, set(), "probe-1", set(), "local0")
        self.assertSyslogContains("No batch found")


class TestD4_DebugFlagIsANoOp(DaemonTestCase):
    """
    **D4 (Low): ``--debug`` does nothing and debug output is always on.**

    Two independent mistakes that cancel into "always verbose":

    * Daemon line 687, inside ``main``: ``debug = True`` binds a LOCAL name. It
      never reaches ``run_batch_processor``, and because it is only assigned
      under ``if args.debug``, referencing it otherwise would be an
      ``UnboundLocalError`` -- except nothing reads it.
    * Daemon line 654, inside ``run_batch_processor``: ``if debug:`` resolves to
      the module-level ``debug`` FUNCTION defined at line 637. A function object
      is always truthy, so the branch is taken unconditionally.

    Consequence: every probe runs the batch processor in debug mode and prints
    to stderr regardless of the flag. Harmless but noisy, and it means the flag
    cannot be trusted when diagnosing a probe.

    Fix: pass the flag explicitly, e.g. ``run_batch_processor(batch, debug_enabled)``.
    """

    def test_module_level_debug_is_a_function_and_thus_truthy(self):
        self.assertTrue(callable(self.daemon.debug))
        self.assertTrue(bool(self.daemon.debug))

    def test_batch_processor_always_receives_a_debug_callback(self):
        cfg = fixtures.minimal_config()
        with self.in_daemon_dir():
            batch, _ = self.daemon.transform_job_list_for_batch_processing(
                cfg["batches"][0], cfg, set(), "local0"
            )
        self.daemon.run_batch_processor(batch)

        from harness import stubs

        self.assertEqual(len(stubs.SUBMITTED_BATCHES), 1)
        self.assertEqual(stubs.SUBMITTED_BATCHES[0]["schema"], 3)


class TestD5_TemplatePathIsRelativeToCwd(DaemonTestCase):
    """
    **D5 (Medium): the Jinja template is opened by relative path.**

    Daemon line 167::

        with open('batch_processor_format_template.j2', 'r') as template_file:

    Nothing anchors this to the daemon's own directory, so the daemon only works
    when the current working directory happens to contain the template. The
    systemd unit installed by ``ansible-role-pssid-daemon`` must therefore set
    ``WorkingDirectory``, and any operator running the daemon by hand from
    elsewhere gets a ``FileNotFoundError`` at the first batch -- long after
    startup appeared to succeed.

    Observed from ``/tmp``::

        FileNotFoundError: batch_processor_format_template.j2

    Fix: resolve against ``os.path.dirname(os.path.abspath(__file__))``.
    """

    def test_transform_fails_from_an_unrelated_directory(self):
        cfg = fixtures.minimal_config()
        previous = os.getcwd()
        os.chdir(os.path.expanduser("~"))
        try:
            with self.assertRaises(FileNotFoundError) as ctx:
                self.daemon.transform_job_list_for_batch_processing(
                    cfg["batches"][0], cfg, set(), "local0"
                )
            self.assertEqual(ctx.exception.filename, "batch_processor_format_template.j2")
        finally:
            os.chdir(previous)

    def test_transform_succeeds_from_the_daemon_directory(self):
        cfg = fixtures.minimal_config()
        with self.in_daemon_dir():
            _, valid = self.daemon.transform_job_list_for_batch_processing(
                cfg["batches"][0], cfg, set(), "local0"
            )
        self.assertTrue(valid)
