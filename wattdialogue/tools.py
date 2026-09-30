# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Stephen Makonin
"""Deterministic, home-scoped evidence tools for a conversational renderer."""
from __future__ import annotations

from hashlib import sha256
import json
import math

import numpy as np

from .adapter import BLOCKS, COMPONENT_CAPACITY, component_id, iso_time
from .labels import LabelRegistry

TOOL_NAMES = ("get_window_summary", "get_component_features", "compare_periods", "get_label")
COMMON_ARGS = {"block_id", "start", "end", "as_of", "mode", "recording", "home_id"}


def _identified(result):
    encoded = json.dumps(result, sort_keys=True, separators=(",", ":"), allow_nan=False)
    result["evidence_id"] = "wd_" + sha256(encoded.encode()).hexdigest()[:24]
    return result


class EnergyTools:
    def __init__(self, store, labels=None, flat_rate_cad_per_kwh=None):
        self.store = store
        self.labels = labels if labels is not None else LabelRegistry()
        if flat_rate_cad_per_kwh is not None:
            try:
                converted_rate = float(flat_rate_cad_per_kwh)
            except (TypeError, ValueError, OverflowError) as exc:
                raise ValueError("Illustrative flat rate must be finite and nonnegative") from exc
            if isinstance(flat_rate_cad_per_kwh, bool) or not math.isfinite(converted_rate) or converted_rate < 0:
                raise ValueError("Illustrative flat rate must be finite and nonnegative")
            flat_rate_cad_per_kwh = converted_rate
        self.flat_rate_cad_per_kwh = flat_rate_cad_per_kwh

    def call(self, name, args, home_scope):
        if not isinstance(home_scope, str) or home_scope not in BLOCKS:
            raise ValueError("Authenticated home_scope must be R1Hz or AMPds2")
        if name not in TOOL_NAMES:
            raise ValueError("Unknown energy tool")
        if not isinstance(args, dict):
            raise ValueError("Tool arguments must be a JSON object")
        extra = {"component_id"} if name in ("get_component_features", "get_label") else {"period_a", "period_b"} if name == "compare_periods" else set()
        if set(args) - COMMON_ARGS - extra:
            raise ValueError("The tool request contains unsupported arguments")
        self._scope(args, home_scope)
        return getattr(self, name)(args, home_scope)

    @staticmethod
    def _scope(args, home_scope):
        for field in ("recording", "home_id"):
            if field in args and args[field] != home_scope:
                raise ValueError("The request is outside the authenticated home")

    def _window(self, args, home_scope):
        if "block_id" not in args:
            raise ValueError("block_id is required")
        dataset = self.store.load(home_scope, args["block_id"], args.get("mode", "online"))
        selected = dataset.select(args.get("start"), args.get("end"), args.get("as_of"))
        return dataset, selected

    def _envelope(self, data, selected):
        component_available = (data.block_end if data.mode == "revised" else selected["latest_effective"]) if selected["component_valid"].any() else None
        latest_available = max((v for v in (selected["latest_meter"], component_available) if v is not None), default=None)
        result = {
            **{k: v for k, v in data.metadata().items() if k in ("synthetic_fixture", "input_kind", "data_source", "recording_label")},
            "home_id": data.recording, "recording": data.recording,
            "block_id": data.block_id, "model_version": data.model_version,
            "mode": data.mode, "boundary": data.metadata()["boundary"],
            "units": {"power": "W", "energy": "kWh"},
            "window": {"start": iso_time(selected["start"]), "end": iso_time(selected["end"])},
            "interval_start": iso_time(selected["start"]), "interval_end": iso_time(selected["end"]),
            "as_of": iso_time(selected["as_of"]), "coverage": selected["coverage"],
            "coverage_fraction": selected["coverage"]["fraction"],
            "latest_availability": iso_time(latest_available),
            "measurement_available_at": iso_time(selected["latest_meter"]),
            "component_available_at": iso_time(component_available),
            "latest_estimate_effective_at": iso_time(selected["latest_effective"]),
            "estimate_source": "Generated synthetic component vectors; no learned NILM inference." if data.synthetic_fixture else "frozen immediate HyNILM path" if data.mode == "online" else "frozen daily retrospective HyNILM path",
            "evidence_content_hash": data.content_hash,
            "estimated": True,
            "notes": [
                "Historical replay, not a live meter feed.",
                "Component values are estimates for anonymous model slots, not verified appliance identities.",
                "No estimate is imputed across absent or invalid meter intervals.",
            ],
        }
        if data.synthetic_fixture:
            result["notes"].insert(0, "Wholly synthetic demonstration; no real household, live meter or experimental model result.")
        if not selected["coverage"]["complete"]:
            result["notes"].append("The requested period has incomplete available meter coverage; reported energy is only the observed portion.")
        if data.mode == "revised":
            result["revised_available_at"] = iso_time(data.block_end)
        return result

    def _cost(self, energy):
        if self.flat_rate_cad_per_kwh is None:
            return {"available": False, "reason": "No tariff was supplied; no cost is inferred."}
        return {
            "available": energy is not None,
            "amount": None if energy is None else energy * self.flat_rate_cad_per_kwh,
            "currency": "CAD", "flat_rate_cad_per_kwh": self.flat_rate_cad_per_kwh,
            "illustrative": True,
            "assumption": "Illustrative flat energy charge only; not a real utility tariff or bill. Taxes, fixed charges and tariff tiers are excluded.",
        }

    def get_window_summary(self, args, home_scope):
        data, s = self._window(args, home_scope)
        m, c, w = s["meter_valid"], s["component_valid"], s["overlap"]
        energy = float(np.dot(data.aggregate_w[m], w[m]) / 3.6e6) if m.any() else None
        seconds = s["coverage"]["valid_meter_seconds"]
        component_energies = (data.components_w[c].T @ w[c] / 3.6e6) if c.any() else None
        residual = data.aggregate_w[c] - data.components_w[c].sum(axis=1)
        signed = float(np.dot(residual, w[c]) / 3.6e6) if c.any() else None
        positive = float(np.dot(np.maximum(residual, 0), w[c]) / 3.6e6) if c.any() else None
        negative = float(np.dot(np.maximum(-residual, 0), w[c]) / 3.6e6) if c.any() else None
        result = self._envelope(data, s)
        result.update({
            "energy_kwh": energy,
            "average_power_w": energy * 3.6e6 / seconds if energy is not None else None,
            "peak_power_w": float(data.aggregate_w[m].max()) if m.any() else None,
            "component_capacity": COMPONENT_CAPACITY,
            "component_capacity_is_appliance_count": False,
            "component_energy_kwh": {component_id(i): None if component_energies is None else float(component_energies[i]) for i in range(COMPONENT_CAPACITY)},
            "label_status": {component_id(i): self.labels.get(home_scope, i, model_version=data.model_version, as_of=s["as_of"])["status"] for i in range(COMPONENT_CAPACITY)},
            "estimated_component_total_kwh": None if component_energies is None else float(component_energies.sum()),
            "meter_energy_on_component_coverage_kwh": float(np.dot(data.aggregate_w[c], w[c]) / 3.6e6) if c.any() else None,
            "signed_residual_energy_kwh": signed,
            "unexplained_energy_kwh": positive,
            "overallocated_energy_kwh": negative,
            "unexplained_kwh": positive, "overallocation_kwh": negative,
            "overallocated_seconds": float(w[c][residual < -1e-9].sum()) if c.any() else 0.0,
            "residual_definition": "Measured aggregate minus the sum of all estimated components. Positive residual includes background and unassigned demand; negative residual denotes over-allocation and is not silently clipped away.",
            "cost": self._cost(energy),
            "metric_sources": {"energy_kwh": "meter", "average_power_w": "meter", "peak_power_w": "meter",
                               "component_energy_kwh": "nilm_estimate", "signed_residual_energy_kwh": "derived",
                               "unexplained_energy_kwh": "derived", "overallocated_energy_kwh": "derived", "cost": "derived"},
        })
        if negative is not None and negative > 1e-9:
            result["notes"].append("Estimated components exceed measured aggregate in part of this window; do not present their allocation as an exact physical decomposition.")
        return _identified(result)

    def get_component_features(self, args, home_scope):
        if "component_id" not in args:
            raise ValueError("component_id is required")
        component = component_id(args["component_id"])
        index = int(component[-3:])
        data, s = self._window(args, home_scope)
        valid, w = s["component_valid"], s["overlap"]
        power = data.components_w[:, index]
        energy = float(np.dot(power[valid], w[valid]) / 3.6e6) if valid.any() else None
        active = valid & (power > 1e-9)
        active_seconds = float(w[active].sum())
        episodes = []
        indices = np.flatnonzero(active)
        for row in indices:
            lo, hi = max(float(data.t[row]), s["start"]), min(float(data.t[row] + data.cadence_s), s["end"])
            if episodes and math.isclose(episodes[-1]["end_unix"], lo, rel_tol=0, abs_tol=1e-6):
                episodes[-1]["end_unix"] = hi
                episodes[-1]["energy_kwh"] += float(power[row] * (hi - lo) / 3.6e6)
            else:
                episodes.append({"start_unix": lo, "end_unix": hi, "energy_kwh": float(power[row] * (hi - lo) / 3.6e6)})
        for episode in episodes:
            episode.update({"start": iso_time(episode["start_unix"]), "end": iso_time(episode["end_unix"]),
                            "duration_s": episode["end_unix"] - episode["start_unix"],
                            "left_censored": True, "right_censored": True})
        # These are observed positive spans, not claimed complete appliance programs.
        seconds = s["coverage"]["valid_component_seconds"]
        result = self._envelope(data, s)
        label = self.labels.get(home_scope, component, model_version=data.model_version, as_of=s["as_of"])
        result.update({
            "component_id": component, "label": label, "label_status": label["status"],
            "coverage_fraction": s["coverage"]["component_fraction"],
            "energy_kwh": energy, "component_energy_kwh": energy,
            "average_power_w": energy * 3.6e6 / seconds if energy is not None else None,
            "peak_power_w": float(power[valid].max()) if valid.any() else None,
            "mean_active_power_w": float(np.dot(power[active], w[active]) / active_seconds) if active_seconds else None,
            "active_seconds": active_seconds,
            "observed_positive_spans": episodes[:20], "observed_positive_span_count": len(episodes),
            "spans_truncated": len(episodes) > 20,
            "state": "estimated positive demand" if active_seconds else "no positive estimated demand in available coverage",
            "cost": self._cost(energy),
            "metric_sources": {"energy_kwh": "nilm_estimate", "component_energy_kwh": "nilm_estimate",
                               "average_power_w": "nilm_estimate", "peak_power_w": "nilm_estimate", "active_seconds": "nilm_estimate", "cost": "derived"},
        })
        result["notes"].append("Positive spans use inferred component power. Censoring is conservatively marked; no complete physical appliance program or known appliance-OFF state is asserted.")
        return _identified(result)

    def compare_periods(self, args, home_scope):
        periods = []
        for name in ("period_a", "period_b"):
            p = args.get(name)
            if not isinstance(p, dict):
                raise ValueError("compare_periods requires period_a and period_b objects")
            if set(p) - COMMON_ARGS:
                raise ValueError("A comparison period contains unsupported arguments")
            self._scope(p, home_scope)
            merged = {key: args[key] for key in ("block_id", "as_of", "mode") if key in args}
            merged.update(p)
            periods.append(self.get_window_summary(merged, home_scope))
        a, b = periods
        ae, be = a["energy_kwh"], b["energy_kwh"]
        difference = None if ae is None or be is None else be - ae
        comparable = a["coverage"]["complete"] and b["coverage"]["complete"] and math.isclose(a["coverage"]["requested_seconds"], b["coverage"]["requested_seconds"], abs_tol=1e-6)
        result = {
            **{k: v for k, v in self.store.source_metadata().items() if k not in ("boundaries", "household_labels")},
            "home_id": home_scope, "boundary": a["boundary"], "model_version": a["model_version"],
            "units": {"power": "W", "energy": "kWh"},
            "period_a_energy_kwh": ae, "period_b_energy_kwh": be,
            "difference_kwh": difference,
            "difference_percent": 100 * difference / ae if difference is not None and ae > 0 else None,
            "period_a": a, "period_b": b, "comparable_complete_equal_duration": comparable,
            "coverage": {"period_a": a["coverage"], "period_b": b["coverage"]},
            "latest_availability": max((v for v in (a["latest_availability"], b["latest_availability"]) if v is not None), default=None),
            "label_status": "anonymous estimated components; per-period annotation status retained",
            "cost_difference": self._cost(difference),
            "metric_sources": {"period_a_energy_kwh": "meter", "period_b_energy_kwh": "meter", "difference_kwh": "derived", "difference_percent": "derived", "cost_difference": "derived"},
            "notes": ["Difference is period B minus period A for observed available aggregate consumption.",
                      "A difference alone does not establish energy savings caused by an intervention or account for weather, occupancy or comfort."],
        }
        if not comparable:
            result["notes"].append("Coverage or requested durations differ; this is not a complete equal-duration comparison.")
        return _identified(result)

    def get_label(self, args, home_scope):
        if "component_id" not in args:
            raise ValueError("component_id is required")
        label = self.labels.get(home_scope, args["component_id"], model_version=self.store.model_version, as_of=args.get("as_of"))
        result = {**{k: v for k, v in self.store.source_metadata().items() if k not in ("boundaries", "household_labels")},
                  "home_id": home_scope, "boundary": self.store.boundary(home_scope), "model_version": self.store.model_version,
                  "component_id": component_id(args["component_id"]), "label": label,
                  "label_status": label["status"], "latest_availability": label["available_at"],
                  "units": {"power": "W", "energy": "kWh"},
                  "coverage": {"applicable": False, "reason": "Label annotation, not a meter measurement."}}
        return _identified(result)
