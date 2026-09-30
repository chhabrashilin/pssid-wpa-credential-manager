"""
The health document: what a probe reports about itself.

Design rules, all of them learned from reading how the rest of the system
reports status:

* **Never claim more than was observed.** ``pssid-gui2``'s ``provision-probes.sh``
  gets this right -- it reports that a file was DELIVERED, never that a probe
  adopted it, because delivery is the only thing it can see. Every check here
  carries the evidence it based its verdict on.
* **Distinguish "broken" from "cannot tell".** A check that could not run is
  ``UNKNOWN``, never ``OK``. Reporting a probe healthy because the check failed
  is the exact failure this project exists to prevent.
* **No secrets.** A ``wpa_supplicant`` conf contains a network-equivalent
  credential (a PSK hex or an NT hash). This reports that a file EXISTS, its
  mode, and its size -- never a byte of its content.
"""

from __future__ import annotations

import dataclasses
import datetime
import enum
import json
from typing import Any


class Status(enum.Enum):
    """
    Ordered by severity so ``max()`` gives a document's overall status.

    ``UNKNOWN`` sits above ``OK`` deliberately: a check that could not run is
    not evidence of health.
    """

    OK = 0
    UNKNOWN = 1
    WARN = 2
    CRITICAL = 3

    def __lt__(self, other: "Status") -> bool:
        return self.value < other.value

    @property
    def label(self) -> str:
        return self.name


@dataclasses.dataclass
class CheckResult:
    """One observation about the probe."""

    name: str
    status: Status
    summary: str
    #: What the verdict was based on. Free-form but never secret-bearing.
    evidence: dict[str, Any] = dataclasses.field(default_factory=dict)
    #: What an operator should do. Empty when there is nothing to do.
    remedy: str = ""

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "name": self.name,
            "status": self.status.label,
            "summary": self.summary,
        }
        if self.evidence:
            out["evidence"] = self.evidence
        if self.remedy:
            out["remedy"] = self.remedy
        return out


@dataclasses.dataclass
class HealthReport:
    """Everything one probe knows about itself at one moment."""

    probe_id: str
    generated_at: datetime.datetime
    checks: list[CheckResult] = dataclasses.field(default_factory=list)
    #: Version of this reporter, so a collector can handle format drift.
    schema: int = 1

    def add(self, result: CheckResult) -> CheckResult:
        self.checks.append(result)
        return result

    @property
    def status(self) -> Status:
        """The worst status among the checks. An empty report is UNKNOWN."""
        if not self.checks:
            return Status.UNKNOWN
        return max(c.status for c in self.checks)

    @property
    def is_testing(self) -> bool:
        """
        The single question this project exists to answer: can this probe run a
        batch right now?

        True only when nothing is CRITICAL. A WARN (say, a config older than
        expected) still leaves the probe able to test.
        """
        return self.status < Status.CRITICAL

    def by_status(self, status: Status) -> list[CheckResult]:
        return [c for c in self.checks if c.status is status]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "probe_id": self.probe_id,
            "generated_at": self.generated_at.replace(microsecond=0).isoformat(),
            "status": self.status.label,
            "is_testing": self.is_testing,
            "checks": [c.to_dict() for c in self.checks],
        }

    def to_json(self, indent: int | None = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, sort_keys=False)

    # -- human output -------------------------------------------------------

    def to_text(self, use_colour: bool = False) -> str:
        glyph = {
            Status.OK: "ok",
            Status.UNKNOWN: " ?",
            Status.WARN: "!!",
            Status.CRITICAL: "XX",
        }
        colour = {
            Status.OK: "\033[32m",
            Status.UNKNOWN: "\033[2m",
            Status.WARN: "\033[33m",
            Status.CRITICAL: "\033[31m",
        }
        off = "\033[0m" if use_colour else ""

        lines = [f"probe: {self.probe_id}", f"time:  {self.generated_at.replace(microsecond=0).isoformat()}", ""]
        for c in self.checks:
            pre = colour[c.status] if use_colour else ""
            lines.append(f"  {pre}[{glyph[c.status]}]{off} {c.name}: {c.summary}")
            if c.remedy and c.status is not Status.OK:
                lines.append(f"       -> {c.remedy}")

        lines.append("")
        verdict = "TESTING" if self.is_testing else "NOT TESTING"
        pre = colour[self.status] if use_colour else ""
        lines.append(f"  {pre}{self.status.label}{off} -- this probe is {verdict}")
        return "\n".join(lines)

    @property
    def exit_code(self) -> int:
        """0 healthy · 1 warnings · 2 critical. Suitable for Nagios-style use."""
        if self.status is Status.CRITICAL:
            return 2
        if self.status is Status.WARN:
            return 1
        return 0
