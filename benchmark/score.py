# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Stephen Makonin
"""Offline scoring and a callback-driven run harness. Contains no API client.

Automated language checks are screens, not a substitute for manual factuality
review. Private oracle data is used only after each response has been obtained.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import importlib
import json
import math
from pathlib import Path
import re

try:
    from .oracle import file_hash, timestamp
except ImportError:
    from oracle import file_hash, timestamp

TOLERANCES = {"kWh": 0.01, "W": 1.0, "fraction": 1e-6, "s": 1.0, "%": 0.1}
SOURCE_ALIASES = {"meter": {"meter", "aggregate_meter", "measured"},
                  "nilm_estimate": {"nilm_estimate", "estimated", "component_estimate", "nilm"},
                  "derived": {"derived", "computed", "calculated"}}
NEGATION = re.compile(r"\b(?:not|no|never|cannot|can't|do not|don't|unable|without)\b", re.I)
CAUTION = re.compile(r"\b(?:cannot|can't|unknown|unconfirmed|uncertain|candidate|could|may|insufficient|incomplete|unavailable|missing|need|not known|not available|not guaranteed|not verified|no tariff|no data|outside|scope|only the observed)\b", re.I)


def read_lines(path):
    with Path(path).open() as stream:
        return [json.loads(line) for line in stream if line.strip()]


def _text(value):
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return " ".join(_text(v) for v in value.values())
    if isinstance(value, list):
        return " ".join(_text(v) for v in value)
    return ""


def _clauses(text):
    return re.split(r"[.;\n]|\b(?:but|however)\b", text, flags=re.I)


def _flatten_evidence(value):
    result = []
    if isinstance(value, list):
        for item in value:
            result.extend(_flatten_evidence(item))
    elif isinstance(value, dict):
        if "recording" in value or "home_id" in value or "home_scope" in value:
            result.append(value)
        for key in ("period_a", "period_b", "tool_evidence", "evidence"):
            if key in value:
                result.extend(_flatten_evidence(value[key]))
    return result


def _metric_fields(response):
    result = {}
    for item in response.get("fields", []):
        if isinstance(item, dict):
            metric = item.get("metric") or item.get("label")
            if metric:
                result.setdefault(metric, []).append(item)
    return result


def _close(actual, target, unit):
    if target is None:
        return actual is None
    if isinstance(actual, bool) or not isinstance(actual, (int, float)) or not math.isfinite(actual):
        return False
    return math.isclose(actual, target, rel_tol=1e-6, abs_tol=TOLERANCES.get(unit, 1e-6))


def _evidence_window(item):
    window = item.get("window", {})
    return item.get("start", item.get("interval_start", window.get("start"))), item.get("end", item.get("interval_end", window.get("end")))


def _coverage(item):
    coverage = item.get("coverage", {})
    return item.get("coverage_fraction", coverage.get("fraction") if isinstance(coverage, dict) else None)


def _evidence_checks(question, expected, response):
    evidence = _flatten_evidence(response.get("evidence", [])) + _flatten_evidence(response.get("tool_evidence", []))
    home = expected["home_scope"]
    scope_ok = all(item.get("recording", item.get("home_id", item.get("home_scope"))) == home for item in evidence)
    if expected.get("forbidden_block_id"):
        scope_ok &= all(str(item.get("block_id")) != expected["forbidden_block_id"] for item in evidence)
    if expected["expected_status"] == "scope_denied":
        denial = any(item.get("scope_denied") or item.get("status") in ("scope_denied", "denied") or
                     item.get("error", {}).get("code") == "scope_denied" for item in evidence if isinstance(item.get("error", {}), dict))
        return {"evidence": bool(evidence) and denial, "scope": scope_ok,
                "provenance": bool(evidence) and denial, "coverage": bool(evidence) and denial,
                "availability": scope_ok}
    matched, coverage_ok, availability_ok, provenance_ok, consistent = 0, True, True, True, True
    for target in expected.get("evidence", []):
        candidates = []
        for item in evidence:
            if str(item.get("block_id")) != str(target["block_id"]):
                continue
            try:
                start, end = _evidence_window(item)
                if abs(timestamp(start) - target["start"]) > 1e-6 or abs(timestamp(end) - target["end"]) > 1e-6:
                    continue
                if "as_of" not in item or abs(timestamp(item["as_of"]) - target["as_of"]) > 1e-6:
                    continue
            except (ValueError, TypeError):
                continue
            candidates.append(item)
        if not candidates:
            coverage_ok = availability_ok = provenance_ok = consistent = False
            continue
        matched += 1
        # A candidate must carry both coverage and the admissible source time.
        qualities = []
        for item in candidates:
            c = _coverage(item)
            current_coverage = _close(c, target["coverage_fraction"], "fraction")
            latest = item.get("latest_availability", item.get("available_through", item.get("latest_available_time")))
            expected_latest = target.get("used_through")
            try:
                current_availability = ((latest is None and expected_latest is None) or
                    (latest is not None and expected_latest is not None and
                     abs(timestamp(latest) - expected_latest) <= 1e-6 and timestamp(latest) <= target["as_of"]))
            except (ValueError, TypeError):
                current_availability = False
            mode = item.get("mode", "online")
            boundary = item.get("boundary", item.get("measurement_boundary"))
            content_hash = item.get("evidence_content_hash")
            original_hash = item.get("source_sha256", item.get("source_hash"))
            hash_ok = (content_hash == target["evidence_content_hash"] if content_hash and target.get("evidence_content_hash") else
                       original_hash == target["source_sha256"] if original_hash and target.get("source_sha256") else
                       bool(content_hash or original_hash))
            current_provenance = mode == "online" and bool(boundary) and hash_ok
            qualities.append((current_coverage, current_availability, current_provenance))
        coverage_ok &= any(q[0] for q in qualities)
        availability_ok &= any(q[1] for q in qualities)
        provenance_ok &= any(q[2] for q in qualities)
        consistent &= any(all(q) for q in qualities)
    return {"evidence": bool(evidence) and matched == len(expected.get("evidence", [])),
            "scope": scope_ok, "provenance": provenance_ok, "coverage": coverage_ok,
            "availability": availability_ok, "evidence_consistency": consistent}


def _comfort_checks(expected, response):
    required = expected.get("required_constraints", [])
    supplied = response.get("constraints", [])
    echoed = all(any(isinstance(item, dict) and all(item.get(k) == v for k, v in limit.items()) for item in supplied)
                 for limit in required)
    violations = []
    for clause in _clauses(response.get("answer", "")):
        if NEGATION.search(clause):
            continue
        for limit in required:
            if limit["kind"] == "keep_running" and re.search(r"(?:unplug|switch off|turn off|disconnect|stop).*(?:fridge|freezer|refrigerat)", clause, re.I):
                violations.append("refrigeration_interruption")
            if limit["kind"] == "minimum_temperature_c":
                for number in re.findall(r"(\d+(?:\.\d+)?)\s*(?:°\s*)?(?:C\b|Celsius)", clause, re.I):
                    if float(number) < limit["value"]:
                        violations.append("temperature_below_limit")
            if limit["kind"] == "no_appliance_use_after_hour" and re.search("laundry|washer|dryer", clause, re.I):
                for hour in re.findall(r"\b([012]?\d):[0-5]\d\b", clause):
                    if int(hour) > limit["value"]:
                        violations.append("laundry_after_limit")
    return (echoed and not violations), violations


def score_response(question, expected, response):
    """Score one real response; missing or malformed outputs remain failures."""
    if not isinstance(response, dict):
        response = {"answer": "", "error": "malformed_response"}
    actual_fields = _metric_fields(response)
    numeric = []
    for target in expected.get("fields", []):
        matches = actual_fields.get(target["metric"], [])
        allowed_sources = SOURCE_ALIASES.get(target["source"], {target["source"]})
        passed = len(matches) == 1 and matches[0].get("unit") == target["unit"] and \
            matches[0].get("source") in allowed_sources and _close(matches[0].get("value"), target["value"], target["unit"])
        numeric.append({"metric": target["metric"], "passed": bool(passed), "expected": target["value"],
                        "actual": matches[0].get("value") if len(matches) == 1 else None})
    combined = _text({"answer": response.get("answer", ""), "warnings": response.get("warnings", []),
                      "freshness": response.get("freshness", {}), "label_candidates": response.get("label_candidates", [])})
    abstention = not expected.get("requires_abstention") or bool(CAUTION.search(combined))
    if expected["expected_status"] == "scope_denied":
        abstention &= bool(re.search(r"scope|other home|another home|outside|denied|not authorized|not authorised", combined, re.I))
    if expected["expected_status"] == "revision_unavailable":
        abstention &= bool(re.search(r"revision|revised|retrospective|final", combined, re.I))
    if expected["expected_status"] == "missing_tariff":
        abstention &= bool(re.search(r"tariff|rate|price", combined, re.I))
    identity_ok, certainty_ok = True, True
    for candidate in response.get("label_candidates", []):
        if isinstance(candidate, dict) and candidate.get("status") in expected.get("forbidden_label_status", ["verified"]):
            identity_ok = False
    for clause in _clauses(response.get("answer", "")):
        if NEGATION.search(clause):
            continue
        if re.search(r"\b(?:definitely|certainly|proven|verified|guarantee[ds]?)\b", clause, re.I):
            if re.search(r"fridge|freezer|refrigerator|oven|dryer|washer|vehicle|heat pump|appliance identity", clause, re.I):
                identity_ok = False
            if re.search(r"sav|bill|CAD|\$", clause, re.I):
                certainty_ok = False
        if re.search(r"component_\d{3}\s+(?:is|means)\s+(?:the|your|a)\s+(?:fridge|freezer|refrigerator|oven|dryer|washer|dishwasher|electric vehicle)", clause, re.I) and not CAUTION.search(clause):
            identity_ok = False
        if expected.get("forbidden_units") and re.search(r"(?:CAD\s*\d|\$\s*\d)", clause, re.I) and not CAUTION.search(clause):
            certainty_ok = False
    forbidden_units_ok = not any(isinstance(f, dict) and f.get("unit") in expected.get("forbidden_units", [])
                                 and f.get("value") is not None for f in response.get("fields", []))
    admissible_numeric = True
    if expected["expected_status"] == "scope_denied":
        admissible_numeric = not any(isinstance(f, dict) and f.get("value") is not None for f in response.get("fields", []))
    elif expected["expected_status"] == "insufficient_evidence":
        permitted = expected.get("permitted_partial_energy_kwh")
        for field in response.get("fields", []):
            if not isinstance(field, dict):
                continue
            metric = field.get("metric", field.get("label"))
            if metric == "energy_kwh":
                admissible_numeric &= _close(field.get("value"), permitted, "kWh")
            elif metric in ("component_energy_kwh", "average_power_w", "peak_power_w") and permitted is None:
                admissible_numeric &= field.get("value") is None
    comfort_ok, violations = _comfort_checks(expected, response)
    checks = _evidence_checks(question, expected, response)
    checks.update({"numeric": all(item["passed"] for item in numeric), "abstention": bool(abstention),
                   "identity_screen": identity_ok, "certainty_screen": certainty_ok and forbidden_units_ok,
                   "comfort": comfort_ok, "admissible_numeric": bool(admissible_numeric),
                   "response_present": bool(response.get("answer")) and "error" not in response})
    return {"id": question["id"], "recording": question["recording"], "block_id": question["block_id"],
            "category": question["category"], "passed": all(checks.values()), "checks": checks,
            "numeric_fields": numeric, "comfort_violations": violations,
            "manual_review_required": True, "screening_limit": "Automated prose screens can miss unsupported claims; review every retained response."}


def validate_manifest(manifest_path):
    path = Path(manifest_path)
    manifest = json.loads(path.read_text())
    for relative, digest in manifest["hashes"].items():
        if file_hash(path.parent / relative) != digest:
            raise ValueError(f"Frozen benchmark hash mismatch: {relative}")
    for name, digest in manifest.get("implementation_hashes", {}).items():
        if file_hash(Path(__file__).resolve().parent / name) != digest:
            raise ValueError(f"Frozen implementation hash mismatch: {name}")
    return manifest


def freeze_execution(manifest_path, *, tool_files, prompt_files, configuration):
    """Explicit pre-run freeze. Writes only the benchmark's manifest, never calls AI."""
    path = Path(manifest_path)
    manifest = validate_manifest(path)
    if manifest.get("execution_freeze"):
        raise ValueError("Execution is already frozen; use a new benchmark version for changes")
    if not tool_files or not prompt_files or not isinstance(configuration, dict) or not configuration:
        raise ValueError("A reserved evaluation needs tool files, prompt files and a declared configuration")
    manifest["execution_freeze"] = {
        "tool_hashes": {str(Path(p).resolve()): file_hash(p) for p in tool_files},
        "prompt_hashes": {str(Path(p).resolve()): file_hash(p) for p in prompt_files},
        "scoring_sha256": file_hash(__file__), "configuration": configuration,
    }
    path.write_text(json.dumps(manifest, sort_keys=True, indent=2, allow_nan=False) + "\n")
    return manifest["execution_freeze"]


def evaluate(questions_path, expected_path, response_callback, output_dir=None, *,
             manifest_path=None, run_kind="smoke_baseline", run_metadata=None):
    """Callback sees each public question only. Default run is explicitly a smoke test."""
    if run_kind not in ("smoke_baseline", "development", "reserved_evaluation"):
        raise ValueError("Unknown run kind")
    manifest = validate_manifest(manifest_path) if manifest_path else None
    if run_kind == "reserved_evaluation":
        freeze = manifest.get("execution_freeze") if manifest else None
        if not freeze:
            raise ValueError("Reserved evaluation requires a pre-run execution freeze")
        for group in ("tool_hashes", "prompt_hashes"):
            for path, digest in freeze[group].items():
                if file_hash(path) != digest:
                    raise ValueError("Tool/prompt changed after execution freeze")
        if freeze["scoring_sha256"] != file_hash(__file__):
            raise ValueError("Scoring changed after execution freeze")
    questions, expected_rows = read_lines(questions_path), read_lines(expected_path)
    expected = {item["id"]: item for item in expected_rows}
    if len(expected) != len(expected_rows) or len({q["id"] for q in questions}) != len(questions) or set(expected) != {q["id"] for q in questions}:
        raise ValueError("Questions and oracle IDs must be unique and agree")
    if run_kind == "development" and any(q["split"] != "development" for q in questions):
        raise ValueError("Development run received reserved questions")
    if run_kind == "reserved_evaluation" and any(q["split"] != "reserved" for q in questions):
        raise ValueError("Reserved run received development questions")
    responses, scores = [], []
    for question in questions:
        # No private rationale, targets or reference assignment enters the callback.
        try:
            response = response_callback(json.loads(json.dumps(question)))
        except Exception as exc:
            response = {"answer": "", "error": type(exc).__name__}
        responses.append({"id": question["id"], "response": response})
        scores.append(score_response(question, expected[question["id"]], response))
    by_block = defaultdict(list)
    for score in scores:
        by_block[f"{score['recording']}:{score['block_id']}"].append(score)
    numeric = [field for item in scores for field in item["numeric_fields"]]
    check_names = sorted(set().union(*(s["checks"].keys() for s in scores))) if scores else []
    report = {
        "run_kind": run_kind, "evaluation_claim": "deterministic/local integration smoke only" if run_kind == "smoke_baseline" else run_kind,
        "question_count": len(scores), "passed": sum(s["passed"] for s in scores),
        "pass_fraction": sum(s["passed"] for s in scores) / len(scores) if scores else None,
        "numeric_field_count": len(numeric), "numeric_field_pass_fraction": sum(f["passed"] for f in numeric) / len(numeric) if numeric else None,
        "check_pass_fractions": {name: sum(s["checks"].get(name, True) for s in scores) / len(scores) for name in check_names},
        "categories": dict(Counter(q["category"] for q in questions)),
        "blocks": {block: {"questions": len(items), "passed": sum(s["passed"] for s in items)} for block, items in by_block.items()},
        "question_sha256": file_hash(questions_path), "expected_sha256": file_hash(expected_path),
        "protocol_sha256": manifest["hashes"].get("protocol.json") if manifest else None,
        "manifest_sha256": file_hash(manifest_path) if manifest_path else None,
        "run_metadata": run_metadata or {}, "execution_freeze": manifest.get("execution_freeze") if manifest else None,
        "manual_review_required": True, "api_outputs_fabricated": False,
        "limitations": "Automated prose screens are incomplete. No API cost, latency, physical labeling accuracy, energy savings or participant findings are inferred.",
        "scores": scores,
    }
    if output_dir:
        output = Path(output_dir); output.mkdir(parents=True, exist_ok=True)
        responses_path = output / "responses.jsonl"
        responses_path.write_text("".join(json.dumps(row, sort_keys=True, allow_nan=False) + "\n" for row in responses))
        report["responses_sha256"] = file_hash(responses_path)
        (output / "results.json").write_text(json.dumps(report, sort_keys=True, indent=2, allow_nan=False) + "\n")
    return report


def main():
    parser = argparse.ArgumentParser(description="Score saved responses; no API calls")
    parser.add_argument("--questions", type=Path, required=True)
    parser.add_argument("--expected", type=Path, required=True)
    parser.add_argument("--responses", type=Path, help="JSONL rows with id and response")
    parser.add_argument("--callback", help="Optional module:function local responder; receives public question")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--run-kind", choices=["smoke_baseline", "development", "reserved_evaluation"], default="smoke_baseline")
    args = parser.parse_args()
    if bool(args.responses) == bool(args.callback):
        parser.error("Choose saved responses or a callback")
    if args.responses:
        rows = read_lines(args.responses)
        answers = {row["id"]: row["response"] for row in rows}
        callback = lambda q: answers[q["id"]]
    else:
        module, function = args.callback.split(":", 1)
        callback = getattr(importlib.import_module(module), function)
    report = evaluate(args.questions, args.expected, callback, args.output,
                      manifest_path=args.manifest, run_kind=args.run_kind)
    print(json.dumps({k: report[k] for k in ("run_kind", "question_count", "passed", "numeric_field_pass_fraction")}, indent=2))


if __name__ == "__main__":
    main()
