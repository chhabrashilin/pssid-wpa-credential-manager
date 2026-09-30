"""
``schedule_batch`` -- how a batch's next run time is chosen.

A batch may reference several schedules (the shipped config's ``batch_A``
references both ``every_two_minutes`` and ``every_three_minute``). The daemon
computes the next fire time for each and enqueues the batch once, at the
EARLIEST of them (daemon lines 73-105). The batch then re-schedules itself after
each run (line 69), so the queue holds at most one entry per batch.

Time is made deterministic by :class:`harness.stubs.FakeCroniter`, which maps a
cron expression to a fixed offset instead of parsing it. These tests are about
the daemon's selection logic, not about croniter's correctness.
"""

from __future__ import annotations

import sched
import time
from unittest import mock

from harness import DaemonTestCase, fixtures, stubs


class SchedulerProbe:
    """Records ``enterabs`` calls instead of running anything."""

    def __init__(self):
        self.entries = []

    def enterabs(self, when, priority, action, argument=()):
        self.entries.append(
            {"when": when, "priority": priority, "action": action, "argument": argument}
        )
        return object()


class TestEarliestScheduleWins(DaemonTestCase):
    def test_single_schedule_is_enqueued(self):
        cfg = fixtures.minimal_config()
        probe = SchedulerProbe()

        self.daemon.schedule_batch(probe, cfg["batches"][0], cfg)

        self.assertEqual(len(probe.entries), 1)

    def test_earliest_of_several_schedules_is_chosen(self):
        cfg = fixtures.minimal_config()
        cfg["schedules"] = [
            fixtures.schedule("slow", "*/30 * * * *"),
            fixtures.schedule("fast", "*/2 * * * *"),
            fixtures.schedule("medium", "*/10 * * * *"),
        ]
        cfg["batches"][0]["schedules"] = ["slow", "fast", "medium"]
        probe = SchedulerProbe()

        self.daemon.schedule_batch(probe, cfg["batches"][0], cfg)

        self.assertEqual(len(probe.entries), 1)
        # run_batch is called with (s, batch, data, cron_expression)
        chosen_expression = probe.entries[0]["argument"][3]
        self.assertEqual(chosen_expression, "*/2 * * * *")

    def test_order_in_the_config_does_not_matter(self):
        """The fastest schedule wins whether it is listed first or last."""
        for order in (["fast", "slow"], ["slow", "fast"]):
            with self.subTest(order=order):
                stubs.reset()
                cfg = fixtures.minimal_config()
                cfg["schedules"] = [
                    fixtures.schedule("slow", "*/30 * * * *"),
                    fixtures.schedule("fast", "*/2 * * * *"),
                ]
                cfg["batches"][0]["schedules"] = order
                probe = SchedulerProbe()

                self.daemon.schedule_batch(probe, cfg["batches"][0], cfg)

                self.assertEqual(probe.entries[0]["argument"][3], "*/2 * * * *")

    def test_batch_priority_is_passed_to_the_scheduler(self):
        cfg = fixtures.minimal_config()
        cfg["batches"][0]["priority"] = 7
        probe = SchedulerProbe()

        self.daemon.schedule_batch(probe, cfg["batches"][0], cfg)

        self.assertEqual(probe.entries[0]["priority"], 7)

    def test_scheduled_action_is_run_batch(self):
        cfg = fixtures.minimal_config()
        probe = SchedulerProbe()

        self.daemon.schedule_batch(probe, cfg["batches"][0], cfg)

        self.assertIs(probe.entries[0]["action"], self.daemon.run_batch)


class TestMissingSchedules(DaemonTestCase):
    def test_unknown_schedule_name_is_warned_and_skipped(self):
        cfg = fixtures.minimal_config()
        cfg["batches"][0]["schedules"] = ["does_not_exist"]
        probe = SchedulerProbe()

        self.daemon.schedule_batch(probe, cfg["batches"][0], cfg)

        self.assertEqual(probe.entries, [])
        self.assertSyslogContains("No cron expression found for schedule: does_not_exist")

    def test_batch_with_no_schedules_is_never_enqueued(self):
        """
        Daemon lines 101-102. The batch is silently idle: it exists, it is valid,
        and it never runs. Only a syslog warning marks it.
        """
        cfg = fixtures.minimal_config()
        cfg["batches"][0]["schedules"] = []
        probe = SchedulerProbe()

        self.daemon.schedule_batch(probe, cfg["batches"][0], cfg)

        self.assertEqual(probe.entries, [])
        self.assertSyslogContains("does not have a schedule")

    def test_one_valid_schedule_among_invalid_ones_still_works(self):
        cfg = fixtures.minimal_config()
        cfg["schedules"] = [fixtures.schedule("real", "*/5 * * * *")]
        cfg["batches"][0]["schedules"] = ["ghost", "real", "phantom"]
        probe = SchedulerProbe()

        self.daemon.schedule_batch(probe, cfg["batches"][0], cfg)

        self.assertEqual(len(probe.entries), 1)
        self.assertEqual(probe.entries[0]["argument"][3], "*/5 * * * *")


class TestReschedulingLoop(DaemonTestCase):
    """
    ``run_batch`` executes the batch then re-schedules it (daemon lines 63-69),
    which is what keeps the ``sched`` queue alive across the daemon's lifetime.
    """

    def test_run_batch_executes_then_reschedules(self):
        cfg = fixtures.minimal_config()
        probe = SchedulerProbe()
        order = []

        with mock.patch.object(
            self.daemon, "execute_batch", side_effect=lambda b, d: order.append("execute")
        ):
            with mock.patch.object(
                self.daemon,
                "schedule_batch",
                side_effect=lambda s, b, d: order.append("reschedule"),
            ):
                self.daemon.run_batch(probe, cfg["batches"][0], cfg, "*/2 * * * *")

        self.assertEqual(order, ["execute", "reschedule"])

    def test_run_batch_logs_the_run(self):
        cfg = fixtures.minimal_config()
        probe = SchedulerProbe()

        with mock.patch.object(self.daemon, "execute_batch"):
            with mock.patch.object(self.daemon, "schedule_batch"):
                self.daemon.run_batch(probe, cfg["batches"][0], cfg, "*/2 * * * *")

        self.assertSyslogContains("Running batch")
        self.assertSyslogContains("batch_A")

    def test_a_real_scheduler_accepts_the_entry(self):
        """
        Integration check against the stdlib ``sched.scheduler`` the daemon
        actually uses, so the argument shape is verified for real rather than
        only against the probe double.
        """
        cfg = fixtures.minimal_config()
        real = sched.scheduler(time.time, time.sleep)

        self.daemon.schedule_batch(real, cfg["batches"][0], cfg)

        self.assertEqual(len(real.queue), 1)
        # Do NOT run it: that would execute the batch. Cancel instead.
        for event in list(real.queue):
            real.cancel(event)
        self.assertEqual(len(real.queue), 0)
