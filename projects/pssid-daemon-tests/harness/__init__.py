"""
Test harness for ``pssid-daemon.py``.

The daemon cannot be imported on a normal machine (see :mod:`harness.stubs`) and
its filename is not an identifier (see :mod:`harness.loader`). This package
solves both, then provides a :class:`DaemonTestCase` base that isolates each
test from the module-level state the daemon accumulates.
"""

from __future__ import annotations

import os
import shlex
import unittest
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator
from unittest import mock

from . import fixtures, loader, stubs

__all__ = ["DaemonTestCase", "fixtures", "loader", "stubs", "requires_daemon"]


requires_daemon = unittest.skipUnless(
    loader.available(),
    "pssid-daemon.py not found; clone UMNET-perfSONAR/pssid-daemon beside this "
    "repo or set PSSID_DAEMON_PATH",
)


@requires_daemon
class DaemonTestCase(unittest.TestCase):
    """
    Base class that loads the daemon once and resets captured state per test.

    Every subclass gets ``self.daemon`` (the module) and clean syslog / batch
    capture. Tests must never depend on execution order.
    """

    daemon: Any

    @classmethod
    def setUpClass(cls) -> None:
        cls.daemon = loader.load_daemon()

    def setUp(self) -> None:
        stubs.reset()

    # -- helpers ------------------------------------------------------------

    @contextmanager
    def in_daemon_dir(self) -> Iterator[Path]:
        """
        Run with the daemon's directory as CWD.

        Required for anything touching ``transform_job_list_for_batch_processing``:
        the daemon opens ``batch_processor_format_template.j2`` by relative path
        (daemon line 167), so it only works when CWD happens to be right. That
        fragility is itself pinned in ``test_defects``.
        """
        previous = Path.cwd()
        os.chdir(loader.daemon_dir())
        try:
            yield loader.daemon_dir()
        finally:
            os.chdir(previous)

    @contextmanager
    def fake_subprocess(self, returncode: int = 0, stdout: str = "") -> Iterator[mock.Mock]:
        """
        Replace ``subprocess.run`` inside the daemon module.

        The daemon shells out for every namespace and layer operation. Capturing
        the commands is how we assert on the contract with the layer 2 / layer 3
        helpers without a probe.
        """
        result = mock.Mock()
        result.returncode = returncode
        result.stdout = stdout
        result.stderr = ""

        with mock.patch.object(self.daemon.subprocess, "run", return_value=result) as run:
            yield run

    def commands_from(self, run_mock: mock.Mock) -> list[str]:
        """
        Every command passed to the mocked ``subprocess.run``, as a string.

        Layer helpers are run with an argument list, which is rendered with
        ``shlex.join`` so string assertions work for both forms.
        """
        return [
            c.args[0] if isinstance(c.args[0], str) else shlex.join(c.args[0])
            for c in run_mock.call_args_list
            if c.args
        ]

    def assertSyslogContains(self, needle: str) -> None:
        text = stubs.syslog_text()
        self.assertIn(
            needle,
            text,
            f"expected {needle!r} in syslog output.\n--- syslog ---\n{text or '(empty)'}",
        )
