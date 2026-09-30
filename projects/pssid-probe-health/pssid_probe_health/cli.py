"""
Command-line entry point for the probe health reporter.

    pssid-probe-health                     # human summary, exit 0/1/2
    pssid-probe-health --json              # machine readable
    pssid-probe-health --post URL          # send to a collector
    pssid-probe-health --config PATH       # non-default config location
"""

from __future__ import annotations

import argparse
import datetime
import json
import socket
import sys
import urllib.error
import urllib.request
from typing import Sequence

from . import checks
from .checks import Environment
from .model import HealthReport, Status

__version__ = "1.0.0"


def run_checks(env: Environment) -> HealthReport:
    """Run every registered check and collect the results."""
    report = HealthReport(probe_id=env.hostname, generated_at=env.now())
    config = checks.load_config(env)

    for _name, fn, needs_config in checks.ALL_CHECKS:
        try:
            result = fn(env, config) if needs_config else fn(env)
        except Exception as exc:  # a broken check must not hide the others
            from .model import CheckResult

            result = CheckResult(
                name=_name,
                status=Status.UNKNOWN,
                summary=f"check raised {type(exc).__name__}: {exc}",
                remedy="This is a bug in the health reporter, not necessarily in the probe.",
            )
        report.add(result)

    return report


def post_report(report: HealthReport, url: str, timeout: float = 10.0) -> tuple[bool, str]:
    """
    POST the report as JSON. Returns ``(ok, detail)``.

    Failing to reach the collector is reported but never changes the probe's own
    verdict: the probe's health is a fact about the probe, not about whether a
    server was reachable.
    """
    body = report.to_json(indent=None).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "User-Agent": f"pssid-probe-health/{__version__}",
            "X-Probe-Id": report.probe_id,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return True, f"HTTP {response.status}"
    except urllib.error.HTTPError as exc:
        return False, f"HTTP {exc.code}"
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return False, str(exc)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pssid-probe-health",
        description=(
            "Report whether this pSSID probe can actually run a batch. "
            "Exit 0 healthy, 1 warnings, 2 critical."
        ),
    )
    parser.add_argument("--json", action="store_true", help="emit JSON instead of text")
    parser.add_argument(
        "--config",
        default=checks.DEFAULT_CONFIG_PATH,
        help=f"path to pssid_config.json (default: {checks.DEFAULT_CONFIG_PATH})",
    )
    parser.add_argument(
        "--hostname",
        default=None,
        help="override the detected hostname (must match the GUI's host entry)",
    )
    parser.add_argument(
        "--root",
        default="",
        help=(
            "treat this directory as / -- run the checks against a fixture tree "
            "instead of a real probe (for testing and demos)"
        ),
    )
    parser.add_argument("--post", metavar="URL", help="POST the report to a collector")
    parser.add_argument(
        "--post-timeout", type=float, default=10.0, help="collector timeout in seconds"
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="print nothing; use the exit code only (for cron)",
    )
    parser.add_argument(
        "--warn-days",
        type=int,
        default=30,
        help="warn when pssid_config.json is older than this (default: 30)",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    hostname = args.hostname or socket.gethostname()
    env = Environment(
        hostname=hostname,
        config_path=args.config,
        root=args.root,
        warn_days=args.warn_days,
    )
    report = run_checks(env)

    if args.post:
        ok, detail = post_report(report, args.post, args.post_timeout)
        if not ok and not args.quiet:
            print(f"warning: could not reach collector {args.post}: {detail}", file=sys.stderr)

    if args.quiet:
        return report.exit_code

    if args.json:
        print(report.to_json())
    else:
        print(report.to_text(use_colour=sys.stdout.isatty()))

    return report.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
