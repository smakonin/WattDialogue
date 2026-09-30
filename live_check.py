# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Stephen Makonin
"""Bounded real API check with an explicitly synthetic appliance signature."""
import argparse
import json
import re
from pathlib import Path

from wattdialogue.config import ROOT, Settings
from wattdialogue.openai_agent import APIError, OpenAIAgent, OUTPUT_SCHEMA


def run_check():
    agent = OpenAIAgent(Settings.load)
    evidence = {"evidence_id": "synthetic_component_features", "component_id": "component_012",
                "model_version": "synthetic_fixture_v1", "source": "synthetic test fixture, not a home",
                "mean_active_power_w": 95.0, "active_seconds": 18000,
                "component_energy_kwh": .475, "observed_positive_span_count": 10,
                "median_duration_s": 1800, "coverage_fraction": 1.0,
                "label_status": "unknown", "units": {"power": "W", "energy": "kWh"},
                "notes": ["No physical appliance identity is verified. Inventory contains a fridge and freezer."]}
    tool_calls = []
    def tool(name, args):
        tool_calls.append(name)
        if name not in {"get_component_features", "get_window_summary", "get_label"}:
            raise ValueError("Only synthetic feature evidence is available in this check.")
        return evidence
    result = agent.run("What might this anonymous component represent? Please explain why a fridge and freezer may be ambiguous.",
                       {"block_id": 1, "start": 0, "end": 86400, "as_of": 86400,
                        "inventory": ["fridge", "freezer"], "synthetic_fixture": True,
                        "component_id": "component_012"}, tool)
    required = set(OUTPUT_SCHEMA["required"])
    passed = (required <= set(result) and bool(tool_calls)
              and set(result.get("evidence_ids", [])) == {evidence["evidence_id"]}
              and not re.search(r"\d|definitely|certainly|guarantee|verified|proven", result.get("answer", ""), re.I))
    report = {"passed": bool(passed), "model": Settings.load().model,
              "input_kind": "synthetic component signature; no residential trace was transmitted",
              "tool_calls": tool_calls, "answer": result["answer"],
              "label_candidates": result.get("label_candidates", []), "usage": agent.usage(),
              "scope": "One live API integration check; not the reserved benchmark or appliance accuracy evidence"}
    path = ROOT / "runtime/live_check.json"
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(report, indent=2))
    print(json.dumps({"passed": report["passed"], "model": report["model"],
                      "tool_calls": tool_calls, "usage": report["usage"], "report": str(path)}))
    return 0 if passed else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Perform a bounded paid API check using the configured existing key.")
    args = parser.parse_args()
    if not args.live:
        parser.error("Choose --live to perform the real API check.")
    try:
        raise SystemExit(run_check())
    except APIError as exc:
        print(json.dumps({"passed": False, "error_code": exc.code, "message": str(exc)}))
        raise SystemExit(1)
