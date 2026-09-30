"""
Stand-in implementations of the modules ``pssid-daemon.py`` imports at module
scope but which cannot be installed on a developer machine or a CI runner.

This is the whole reason the daemon has no tests. Line 22-24 of the daemon are::

    from croniter import croniter
    from jinja2 import Template
    import pscheduler.batchprocessor

``croniter`` is a third-party package, and ``pscheduler`` ships only as part of a
perfSONAR installation. Importing the daemon therefore fails immediately
anywhere that is not a provisioned probe -- so nothing about it has ever been
unit tested, including the parts that are pure data transformation and have no
business needing hardware.

These stubs are deliberately *minimal and honest*:

* They implement only what the daemon actually calls.
* Where behaviour matters to a test, it is deterministic and controllable.
* They never pretend to be the real thing. ``FakeCroniter`` does not parse cron;
  it maps an expression to a fixed offset so that "which schedule fires first"
  can be asserted without depending on wall-clock time or on croniter's
  correctness (which is not what we are testing).

``jinja2`` is NOT stubbed. It is a normal pip package that is usually present,
and the template rendering is real logic worth exercising for real.
"""

from __future__ import annotations

import datetime
import sys
import types
from typing import Any, Callable

# ---------------------------------------------------------------------------
# croniter
# ---------------------------------------------------------------------------

#: Maps a cron expression to "minutes from now" for the fake scheduler.
#: Tests set this to control which schedule is earliest. Anything not listed
#: falls back to :func:`_default_offset_minutes`.
CRON_OFFSETS: dict[str, int] = {}


def _default_offset_minutes(expression: str) -> int:
    """
    Derive a deterministic offset from an expression without parsing cron.

    ``*/5 * * * *`` -> 5 minutes. Anything else -> 60 minutes. This is enough to
    order schedules relative to one another, which is the only property the
    daemon's scheduling logic actually depends on.
    """
    parts = expression.split()
    if parts and parts[0].startswith("*/"):
        try:
            return max(1, int(parts[0][2:]))
        except ValueError:
            pass
    return 60


class FakeCroniter:
    """Minimal replacement for ``croniter.croniter``."""

    def __init__(self, expression: str, start_time: datetime.datetime):
        self.expression = expression
        self.start_time = start_time
        self.calls = 0

    def get_next(self, ret_type: type = float) -> Any:
        self.calls += 1
        minutes = CRON_OFFSETS.get(
            self.expression, _default_offset_minutes(self.expression)
        )
        nxt = self.start_time + datetime.timedelta(minutes=minutes)
        if ret_type is datetime.datetime:
            return nxt
        return nxt.timestamp()


# ---------------------------------------------------------------------------
# pscheduler.batchprocessor
# ---------------------------------------------------------------------------

#: Every batch handed to the batch processor, in order. Tests assert on this to
#: verify what the daemon would actually have run.
SUBMITTED_BATCHES: list[dict[str, Any]] = []


class FakeBatchProcessor:
    """Replacement for ``pscheduler.batchprocessor.BatchProcessor``."""

    #: Set by a test to make the processor raise, exercising failure paths.
    raise_on_call: Exception | None = None

    def __init__(self, batch: dict[str, Any]):
        self.batch = batch
        SUBMITTED_BATCHES.append(batch)

    def __call__(self, debug: Callable[[str], None] | None = None) -> dict[str, Any]:
        if FakeBatchProcessor.raise_on_call is not None:
            raise FakeBatchProcessor.raise_on_call
        return {"succeeded": True, "jobs": len(self.batch.get("jobs", []))}


# ---------------------------------------------------------------------------
# syslog
# ---------------------------------------------------------------------------

#: Every ``(priority, message)`` the daemon logged. Syslog is the daemon's ONLY
#: error channel on a real probe, so asserting on it is how we verify that a
#: failure is actually reported rather than swallowed.
SYSLOG_MESSAGES: list[tuple[int, str]] = []


class FakeSyslog(types.ModuleType):
    """Replacement for the stdlib ``syslog`` module (absent on Windows)."""

    LOG_EMERG, LOG_ALERT, LOG_CRIT, LOG_ERR = 0, 1, 2, 3
    LOG_WARNING, LOG_NOTICE, LOG_INFO, LOG_DEBUG = 4, 5, 6, 7
    LOG_LOCAL0, LOG_LOCAL1, LOG_LOCAL2, LOG_LOCAL3 = 128, 136, 144, 152
    LOG_LOCAL4, LOG_LOCAL5, LOG_LOCAL6, LOG_LOCAL7 = 160, 168, 176, 184
    LOG_DAEMON = 24

    def __init__(self) -> None:
        super().__init__("syslog")
        self.opened_with: dict[str, Any] | None = None

    def openlog(self, ident: str = "", logoption: int = 0, facility: int = 0) -> None:
        self.opened_with = {"ident": ident, "facility": facility}

    def syslog(self, *args: Any) -> None:
        if len(args) == 1:
            SYSLOG_MESSAGES.append((self.LOG_INFO, str(args[0])))
        else:
            SYSLOG_MESSAGES.append((int(args[0]), str(args[1])))

    def closelog(self) -> None:
        pass


# ---------------------------------------------------------------------------
# Installation
# ---------------------------------------------------------------------------


def install() -> FakeSyslog:
    """
    Put the stubs into :data:`sys.modules` so a subsequent import of the daemon
    resolves to them. Idempotent.

    Returns the syslog stub so callers can inspect ``opened_with``.
    """
    croniter_mod = types.ModuleType("croniter")
    croniter_mod.croniter = FakeCroniter  # type: ignore[attr-defined]
    sys.modules["croniter"] = croniter_mod

    pscheduler_mod = types.ModuleType("pscheduler")
    batchprocessor_mod = types.ModuleType("pscheduler.batchprocessor")
    batchprocessor_mod.BatchProcessor = FakeBatchProcessor  # type: ignore[attr-defined]
    pscheduler_mod.batchprocessor = batchprocessor_mod  # type: ignore[attr-defined]
    sys.modules["pscheduler"] = pscheduler_mod
    sys.modules["pscheduler.batchprocessor"] = batchprocessor_mod

    syslog_stub = FakeSyslog()
    sys.modules["syslog"] = syslog_stub
    return syslog_stub


def reset() -> None:
    """Clear all captured state. Call from ``setUp`` so tests cannot leak."""
    SYSLOG_MESSAGES.clear()
    SUBMITTED_BATCHES.clear()
    CRON_OFFSETS.clear()
    FakeBatchProcessor.raise_on_call = None


def syslog_text() -> str:
    """All syslog output joined, for substring assertions."""
    return "\n".join(m for _, m in SYSLOG_MESSAGES)


def syslog_errors() -> list[str]:
    """Only the messages logged at LOG_ERR."""
    return [m for p, m in SYSLOG_MESSAGES if p == FakeSyslog.LOG_ERR]
