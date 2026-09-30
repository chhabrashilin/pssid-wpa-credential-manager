"""
Import ``pssid-daemon.py`` as a module so its functions can be tested.

Two obstacles, both solved here:

1. **The filename is not a Python identifier.** ``pssid-daemon.py`` has a hyphen,
   so ``import pssid_daemon`` can never work. We load it by path through
   ``importlib``.

2. **It imports things that are not installed.** See :mod:`harness.stubs`. The
   stubs must be in ``sys.modules`` *before* the module body executes, so
   :func:`load_daemon` installs them first.

The daemon is imported exactly once and cached: it is not written to be
re-imported (module-level state, ``syslog.openlog`` side effects), and repeated
imports would make tests order-dependent.
"""

from __future__ import annotations

import importlib.util
import os
import sys
import types
from pathlib import Path

from . import stubs

#: Where the daemon checkout is expected relative to this file, when the whole
#: PSSID workspace is cloned side by side. Overridable with PSSID_DAEMON_PATH.
_DEFAULT_RELATIVE = Path("../../../../pssid-daemon/pssid-daemon.py")

_cached: types.ModuleType | None = None


class DaemonNotFound(Exception):
    """Raised when the daemon source cannot be located."""


def daemon_path() -> Path:
    """
    Resolve the path to ``pssid-daemon.py``.

    Order: ``PSSID_DAEMON_PATH`` env var, then the conventional sibling checkout.
    """
    override = os.environ.get("PSSID_DAEMON_PATH")
    if override:
        p = Path(override).expanduser().resolve()
        if not p.is_file():
            raise DaemonNotFound(f"PSSID_DAEMON_PATH points at {p}, which is not a file")
        return p

    p = (Path(__file__).parent / _DEFAULT_RELATIVE).resolve()
    if not p.is_file():
        raise DaemonNotFound(
            f"Could not find pssid-daemon.py at {p}.\n"
            "Clone UMNET-perfSONAR/pssid-daemon beside this repository, or set "
            "PSSID_DAEMON_PATH to the file."
        )
    return p


def load_daemon() -> types.ModuleType:
    """
    Load (once) and return the daemon module with stubs installed.

    The daemon's working directory matters: ``transform_job_list_for_batch_processing``
    opens ``batch_processor_format_template.j2`` by RELATIVE path (daemon line
    167), so tests that exercise it must run with the daemon directory as CWD.
    See :func:`daemon_dir`.
    """
    global _cached
    if _cached is not None:
        return _cached

    stubs.install()

    path = daemon_path()
    spec = importlib.util.spec_from_file_location("pssid_daemon_under_test", path)
    if spec is None or spec.loader is None:
        raise DaemonNotFound(f"Could not build an import spec for {path}")

    module = importlib.util.module_from_spec(spec)
    # Register before exec so any self-referential import resolves.
    sys.modules["pssid_daemon_under_test"] = module
    spec.loader.exec_module(module)

    _cached = module
    return module


def daemon_dir() -> Path:
    """Directory containing the daemon, i.e. where its .j2 template lives."""
    return daemon_path().parent


def available() -> bool:
    """True when the daemon source can be found; used to skip cleanly."""
    try:
        daemon_path()
        return True
    except DaemonNotFound:
        return False
