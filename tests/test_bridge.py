# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Stephen Makonin
"""Synthetic interval tests plus a read-only frozen replay smoke check."""
from __future__ import annotations

import json
import os
from pathlib import Path
import stat
import tempfile
import unittest

import numpy as np

from wattdialogue.adapter import MODEL_VERSION, ReplayStore, iso_time, parse_time
from wattdialogue.labels import LabelRegistry
from wattdialogue.tools import EnergyTools

T = 1_500_000_000


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = ReplayStore(self.root)
        self.labels = LabelRegistry()
        self.tools = EnergyTools(self.store, self.labels)

    def tearDown(self):
        self.temp.cleanup()

    def fixture(self, t, meter, component0=None, recording="R1Hz", components=None, revised=None):
        block = 17422 if recording == "R1Hz" else 15431
        path = self.root / recording / "verification" / f"{block}.npz"
        path.parent.mkdir(parents=True, exist_ok=True)
        t = np.asarray(t, dtype=np.int64)
        if components is None:
            components = np.zeros((len(t), 24))
            if component0 is not None:
                components[:, 0] = component0
        # Deliberately poisonous evaluator columns/masks must never affect tools.
        reference = np.full((len(t), 18), np.nan)
        np.savez(path, t=t, P=np.column_stack((meter, reference)),
                 control_P_online=components,
                 control_P_revised=components if revised is None else revised,
                 I=np.full((len(t), 19), -999999), valid=np.zeros(len(t), bool),
                 evaluator_appliance_names=np.array(["secret reference label"]))
        self.store._cache.clear()
        return block

    def summary(self, block=17422, home="R1Hz", **args):
        return self.tools.call("get_window_summary", {"block_id": block, **args}, home)

    def test_interval_completion_prevents_partial_future_mean(self):
        self.fixture([T, T + 1, T + 2], [3600, 7200, 10800], [1800, 3600, 5400])
        result = self.summary(start=T, end=T + 2, as_of=T + 1.9)
        self.assertAlmostEqual(result["energy_kwh"], .001)
        self.assertEqual(result["coverage_fraction"], .5)
        self.assertEqual(result["latest_availability"], iso_time(T + 1))
        self.assertEqual(result["component_available_at"], iso_time(T))
        self.assertEqual(result["coverage"]["not_yet_available_seconds"], 1)
        empty = self.summary(start=T, end=T + .5, as_of=T + .5)
        self.assertIsNone(empty["energy_kwh"])
        self.assertEqual(empty["coverage_fraction"], 0)

    def test_clipped_integration_waits_for_full_native_mean(self):
        block = self.fixture([T, T + 60], [3600, 7200], [1800, 3600], recording="AMPds2")
        before = self.summary(block, "AMPds2", start=T + 30, end=T + 90, as_of=T + 90)
        after = self.summary(block, "AMPds2", start=T + 30, end=T + 90, as_of=T + 120)
        self.assertAlmostEqual(before["energy_kwh"], .03)
        self.assertAlmostEqual(after["energy_kwh"], .09)
        self.assertAlmostEqual(after["average_power_w"], 5400)
        self.assertEqual(before["coverage_fraction"], .5)
        self.assertEqual(after["coverage_fraction"], 1)

    def test_native_online_vector_is_preserved_without_backdating(self):
        self.fixture(range(T, T + 10), [100] * 10, [0] * 5 + [100] * 5)
        first = self.summary(start=T, end=T + 5, as_of=T + 5)
        second = self.summary(start=T + 5, end=T + 10, as_of=T + 10)
        self.assertEqual(first["component_energy_kwh"]["component_000"], 0)
        self.assertAlmostEqual(second["component_energy_kwh"]["component_000"], 500 / 3.6e6)
        np.testing.assert_array_equal(self.store.load("R1Hz", 17422).t, np.arange(T, T + 10))

    def test_revised_estimates_are_a_separate_post_block_view(self):
        revised = np.zeros((3, 24))
        revised[:, 0] = 500
        self.fixture([T, T + 1, T + 2], [1000] * 3, [100] * 3, revised=revised)
        with self.assertRaisesRegex(ValueError, "after the UTC block"):
            self.summary(start=T, end=T + 1, as_of=T + 2, mode="revised")
        after = self.summary(start=T, end=T + 1, as_of=T + 3, mode="revised")
        self.assertAlmostEqual(after["component_energy_kwh"]["component_000"], 500 / 3.6e6)
        self.assertEqual(after["revised_available_at"], iso_time(T + 3))
        self.assertEqual(after["measurement_available_at"], iso_time(T + 1))
        self.assertEqual(after["latest_availability"], iso_time(T + 3))
        self.assertEqual(self.store.load("R1Hz", 17422).mode, "online")

    def test_reference_arrays_and_joint_valid_never_enter_evidence(self):
        self.fixture([T, T + 1], [1000, 2000], [500, 1000])
        dataset = self.store.load("R1Hz", 17422)
        self.assertEqual(set(vars(dataset)), {"recording", "block_id", "mode", "t", "aggregate_w", "components_w", "content_hash", "model_version", "synthetic_fixture"})
        self.assertEqual(dataset.aggregate_w.shape, (2,))
        self.assertFalse(dataset.aggregate_w.flags.writeable)
        result = self.summary()
        self.assertEqual(result["coverage_fraction"], 1)
        encoded = json.dumps(result, allow_nan=False)
        self.assertNotIn("secret reference", encoded)
        self.assertNotIn("evaluator_appliance_names", encoded)
        self.assertTrue(all(v == "unknown" for v in result["label_status"].values()))

    def test_gap_invalid_meter_and_invalid_component_have_distinct_coverage(self):
        components = np.zeros((3, 24))
        components[:, 0] = 1000
        components[2, 23] = np.nan
        self.fixture([T, T + 2, T + 3], [3600, np.nan, 7200], components=components)
        result = self.summary(start=T - 1, end=T + 5, as_of=T + 5)
        c = result["coverage"]
        self.assertEqual(c["outside_block_seconds"], 2)
        self.assertEqual(c["absent_interval_seconds"], 1)
        self.assertEqual(c["missing_meter_seconds"], 1)
        self.assertEqual(c["invalid_component_seconds"], 1)
        self.assertEqual(c["valid_meter_seconds"], 2)
        self.assertEqual(c["valid_component_seconds"], 1)
        self.assertAlmostEqual(result["energy_kwh"], .003)
        self.assertAlmostEqual(result["component_energy_kwh"]["component_000"], 1000 / 3.6e6)
        feature = self.tools.call("get_component_features", {"block_id": 17422, "component_id": 0, "start": T - 1, "end": T + 5}, "R1Hz")
        self.assertAlmostEqual(feature["coverage_fraction"], 1 / 6)
        self.assertAlmostEqual(feature["average_power_w"], 1000)

    def test_residual_is_signed_and_overallocation_is_not_hidden(self):
        self.fixture([T, T + 1, T + 2], [1000] * 3, [1500, 500, 1000])
        result = self.summary()
        self.assertAlmostEqual(result["signed_residual_energy_kwh"], 0)
        self.assertAlmostEqual(result["unexplained_energy_kwh"], 500 / 3.6e6)
        self.assertAlmostEqual(result["overallocated_energy_kwh"], 500 / 3.6e6)
        self.assertEqual(result["overallocated_seconds"], 1)
        self.assertTrue(any("exceed" in n for n in result["notes"]))

    def test_positive_spans_do_not_bridge_a_missing_second(self):
        self.fixture([T, T + 2], [1000, 1000], [500, 500])
        result = self.tools.call("get_component_features", {"block_id": 17422, "component_id": "component_000"}, "R1Hz")
        self.assertEqual(result["observed_positive_span_count"], 2)
        self.assertEqual(result["active_seconds"], 2)
        self.assertTrue(all(s["left_censored"] and s["right_censored"] for s in result["observed_positive_spans"]))
        self.assertEqual(result["metric_sources"]["energy_kwh"], "nilm_estimate")

    def test_comparison_inherits_block_and_is_b_minus_a(self):
        self.fixture([T, T + 1, T + 2, T + 3], [1000, 1000, 2000, 2000])
        args = {"block_id": 17422, "period_a": {"start": T, "end": T + 2}, "period_b": {"start": T + 2, "end": T + 4}}
        result = self.tools.call("compare_periods", args, "R1Hz")
        self.assertAlmostEqual(result["difference_kwh"], 2000 / 3.6e6)
        self.assertAlmostEqual(result["difference_percent"], 100)
        self.assertTrue(result["comparable_complete_equal_duration"])
        self.assertNotEqual(result["evidence_id"], result["period_a"]["evidence_id"])
        args["period_b"]["end"] = T + 3
        self.assertFalse(self.tools.call("compare_periods", args, "R1Hz")["comparable_complete_equal_duration"])

    def test_zero_baseline_and_no_observations_return_json_null(self):
        self.fixture([T, T + 1], [0, 1000])
        result = self.tools.call("compare_periods", {"block_id": 17422, "period_a": {"start": T, "end": T + 1}, "period_b": {"start": T + 1, "end": T + 2}}, "R1Hz")
        self.assertIsNone(result["difference_percent"])
        no_data = self.summary(start=T + 4, end=T + 5)
        self.assertIsNone(no_data["energy_kwh"])
        self.assertIsNone(no_data["peak_power_w"])
        json.dumps(no_data, allow_nan=False)

    def test_cost_is_explicitly_illustrative_and_optional(self):
        self.fixture([T], [3600])
        self.assertFalse(self.summary()["cost"]["available"])
        priced = EnergyTools(self.store, flat_rate_cad_per_kwh=.12).call("get_window_summary", {"block_id": 17422}, "R1Hz")
        self.assertAlmostEqual(priced["cost"]["amount"], .00012)
        self.assertTrue(priced["cost"]["illustrative"])
        with self.assertRaises(ValueError):
            EnergyTools(self.store, flat_rate_cad_per_kwh=float("nan"))

    def test_home_scope_and_nested_scope_are_enforced(self):
        self.fixture([T], [100])
        for args in ({"block_id": 17422, "home_id": "AMPds2"}, {"block_id": 15431}, {"block_id": "../17422"}, {"block_id": 17422, "path": "/etc/passwd"}):
            with self.assertRaises(ValueError):
                self.tools.call("get_window_summary", args, "R1Hz")
        with self.assertRaises(ValueError):
            self.tools.call("compare_periods", {"block_id": 17422, "period_a": {"home_id": "AMPds2"}, "period_b": {}}, "R1Hz")
        with self.assertRaises(ValueError):
            self.tools.call("arbitrary_function", {}, "R1Hz")
        with self.assertRaises(ValueError):
            self.tools.call("get_label", {"component_id": 24}, "R1Hz")

    def test_time_requires_finite_unambiguous_instants(self):
        self.assertEqual(parse_time("2017-07-14T19:40:00-07:00"), parse_time("2017-07-15T02:40:00Z"))
        for bad in (True, float("nan"), float("inf"), 1e300, "2017-07-14T19:40:00", "not a timestamp"):
            with self.assertRaises(ValueError):
                parse_time(bad)
        self.fixture([T], [100])
        with self.assertRaises(ValueError):
            self.summary(start=T + 1, end=T)

    def test_overlapping_native_intervals_are_rejected(self):
        self.fixture([T, T], [100, 100])
        with self.assertRaisesRegex(ValueError, "overlapping"):
            self.store.load("R1Hz", 17422)

    def test_labels_keep_availability_home_and_model_version_separate(self):
        self.labels.propose("R1Hz", 0, "Possible refrigerator", source="prototype_operator", evidence="Operator suggestion", alternatives=["freezer"], available_at=T + 10)
        self.assertEqual(self.labels.get("R1Hz", 0, as_of=T + 9)["status"], "unknown")
        candidate = self.labels.get("R1Hz", 0, as_of=T + 10)
        self.assertEqual(candidate["status"], "candidate")
        self.assertFalse(candidate["definitive_identity"])
        confirmed = self.labels.confirm("R1Hz", 0, "Refrigerator", evidence="Occupant identified the cycling load", available_at=T + 20)
        self.assertEqual(confirmed["status"], "occupant-confirmed")
        self.assertFalse(confirmed["definitive_identity"])
        self.assertEqual(self.labels.get("R1Hz", 0, as_of=T + 19)["status"], "candidate")
        self.assertEqual(self.labels.get("AMPds2", 0)["status"], "unknown")
        self.assertEqual(self.labels.get("R1Hz", 0, model_version="new_model")["status"], "unknown")
        confirmed["label"] = "mutated"
        self.assertEqual(self.labels.get("R1Hz", 0)["label"], "Refrigerator")

    def test_definitive_identity_requires_independent_verification(self):
        with self.assertRaisesRegex(ValueError, "unverified"):
            self.labels.set_label("R1Hz", 0, "Refrigerator", source="operator", evidence="guess", definitive=True)
        with self.assertRaisesRegex(ValueError, "independent_verification"):
            self.labels.set_label("R1Hz", 0, "Refrigerator", status="verified", source="occupant", evidence="confirmation")
        with self.assertRaisesRegex(ValueError, "occupant source"):
            self.labels.set_label("R1Hz", 0, "Refrigerator", status="occupant-confirmed", source="prototype_operator", evidence="operator guess")
        verified = self.labels.set_label("R1Hz", 0, "Refrigerator", status="verified", source={"kind": "independent_verification", "method": "independent measurement"}, evidence={"record": "verification-test"}, available_at=T)
        self.assertTrue(verified["definitive_identity"])
        with self.assertRaisesRegex(ValueError, "finite JSON"):
            self.labels.propose("R1Hz", 1, "candidate", source="operator", evidence={"confidence": float("nan")})

    def test_persisted_labels_are_private_and_history_survives_reload(self):
        path = self.root / "runtime" / "labels.json"
        registry = LabelRegistry(path)
        registry.propose("R1Hz", 1, "candidate", source="operator", evidence="suggestion", available_at=T)
        registry.confirm("R1Hz", 1, "occupant name", evidence="explicit occupant response", available_at=T + 1)
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        restored = LabelRegistry(path)
        self.assertEqual(restored.get("R1Hz", 1, as_of=T)["status"], "candidate")
        self.assertEqual(restored.get("R1Hz", 1, as_of=T + 1)["status"], "occupant-confirmed")


class FrozenReplaySmokeTests(unittest.TestCase):
    def test_real_first_blocks_are_native_partial_days_and_json_safe(self):
        source_root = os.environ.get("WATTDIALOGUE_ARCHIVE_ROOT")
        if not source_root:
            self.skipTest("Private archive checks require explicit WATTDIALOGUE_ARCHIVE_ROOT opt-in")
        store = ReplayStore(source_root)
        tools = EnergyTools(store)
        for recording, block, cadence, rows in (("R1Hz", 17422, 1, 61200), ("AMPds2", 15431, 60, 1020)):
            data = store.load(recording, block)
            metadata = data.metadata()
            self.assertEqual(len(data.t), rows)
            self.assertEqual(metadata["end_unix"] - metadata["start_unix"], 17 * 3600)
            self.assertEqual(data.cadence_s, cadence)
            self.assertFalse(metadata["component_capacity_is_appliance_count"])
            self.assertEqual(metadata["model_version"], MODEL_VERSION)
            result = tools.call("get_window_summary", {"block_id": block}, recording)
            self.assertEqual(result["coverage_fraction"], 1)
            self.assertGreater(result["energy_kwh"], 0)
            self.assertEqual(len(result["component_energy_kwh"]), 24)
            self.assertTrue(result["evidence_id"].startswith("wd_"))
            json.dumps(result, allow_nan=False)


if __name__ == "__main__":
    unittest.main()
