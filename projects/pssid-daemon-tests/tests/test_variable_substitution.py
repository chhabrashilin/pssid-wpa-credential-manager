"""
``variable_substitution`` -- how ``$placeholders`` in a config get resolved.

This is the least obvious code in the daemon and the easiest to break, because
the rules are implicit and surprising. The shipped ``pssid_config.json`` relies
on it: ``"test_interface": "$interface"`` is resolved from the host's ``data``
block (``"interface": "wlan0"``).

The rules, read off daemon lines 139-163 and confirmed by execution:

1. Only ``str`` values containing ``$`` are candidates (line 143).
2. A key whose lowercased name CONTAINS ``"name"`` is skipped entirely
   (line 143) -- so ``name``, ``batch_name`` and ``hostname`` are never touched.
3. The match is ``lhs in value`` -- a SUBSTRING test against the VALUE, not the
   key (line 146). ``interface`` matches ``"$interface"``.
4. On match, the WHOLE value is replaced by ``rhs`` (line 147). It is not an
   interpolation: ``"$interface0"`` becomes ``"wlan0"``, not ``"wlan00"``.
5. Lists and dicts are walked recursively (lines 154-161); lists of non-dicts
   are not descended into.
6. If any ``$`` survives, the function reports ``substituted=False`` (line 151)
   and the caller invalidates the batch.

Rule 4 is worth staring at. Substitution replaces rather than interpolates, so
composite values like ``"$prefix-suffix"`` silently lose the suffix.
"""

from __future__ import annotations

from harness import DaemonTestCase, fixtures


class TestBasicSubstitution(DaemonTestCase):
    def test_placeholder_is_replaced_from_metadata(self):
        metadata = {("interface", "wlan0", "probe-1")}
        obj = {"test_interface": "$interface"}

        result, substituted = self.daemon.variable_substitution(obj, metadata)

        self.assertTrue(substituted)
        self.assertEqual(result["test_interface"], "wlan0")

    def test_value_without_dollar_is_untouched(self):
        metadata = {("interface", "wlan0", "probe-1")}
        obj = {"test_interface": "eth0"}

        result, substituted = self.daemon.variable_substitution(obj, metadata)

        self.assertTrue(substituted)
        self.assertEqual(result["test_interface"], "eth0")

    def test_unresolved_placeholder_reports_failure(self):
        metadata = {("interface", "wlan0", "probe-1")}
        obj = {"test_interface": "$nonexistent"}

        _, substituted = self.daemon.variable_substitution(obj, metadata)

        self.assertFalse(substituted)

    def test_unresolved_placeholder_invalidates_the_batch(self):
        """Daemon lines 175-180: the caller turns this into an invalid batch."""
        cfg = fixtures.minimal_config()
        cfg["batches"][0]["test_interface"] = "$never_defined"

        with self.in_daemon_dir():
            _, valid = self.daemon.transform_job_list_for_batch_processing(
                cfg["batches"][0], cfg, set(), "local0"
            )

        self.assertFalse(valid)
        self.assertSyslogContains("has unresolved variables")


class TestSurprisingRules(DaemonTestCase):
    """The behaviours most likely to bite someone writing a config."""

    def test_keys_containing_name_are_skipped(self):
        """
        Rule 2. ``batch_name`` contains "name", so its ``$`` is never resolved --
        and, notably, never reported as unresolved either, because the key is
        skipped before the check.
        """
        metadata = {("batch", "real-batch", "probe-1")}
        obj = {"batch_name": "$batch"}

        result, substituted = self.daemon.variable_substitution(obj, metadata)

        self.assertEqual(result["batch_name"], "$batch")
        self.assertTrue(substituted, "a skipped key does not count as unresolved")

    def test_match_is_against_the_value_not_the_key(self):
        """
        Rule 3. The metadata key need not relate to the config key at all; it
        only has to appear inside the value string.
        """
        metadata = {("wlan", "SUBSTITUTED", "probe-1")}
        obj = {"totally_unrelated_key": "$wlan"}

        result, _ = self.daemon.variable_substitution(obj, metadata)

        self.assertEqual(result["totally_unrelated_key"], "SUBSTITUTED")

    def test_substitution_replaces_the_whole_value(self):
        """
        Rule 4, the sharp edge. ``"$interface-monitor"`` does not become
        ``"wlan0-monitor"`` -- it becomes ``"wlan0"``. Anyone expecting shell- or
        Jinja-style interpolation will lose data silently.
        """
        metadata = {("interface", "wlan0", "probe-1")}
        obj = {"test_interface": "$interface-monitor"}

        result, substituted = self.daemon.variable_substitution(obj, metadata)

        self.assertEqual(result["test_interface"], "wlan0")
        self.assertNotEqual(result["test_interface"], "wlan0-monitor")
        self.assertTrue(substituted)

    def test_substring_metadata_key_matches_a_longer_placeholder(self):
        """
        A short metadata key matches any value containing it. ``face`` matches
        ``$interface``, so poorly chosen metadata names collide silently.
        """
        metadata = {("face", "MATCHED", "probe-1")}
        obj = {"test_interface": "$interface"}

        result, _ = self.daemon.variable_substitution(obj, metadata)

        self.assertEqual(result["test_interface"], "MATCHED")


class TestRecursion(DaemonTestCase):
    def test_nested_dict_is_substituted(self):
        metadata = {("dest", "host.example.edu", "probe-1")}
        obj = {"spec": {"dest": "$dest"}}

        result, substituted = self.daemon.variable_substitution(obj, metadata)

        self.assertTrue(substituted)
        self.assertEqual(result["spec"]["dest"], "host.example.edu")

    def test_list_of_dicts_is_substituted(self):
        metadata = {("url", "www.example.edu", "probe-1")}
        obj = {"tests": [{"url": "$url"}, {"url": "$url"}]}

        result, _ = self.daemon.variable_substitution(obj, metadata)

        self.assertEqual([t["url"] for t in result["tests"]], ["www.example.edu"] * 2)

    def test_list_of_plain_strings_is_NOT_substituted(self):
        """
        Daemon lines 154-158 descend only into dict elements, so a bare string
        inside a list keeps its placeholder -- and, because the recursive call
        returns its own flag that the caller discards, this is not reported as
        unresolved either.
        """
        metadata = {("ssid", "eduroam", "probe-1")}
        obj = {"ssid_profiles": ["$ssid"]}

        result, substituted = self.daemon.variable_substitution(obj, metadata)

        self.assertEqual(result["ssid_profiles"], ["$ssid"])
        self.assertTrue(substituted)

    def test_nested_failure_is_not_propagated_to_the_caller(self):
        """
        The recursive calls at lines 158 and 161 ignore the returned flag, so an
        unresolved placeholder nested inside a dict reports success at the top
        level. Characterisation, not endorsement.
        """
        metadata = set()
        obj = {"spec": {"dest": "$never_defined"}}

        result, substituted = self.daemon.variable_substitution(obj, metadata)

        self.assertEqual(result["spec"]["dest"], "$never_defined")
        self.assertTrue(
            substituted,
            "nested failures now propagate -- the daemon has been improved; "
            "update this test",
        )


class TestEndToEndWithRealConfigShape(DaemonTestCase):
    """The shipped config's own substitution, exercised through the real path."""

    def test_dollar_interface_resolves_from_host_data(self):
        cfg = fixtures.substitution_config()
        metadata = {("interface", "wlan0", "probe-1")}

        with self.in_daemon_dir():
            batch, valid = self.daemon.transform_job_list_for_batch_processing(
                cfg["batches"][0], cfg, metadata, "local0"
            )

        self.assertTrue(valid)
        self.assertEqual(batch["test_interface"], "wlan0")

    def test_resolved_interface_reaches_the_pscheduler_namespace(self):
        """
        The substituted interface must flow into the ``linuxnns`` context, or
        tests run outside the probe's namespace and measure the wrong path.
        """
        cfg = fixtures.substitution_config()
        metadata = {("interface", "wlan0", "probe-1")}

        with self.in_daemon_dir():
            batch, _ = self.daemon.transform_job_list_for_batch_processing(
                cfg["batches"][0], cfg, metadata, "local0"
            )

        task = batch["batch_4_batchProcessor"][0]["task"]["reference"]["tasks"][0]
        namespaces = [
            entry["data"]["namespace"]
            for group in task["contexts"]["contexts"]
            for entry in group
        ]
        self.assertEqual(namespaces, ["pssid_wlan0"])
