# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Stephen Makonin
"""Portable synthetic source, provenance and interval-quality checks."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from wattdialogue.adapter import MODEL_VERSION as ARCHIVE_VERSION, ReplayStore
from wattdialogue.demo_data import BLOCKS, CADENCE_S, DURATION_S, MODEL_VERSION, synthetic_arrays, write_demo_npz
from wattdialogue.labels import LabelRegistry
from wattdialogue.tools import EnergyTools


class SyntheticDemoTests(unittest.TestCase):
    def test_default_launch_never_opens_an_archive(self):
        with patch("wattdialogue.adapter.np.load", side_effect=AssertionError("No archive should be opened")):
            store = ReplayStore()
            self.assertIsNone(store.root)
            metadata = store.source_metadata()
            self.assertTrue(metadata["synthetic_fixture"])
            self.assertEqual(metadata["input_kind"], "synthetic")
            self.assertEqual(metadata["model_version"], MODEL_VERSION)
            for home, blocks in store.list_blocks().items():
                for block in blocks:
                    data = store.load(home, block)
                    result = EnergyTools(store).call("get_window_summary", {"block_id": block}, home)
                    self.assertEqual(result["model_version"], MODEL_VERSION)
                    self.assertTrue(result["synthetic_fixture"])
                    self.assertEqual(result["input_kind"], "synthetic")
                    self.assertIn("Synthetic home", result["boundary"])
                    self.assertIn("2025-", data.metadata()["start"])
                    self.assertEqual(data.block_end - data.block_start, DURATION_S)

    def test_generator_is_deterministic_and_contains_only_allowed_channels(self):
        for home, blocks in BLOCKS.items():
            first = synthetic_arrays(home, blocks[0])
            second = synthetic_arrays(home, blocks[0])
            self.assertEqual(set(first), {"t", "P", "control_P_online", "control_P_revised"})
            self.assertEqual(first["P"].shape[1], 1)
            self.assertEqual(first["control_P_online"].shape[1], 24)
            for key in first:
                np.testing.assert_array_equal(first[key], second[key])
            a = ReplayStore().load(home, blocks[0])
            b = ReplayStore().load(home, blocks[0])
            self.assertEqual(a.content_hash, b.content_hash)

    def test_deliberate_quality_examples_are_not_imputed(self):
        store = ReplayStore()
        for home, blocks in BLOCKS.items():
            data = store.load(home, blocks[0])
            summary = EnergyTools(store).call("get_window_summary", {"block_id": blocks[0]}, home)
            cadence = CADENCE_S[home]
            coverage = summary["coverage"]
            self.assertEqual(coverage["outside_block_seconds"], 0)
            self.assertEqual(coverage["absent_interval_seconds"], cadence)
            self.assertEqual(coverage["missing_meter_seconds"], cadence)
            self.assertEqual(coverage["invalid_component_seconds"], cadence)
            self.assertEqual(coverage["valid_meter_seconds"], DURATION_S - 2 * cadence)
            self.assertEqual(coverage["valid_component_seconds"], DURATION_S - 3 * cadence)
            meter = np.isfinite(data.aggregate_w)
            self.assertAlmostEqual(summary["energy_kwh"], float(data.aggregate_w[meter].sum() * cadence / 3.6e6))
            self.assertGreater(summary["overallocated_energy_kwh"], 0)
            self.assertFalse(coverage["complete"])

    def test_demo_identity_version_isolated_from_archive_annotations(self):
        store = ReplayStore()
        home = next(iter(BLOCKS))
        block = BLOCKS[home][0]
        data = store.load(home, block)
        registry = LabelRegistry()
        registry.confirm(home, 0, "Demo occupant annotation", evidence="Synthetic operator simulation", model_version=MODEL_VERSION, available_at=data.block_start)
        tools = EnergyTools(store, registry)
        feature = tools.call("get_component_features", {"block_id": block, "component_id": 0}, home)
        annotation = tools.call("get_label", {"block_id": block, "component_id": 0}, home)
        summary = tools.call("get_window_summary", {"block_id": block}, home)
        comparison = tools.call("compare_periods", {"block_id": block, "period_a": {"start": data.block_start, "end": data.block_start + 3600}, "period_b": {"start": data.block_start + 3600, "end": data.block_start + 7200}}, home)
        for result in (feature, annotation, summary, comparison):
            self.assertEqual(result["model_version"], MODEL_VERSION)
            self.assertTrue(result["synthetic_fixture"])
        self.assertEqual(feature["label_status"], "occupant-confirmed")
        self.assertEqual(annotation["label_status"], "occupant-confirmed")
        self.assertEqual(summary["label_status"]["component_000"], "occupant-confirmed")
        self.assertEqual(registry.get(home, 0, model_version=ARCHIVE_VERSION)["status"], "unknown")

    def test_demo_revised_view_still_requires_block_completion(self):
        store = ReplayStore()
        home = next(iter(BLOCKS))
        block = BLOCKS[home][0]
        data = store.load(home, block)
        tools = EnergyTools(store)
        with self.assertRaises(ValueError):
            tools.call("get_window_summary", {"block_id": block, "mode": "revised", "as_of": data.block_end - 1}, home)
        result = tools.call("get_window_summary", {"block_id": block, "mode": "revised"}, home)
        self.assertTrue(result["synthetic_fixture"])
        self.assertEqual(result["latest_availability"], result["revised_available_at"])

    def test_exports_are_generated_npz_only_and_explicit_root_does_not_fallback(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            exported = write_demo_npz(root)
            self.assertEqual(exported, ReplayStore().list_blocks())
            for home, blocks in exported.items():
                for block in blocks:
                    with np.load(root / home / "verification" / f"{block}.npz", allow_pickle=False) as archive:
                        self.assertEqual(set(archive.files), {"t", "P", "control_P_online", "control_P_revised"})
                        self.assertEqual(archive["P"].shape[1], 1)
            explicit = ReplayStore(root)
            self.assertFalse(explicit.source_metadata()["synthetic_fixture"])
            self.assertEqual(explicit.source_metadata()["input_kind"], "archive_replay")
            home = next(iter(BLOCKS))
            np.testing.assert_array_equal(explicit.load(home, BLOCKS[home][0]).aggregate_w, ReplayStore().load(home, BLOCKS[home][0]).aggregate_w)
            with self.assertRaises(ValueError):
                ReplayStore(root / "missing").load(home, BLOCKS[home][0])


if __name__ == "__main__":
    unittest.main()
