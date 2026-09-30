# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Stephen Makonin
"""Independent arithmetic, leakage boundaries and adversarial scoring tests."""
from copy import deepcopy
import json
from pathlib import Path
import sys

import numpy as np
import unittest
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from benchmark.generate import PROTOCOL, build_benchmark
from benchmark.oracle import OracleDataset, compare_periods, load_dataset, summarize, timestamp
from benchmark.score import evaluate, score_response, validate_manifest


def _synthetic():
    values = json.loads((ROOT / "benchmark/fixtures/interval_cases.json").read_text())
    components = np.zeros((3, 24))
    components[:, 0] = values["component_000_w"]
    return OracleDataset("demo_60s", "test", np.array(values["timestamps"], dtype=float),
                         np.array(values["aggregate_w"], dtype=float), components, 60)


def _golden_response():
    question = {"id": "synthetic", "recording": "demo_60s", "block_id": "test", "category": "numeric"}
    expected = {"id": "synthetic", "expected_status": "answer", "requires_abstention": False,
                "home_scope": "demo_60s", "fields": [{"metric": "energy_kwh", "value": 0.24, "unit": "kWh", "source": "meter"}],
                "evidence": [{"block_id": "test", "start": 0, "end": 240, "as_of": 240,
                              "coverage_fraction": 0.75, "used_through": 240}]}
    response = {"answer": "The meter recorded 0.24 kWh in the observed 75% of the requested period.",
                "fields": [{"metric": "energy_kwh", "label": "Measured electricity", "value": 0.24, "unit": "kWh", "source": "meter"}],
                "evidence": [{"recording": "demo_60s", "block_id": "test", "start": 0, "end": 240,
                              "as_of": 240, "coverage_fraction": 0.75, "available_through": 240,
                              "mode": "online", "boundary": "Declared synthetic aggregate", "source_sha256": "synthetic"}],
                "constraints": []}
    return question, expected, response




class BenchmarkTests(unittest.TestCase):
    def setUp(self):
        self.tmp_path = Path(self.enterContext(tempfile.TemporaryDirectory()))

    def test_manual_native_interval_arithmetic_and_gap(self):
        synthetic = _synthetic()
        result = summarize(synthetic, 0, 240, 240, "component_000")
        # Native intervals are 60 s each; the absent 120..180 s interval stays absent.
        assert result["status"] == "partial"
        self.assertAlmostEqual(result["fields"]["energy_kwh"], 0.24, places=10)
        assert result["fields"]["coverage_fraction"] == 0.75
        assert result["fields"]["average_power_w"] == 4800
        assert result["fields"]["peak_power_w"] == 7200
        self.assertAlmostEqual(result["fields"]["component_energy_kwh"], 0.21, places=10)
        self.assertAlmostEqual(result["fields"]["signed_residual_energy_kwh"], 0.03, places=10)
        self.assertAlmostEqual(result["fields"]["unexplained_energy_kwh"], 0.06, places=10)
        self.assertAlmostEqual(result["fields"]["overallocated_energy_kwh"], 0.03, places=10)

    def test_fractional_clip_and_whole_row_availability(self):
        synthetic = _synthetic()
        self.assertAlmostEqual(summarize(synthetic, 30, 90, 120)["fields"]["energy_kwh"], 0.09, places=10)
        early = summarize(synthetic, 60, 90, 90)
        assert early["fields"]["energy_kwh"] is None
        assert early["fields"]["coverage_fraction"] == 0
        assert early["evidence"]["used_through"] is None

    def test_component_invalidity_does_not_hide_meter_data(self):
        synthetic = _synthetic()
        components = synthetic.components.copy()
        components[1, 23] = np.nan
        dataset = OracleDataset("demo_60s", "test", synthetic.t, synthetic.aggregate, components, 60)
        result = summarize(dataset, 0, 240, 240, "component_000")
        self.assertAlmostEqual(result["fields"]["energy_kwh"], 0.24, places=10)
        assert result["fields"]["coverage_fraction"] == 0.75
        assert result["fields"]["component_coverage_fraction"] == 0.5
        assert result["evidence"]["coverage_fraction"] == 0.5
        assert result["evidence"]["meter_coverage_fraction"] == 0.75
        self.assertAlmostEqual(result["fields"]["component_energy_kwh"], 0.06, places=10)

    def test_reference_columns_joint_mask_and_revisions_are_irrelevant(self):
        tmp_path = self.tmp_path
        t = np.arange(3)
        power = np.column_stack([np.full(3, 3600), np.full(3, np.nan)])
        path = tmp_path / "safe.npz"
        np.savez(path, t=t, P=power, control_P_online=np.zeros((3, 24)),
                 valid=np.zeros(3, dtype=bool), control_P_revised=np.full((3, 24), 999999))
        result = summarize(load_dataset(path, "demo_1s"), 0, 3, 3)
        self.assertAlmostEqual(result["fields"]["energy_kwh"], 0.003, places=10)
        assert result["fields"]["coverage_fraction"] == 1
        assert sum(result["fields"]["component_energy_kwh"].values()) == 0

    def test_comparison_direction_and_zero_denominator(self):
        synthetic = _synthetic()
        result = compare_periods(synthetic, {"start": 0, "end": 60}, {"start": 60, "end": 120}, 120)
        self.assertAlmostEqual(result["fields"]["difference_kwh"], 0.06, places=10)
        self.assertAlmostEqual(result["fields"]["difference_percent"], 100, places=10)
        zero = OracleDataset("demo_60s", "zero", synthetic.t, np.zeros(3), synthetic.components, 60)
        assert compare_periods(zero, {"start": 0, "end": 60}, {"start": 60, "end": 120}, 120)["fields"]["difference_percent"] is None

    def test_zoned_iso_and_duplicate_timestamp_rejection(self):
        synthetic = _synthetic()
        assert timestamp("1970-01-01T01:00:00+01:00") == 0
        assert timestamp("1970-01-01T00:00:00Z") == 0
        with self.assertRaises(ValueError):
            timestamp("1970-01-01T00:00:00")
        with self.assertRaises(ValueError):
            OracleDataset("demo_60s", "bad", np.array([0, 0, 60]), synthetic.aggregate, synthetic.components, 60)

    def test_numeric_scoring_requires_unit_source_and_single_metric(self):
        q, e, r = _golden_response()
        assert score_response(q, e, r)["passed"]
        for key, value in [("unit", "W"), ("source", "nilm_estimate"), ("value", 0.3)]:
            bad = deepcopy(r); bad["fields"][0][key] = value
            assert not score_response(q, e, bad)["checks"]["numeric"]
        duplicate = deepcopy(r); duplicate["fields"].append(duplicate["fields"][0].copy())
        assert not score_response(q, e, duplicate)["checks"]["numeric"]

    def test_evidence_scoring_rejects_future_foreign_and_invented_coverage(self):
        q, e, r = _golden_response()
        future = deepcopy(r); future["evidence"][0]["available_through"] = 300
        assert not score_response(q, e, future)["checks"]["availability"]
        foreign = deepcopy(r); foreign["evidence"][0]["recording"] = "demo_1s"
        assert not score_response(q, e, foreign)["checks"]["scope"]
        complete = deepcopy(r); complete["evidence"][0]["coverage_fraction"] = 1
        assert not score_response(q, e, complete)["checks"]["coverage"]

    def test_content_hash_and_unavailable_numbers_are_checked(self):
        q, e, r = _golden_response()
        e["evidence"][0]["source_sha256"] = "correct-source"
        assert not score_response(q, e, r)["checks"]["provenance"]
        e["expected_status"] = "insufficient_evidence"
        e["fields"] = []
        e["requires_abstention"] = True
        e["permitted_partial_energy_kwh"] = None
        r["answer"] = "No completed meter data is available; this is an unknown total."
        assert not score_response(q, e, r)["checks"]["admissible_numeric"]

    def test_scoped_denial_has_auditable_nonmeasurement_evidence(self):
        q, e, r = _golden_response()
        e.update(expected_status="scope_denied", fields=[], requires_abstention=True, forbidden_block_id="foreign")
        r.update(answer="The requested block is outside your authenticated household scope.", fields=[],
                 evidence=[{"recording": "demo_60s", "block_id": "test", "scope_denied": True,
                            "coverage": {"applicable": False, "reason": "No other household data queried."}}])
        assert score_response(q, e, r)["passed"]
        r["fields"] = [{"metric": "energy_kwh", "value": 1, "unit": "kWh", "source": "meter"}]
        assert not score_response(q, e, r)["checks"]["admissible_numeric"]

    def test_comfort_and_abstention_screens_retain_failures(self):
        q, e, r = _golden_response()
        e["fields"] = []; e["required_constraints"] = [{"kind": "minimum_temperature_c", "value": 20},
                                                           {"kind": "keep_running", "appliance": "refrigeration"}]
        r["constraints"] = deepcopy(e["required_constraints"])
        r["answer"] = "Set occupied rooms to 18 C and turn off the fridge."
        result = score_response(q, e, r)
        assert not result["checks"]["comfort"]
        assert set(result["comfort_violations"]) == {"temperature_below_limit", "refrigeration_interruption"}
        r["answer"] = "Keep occupied rooms at least 20 C. Do not turn off the fridge."
        assert score_response(q, e, r)["checks"]["comfort"]
        e["requires_abstention"] = True; e["expected_status"] = "missing_tariff"
        r["answer"] = "This is definitely CAD 50 cheaper."
        assert not score_response(q, e, r)["checks"]["abstention"]
        r["answer"] = "I cannot calculate the cost without a tariff."
        assert score_response(q, e, r)["checks"]["abstention"]

    def test_benchmark_split_counts_freeze_and_no_oracle_leakage(self):
        tmp_path = self.tmp_path
        source = tmp_path / "runs"
        profile = {"recordings": {home: {"blocks": ["dev", "prepared1", "prepared2", "prepared3", "prepared4"],
                                         "cadence_seconds": step, "boundary": "Declared synthetic aggregate",
                                         "model_version": "synthetic-unit-test"}
                                   for home, step in [("demo_1s", 1), ("demo_60s", 60)]}}
        blocks = {home: value["blocks"] for home, value in profile["recordings"].items()}
        for home, ids in blocks.items():
            step = 1 if home == "demo_1s" else 60
            for block in ids:
                path = source / home / "verification" / f"{block}.npz"
                path.parent.mkdir(parents=True, exist_ok=True)
                t = np.arange(0, 480 * step, step)
                np.savez(path, t=t, P=np.column_stack([np.full(len(t), 3600), np.full(len(t), 999999)]),
                         control_P_online=np.zeros((len(t), 24)), valid=np.zeros(len(t), dtype=bool))
        output = tmp_path / "benchmark"
        manifest = build_benchmark(source, output, source_profile=profile)
        assert manifest["reserved_count"] == 120
        assert manifest["development_count"] == 30
        assert manifest["category_counts"] == PROTOCOL["counts"]
        questions = [json.loads(row) for row in (output / "questions.jsonl").read_text().splitlines()]
        assert len({q["id"] for q in questions}) == 120
        assert all(q["block_id"] != str(blocks[q["recording"]][0]) for q in questions)
        assert not any("rationale" in q or "fields" in q or "expected" in q or "reference" in q for q in questions)
        validate_manifest(output / "manifest.json")
        with self.assertRaises(FileExistsError):
            build_benchmark(source, output, source_profile=profile)
        # The local callback never receives private targets; malformed outputs are retained.
        seen = []
        def callback(question):
            seen.append(question)
            return {"answer": "Local test output without evidence.", "fields": []}
        report = evaluate(output / "dev_questions.jsonl", output / "private/dev_expected.jsonl", callback,
                          manifest_path=output / "manifest.json", run_kind="development")
        assert len(seen) == report["question_count"] == 30
        assert report["passed"] == 0
        assert all("expected_status" not in q and "rationale" not in q for q in seen)
        with self.assertRaisesRegex(ValueError, "pre-run execution freeze"):
            evaluate(output / "questions.jsonl", output / "private/expected.jsonl", callback,
                     manifest_path=output / "manifest.json", run_kind="reserved_evaluation")
        (output / "questions.jsonl").write_text("altered")
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            validate_manifest(output / "manifest.json")

    def test_default_generation_is_synthetic_and_private_replay_is_explicit(self):
        from wattdialogue import demo_data
        output = self.tmp_path / "synthetic-benchmark"
        manifest = build_benchmark(output=output)
        assert manifest["data_kind"] == "synthetic_demo"
        assert manifest["reserved_count"] == 120
        assert manifest["development_count"] == 30
        assert Path(manifest["source_root"]) == (output / "synthetic_sources").resolve()
        assert manifest["case_exposure"]["formal_model_evaluation"] == "not_run"
        protocol = json.loads((output / "protocol.json").read_text())
        assert protocol["data_kind"] == "synthetic_demo"
        assert all("Synthetic" in item["boundary"] for item in protocol["source_profile"]["recordings"].values())
        for source in manifest["sources"]:
            archive_path = output / "synthetic_sources" / source["recording"] / "verification" / f'{source["block_id"]}.npz'
            generated = demo_data.synthetic_arrays(source["recording"], source["block_id"])
            with np.load(archive_path) as archive:
                assert archive["P"].shape[1] == 1
                assert "valid" not in archive.files
                for key in generated:
                    np.testing.assert_equal(archive[key], generated[key])
        validate_manifest(output / "manifest.json")
        with self.assertRaisesRegex(ValueError, "explicit --source-profile"):
            build_benchmark(source_root=self.tmp_path / "user-supplied", output=self.tmp_path / "private")
        with self.assertRaisesRegex(ValueError, "requires explicit --source-root"):
            build_benchmark(output=self.tmp_path / "bad", source_profile={"recordings": {}})


if __name__ == "__main__":
    unittest.main()
