# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Stephen Makonin
"""Shared evidence-to-display service for replay, local baseline and OpenAI."""
from __future__ import annotations

import math
import re
import time
import json
from hashlib import sha256
from datetime import datetime, timezone
from pathlib import Path

from .adapter import BOUNDARIES, ReplayStore, parse_time
from .config import ROOT, Settings
from .labels import LabelRegistry
from .openai_agent import APIError, OpenAIAgent
from .tools import EnergyTools

METRICS = {
    "energy_kwh": ("Measured electricity", "kWh", "meter"),
    "average_power_w": ("Average measured demand", "W", "meter"),
    "peak_power_w": ("Peak measured demand", "W", "meter"),
    "coverage_fraction": ("Data coverage", "fraction", "derived"),
    "component_energy_kwh": ("Estimated component electricity", "kWh", "nilm_estimate"),
    "signed_residual_energy_kwh": ("Signed unexplained difference", "kWh", "derived"),
    "unexplained_energy_kwh": ("Unexplained electricity", "kWh", "derived"),
    "overallocated_energy_kwh": ("Over-allocation by NILM", "kWh", "derived"),
    "period_a_energy_kwh": ("First period measured electricity", "kWh", "meter"),
    "period_b_energy_kwh": ("Second period measured electricity", "kWh", "meter"),
    "difference_kwh": ("Measured difference", "kWh", "derived"),
    "difference_percent": ("Measured difference", "%", "derived"),
    "illustrative_cost_cad": ("Illustrative variable cost", "CAD", "derived"),
}


def epoch(value):
    return None if value is None else parse_time(value)


def iso(value):
    return datetime.fromtimestamp(float(value), timezone.utc).isoformat().replace("+00:00", "Z") if value is not None else None


def fields_from_evidence(evidence):
    fields = []
    for item in evidence:
        for metric, (label, unit, source) in METRICS.items():
            value = item.get(metric)
            if isinstance(value, (int, float)) and math.isfinite(value):
                if item.get("component_id") and metric in {"energy_kwh", "average_power_w", "peak_power_w"}:
                    if metric == "energy_kwh":
                        continue  # The selected component has its own explicitly estimated metric.
                    label = label.replace("measured", "estimated")
                    source = "nilm_estimate"
                fields.append({"metric": metric, "label": label, "value": value, "unit": unit,
                               "source": source, "evidence_id": item.get("evidence_id")})
    return fields


def normalize_constraints(constraints):
    if constraints is None:
        return []
    return constraints if isinstance(constraints, list) else [constraints]


APPLIANCE_CLASS = re.compile(
    r"\b(?:fridge|freezer|refrigerator|refrigeration|dishwasher|washing machine|washer|dryer|"
    r"water heater|space heater|heater|furnace|heat pump|air conditioner|HVAC|microwave|oven|"
    r"stove|cooker|television|TV|EV charger|electric vehicle|kettle|toaster)\b", re.I)
IDENTITY_QUALIFIER = re.compile(
    r"\b(?:possible|candidate|may|might|could|unknown|unconfirmed|unverified|uncertain|"
    r"uncertainty|unresolved|ambiguous|alternatives?)\b|more than one|can (?:resemble|match|indicate)", re.I)


def screen_model_text(text, *, candidate_name=False, annotation_labels=()):
    """A limited fail-closed prose screen, not factuality certification."""
    if not isinstance(text, str):
        raise APIError("explanation_check", "The model returned invalid explanatory text.")
    if re.search(r"\d", text):
        raise APIError("explanation_check", "The explanation contained unvalidated numbers.")
    for match in re.finditer(r"\b(?:definitely|certainly|guarantee(?:d|s)?|verified|proven)\b", text, re.I):
        prefix = text[max(0, match.start() - 24):match.start()]
        if not re.search(r"\b(?:not|no|never|cannot)\b", prefix, re.I):
            raise APIError("explanation_check", "The explanation contained unsupported certainty.")
    for match in re.finditer(r"\b(?:turn off|unplug|disconnect|disable|shut off|shut down)\b", text, re.I):
        prefix = text[max(0, match.start() - 20):match.start()]
        if not re.search(r"\b(?:not|never|avoid|don't)\b", prefix, re.I):
            raise APIError("comfort_check", "The explanation proposed unchecked appliance control.")
    if not candidate_name and APPLIANCE_CLASS.search(text) and not IDENTITY_QUALIFIER.search(text):
        # Generic preservation advice is not an asserted electrical identity.
        generic_advice = re.match(r"\s*(?:please\s+)?(?:keep|maintain|respect|retain|do not|don't|avoid)\b", text, re.I)
        annotated = any(label and label.casefold() in text.casefold() for label in annotation_labels) and re.search(r"\b(?:annotation|annotated|occupant-confirmed)\b", text, re.I)
        if not generic_advice and not annotated:
            raise APIError("identity_check", "The explanation asserted an unqualified physical appliance identity.")


class WattDialogueService:
    def __init__(self, source_root=None, env_file=None, registry_path=None, transport=None):
        self.store = ReplayStore(source_root)
        self.labels = LabelRegistry(registry_path or ROOT / "runtime" / "labels.json")
        self.tools = EnergyTools(self.store, self.labels)
        self.env_file = Path(env_file) if env_file else ROOT / ".env.local"
        self.agent = OpenAIAgent(lambda: Settings.load(self.env_file), **({"transport": transport} if transport else {}))

    def status(self):
        return {**Settings.load(self.env_file).public_status(), "usage": self.agent.usage(),
                **self.store.source_metadata(),
                "mode": "local", "prototype": True, "live_meter": False,
                "recordings": list(self.store.list_blocks()),
                "privacy": "Local summaries by default; OpenAI needs explicit cloud consent.",
                "household_authentication": "Loopback research demo with session-scoped archive selection."}

    def metadata(self, home, block_id):
        return self.store.metadata(home, int(block_id))

    def bounds(self, home, block_id):
        dataset = self.store.load(home, int(block_id))
        start = float(dataset.t[0])
        cadence = 1.0 if home == "R1Hz" else 60.0
        return start, float(dataset.t[-1]) + cadence

    def blocks(self, home):
        if home not in self.store.list_blocks():
            raise ValueError("Choose one of the available research recordings.")
        blocks = []
        for block in self.store.list_blocks()[home]:
            start, end = self.bounds(home, block)
            blocks.append({"block_id": block, "label": f"{iso(start)[:10]} - {block}",
                           "observation_start": iso(start), "observation_end": iso(end),
                           "available_time": iso(end)})
        return {"home": home, "blocks": blocks}

    def execute(self, name, args, home_scope, block_id=None, as_of=None, fixed_mode=None):
        if name not in {"get_window_summary", "get_component_features", "compare_periods", "get_label"}:
            raise ValueError("This tool is not available.")
        if not isinstance(args, dict):
            raise ValueError("Tool arguments must be an object.")
        args = {k: v for k, v in args.items() if v is not None}
        if any(k in args for k in ("home", "recording", "home_scope", "path", "root", "file")):
            raise ValueError("The server fixes household scope; a tool cannot choose another household.")
        if block_id is not None:
            args.setdefault("block_id", int(block_id))
        requested_blocks = [args.get("block_id", block_id)]
        if name == "compare_periods":
            for key in ("period_a", "period_b"):
                period = args.get(key)
                if not isinstance(period, dict):
                    raise ValueError("Comparison periods must be objects.")
                if set(period) - {"block_id", "start", "end"}:
                    raise ValueError("Comparison periods accept only block and observation bounds; query availability is fixed by the server.")
                requested_blocks.append(period.get("block_id", args.get("block_id", block_id)))
        if block_id is not None and any(int(b) != int(block_id) for b in requested_blocks if b is not None):
            raise ValueError("The requested block is outside this display session.")
        if as_of is not None:
            if "as_of" in args and epoch(args["as_of"]) > epoch(as_of):
                raise ValueError("A tool cannot use evidence after the query time.")
            args["as_of"] = epoch(as_of)
        if fixed_mode is not None:
            if fixed_mode not in ("online", "revised"):
                raise ValueError("Selected estimate mode must be online or revised.")
            if args.get("mode", fixed_mode) != fixed_mode:
                raise ValueError("A tool cannot change the selected estimate mode.")
            args["mode"] = fixed_mode
        return self.tools.call(name, args, home_scope)

    def summary(self, home, block_id, as_of=None):
        start, end = self.bounds(home, block_id)
        as_of = epoch(as_of) if as_of is not None else end
        result = self.execute("get_window_summary", {"block_id": int(block_id), "start": start,
                                                     "end": end, "as_of": as_of}, home)
        return self.display_summary(home, block_id, result, as_of)

    def display_summary(self, home, block_id, result, as_of):
        start, end = self.bounds(home, block_id)
        energies = result.get("component_energy_kwh", {})
        components = []
        if isinstance(energies, dict):
            for component_id, value in energies.items():
                if value is None or float(value) <= 0:
                    continue
                record = self.labels.get(home, component_id, model_version=result.get("model_version", "quiet_fusion_v3a/control/P"), as_of=as_of)
                components.append({"component_id": component_id, "energy_kwh": float(value),
                                   "label": record.get("label") or component_id,
                                   "label_status": record.get("status", "unknown"),
                                   "model_version": result.get("model_version", "quiet_fusion_v3a/control/P"),
                                   "evidence_id": result.get("evidence_id"),
                                   "label_candidates": record.get("alternatives", [])})
        components.sort(key=lambda item: item["energy_kwh"], reverse=True)
        return {**result, "home": home, "block_id": int(block_id),
                "total_energy_kwh": result.get("energy_kwh"),
                "estimated_energy_kwh": result.get("estimated_component_total_kwh"),
                "residual_energy_kwh": result.get("signed_residual_energy_kwh"),
                "coverage_details": result.get("coverage", {}),
                "coverage": result.get("coverage_fraction", 0), "components": components,
                "observation_start": iso(start), "observation_end": iso(end), "available_time": result.get("latest_availability"),
                "freshness": {"archive_replay": True, "as_of": iso(as_of),
                              "observation_start": iso(start), "observation_end": iso(end),
                              "available_time": result.get("latest_availability"), "status": "Archived observations; not a live meter"}}

    def _scope_denial(self, home_scope, block_id, as_of, constraints, message, tick):
        evidence = {"home_id": home_scope, "recording": home_scope, "block_id": int(block_id),
                    "boundary": self.store.boundary(home_scope), "scope_denied": True, "status": "scope_denied",
                    "synthetic_fixture": self.store.synthetic_fixture, "input_kind": self.store.source_metadata()["input_kind"],
                    "coverage": {"applicable": False, "reason": "No other household data queried"},
                    "as_of": iso(as_of)}
        evidence["evidence_id"] = "wd_" + sha256(json.dumps(evidence, sort_keys=True).encode()).hexdigest()[:24]
        return {"answer": "That request is outside the selected recording scope and was denied. " + message,
                "fields": [], "evidence": [evidence], "evidence_ids": [evidence["evidence_id"]],
                "label_candidates": [], "warnings": [message], "constraints": constraints,
                "mode": "local", "status": "scope_denied", "abstained": True,
                "freshness": {"archive_replay": True, "as_of": iso(as_of)}, "latency_s": time.monotonic() - tick}

    def _intent(self, question, home, block_id, as_of):
        start, end = self.bounds(home, block_id)
        args = {"block_id": int(block_id), "start": start, "end": end, "as_of": as_of}
        match = re.search(r"(?:component[_\s-]*|appliance\s*)(\d{1,3})\b", question, re.I)
        if match:
            args["component_id"] = f"component_{int(match.group(1)):03d}"
            return "get_component_features", args
        if re.search(r"compare|difference|more than|less than", question, re.I):
            middle = start + (end - start) / 2
            return "compare_periods", {"period_a": {"block_id": int(block_id), "start": start, "end": middle},
                                       "period_b": {"block_id": int(block_id), "start": middle, "end": end}, "as_of": as_of}
        return "get_window_summary", args

    def local_query(self, payload, home_scope):
        tick = time.monotonic()
        block_id = int(payload["block_id"])
        _, end = self.bounds(home_scope, block_id)
        as_of = epoch(payload.get("as_of")) if payload.get("as_of") is not None else end
        question = str(payload.get("question", ""))[:2000]
        constraints = normalize_constraints(payload.get("constraints"))
        request = payload.get("request")
        if request is not None and (not isinstance(request, dict) or set(request) != {"tool", "args"} or not isinstance(request.get("args"), dict)):
            return {"answer": "I cannot read that structured energy request. Supply only tool and args.",
                    "fields": [], "evidence": [], "evidence_ids": [], "label_candidates": [],
                    "warnings": ["Invalid structured request."], "constraints": constraints,
                    "mode": "local", "abstained": True, "status": "invalid_request",
                    "freshness": {"archive_replay": True, "as_of": iso(as_of)}, "latency_s": time.monotonic() - tick}
        name, args = (request["tool"], request["args"]) if isinstance(request, dict) else self._intent(question, home_scope, block_id, as_of)
        if "mode" not in args:
            inferred_mode = "revised" if re.search(r"\brevised\b|\brevisions?\b|\bretrospect", question, re.I) else "online"
            args = {**args, "mode": payload.get("estimate_mode", inferred_mode)}
        revision_unavailable = args.get("mode") == "revised" and name != "get_label" and as_of < end
        if revision_unavailable:
            args = {**args, "mode": "online"}
        try:
            evidence = self.execute(name, args, home_scope, block_id, as_of)
        except (ValueError, KeyError, TypeError) as exc:
            if re.search(r"outside|household scope|fixes household|display session|is not a listed block", str(exc), re.I):
                return self._scope_denial(home_scope, block_id, as_of, constraints, str(exc), tick)
            return {"answer": "I do not have sufficient available evidence for that request. " + str(exc),
                    "fields": [], "evidence": [], "evidence_ids": [], "label_candidates": [],
                    "warnings": [str(exc)], "constraints": constraints, "mode": "local", "abstained": True,
                    "freshness": {"archive_replay": True, "as_of": iso(as_of)}, "latency_s": time.monotonic() - tick}
        fields = fields_from_evidence([evidence])
        candidates = []
        warnings = list(evidence.get("warnings") or evidence.get("notes") or [])
        if re.search(r"save|guarantee|definitely|certain|bill|tariff|cost|dollar|comfort|temperature|unplug|turn off", question, re.I):
            answer = ("This evidence cannot establish a complete electricity bill, guaranteed savings, or a comfort-preserving change. "
                      "I will respect your stated limits. I need the applicable tariff and comfort context before recommending a change.")
        elif name == "get_component_features":
            component = args["component_id"]
            answer = (f"{component} is an inferred electrical component. Its signature may match more than one appliance; "
                      "a fridge or freezer name would remain a candidate until additional evidence or your confirmation is recorded.")
            candidates = [{"component_id": component, "label": "Unknown", "status": "unknown",
                           "reason": "The local baseline does not infer a physical appliance class.",
                           "alternatives": [], "evidence_id": evidence.get("evidence_id"),
                           "model_version": evidence.get("model_version")}]
        elif name == "compare_periods":
            answer = ("The checked values compare the first and second covered parts of this replay block. "
                      "Different coverage or duration can make totals misleading; this comparison alone does not establish conservation.")
        else:
            energies = {k: v for k, v in evidence.get("component_energy_kwh", {}).items()
                        if isinstance(v, (int, float)) and math.isfinite(v) and v > 0}
            largest = max(energies, key=energies.get) if isinstance(energies, dict) and energies else None
            answer = (f"The largest estimated component in the covered interval is {largest}. Its physical appliance name is unresolved. "
                      if largest else "No active component can be identified from this interval. ")
            answer += "The measured total and estimated component values are shown separately. This archived block may cover only part of a local day."
        if evidence.get("coverage_fraction", 1) < .999:
            answer += " Coverage is incomplete; unavailable intervals have not been counted as zero."
        if evidence.get("mode") == "revised":
            answer += " These are retrospective revisions, available after the archived block."
        if revision_unavailable:
            answer = "Revised estimates are unavailable before the archived block ends. Only available immediate observations are shown. " + answer
            warnings.append("Requested retrospective revisions are not available at this query time; all displayed evidence uses the online path.")
        if self.store.synthetic_fixture:
            answer = "This replay uses generated synthetic examples. " + answer.replace("measured total", "generated aggregate total").replace("measured", "generated aggregate")
        return {"answer": answer, "fields": fields, "evidence": [evidence],
                "evidence_ids": [evidence["evidence_id"]] if evidence.get("evidence_id") else [],
                "label_candidates": candidates, "warnings": warnings, "constraints": constraints,
                "mode": "local", "abstained": revision_unavailable or evidence.get("coverage_fraction", 1) <= 0,
                "status": "revision_unavailable" if revision_unavailable else "answer",
                "freshness": {"archive_replay": True, "as_of": iso(as_of),
                              "available_time": evidence.get("latest_availability")},
                "latency_s": time.monotonic() - tick,
                "explanation_source": "Deterministic local template; not an LLM result"}

    def query(self, payload, home_scope):
        if payload.get("home", home_scope) != home_scope:
            raise ValueError("This request is outside the household selected in the display session.")
        if payload.get("mode", "local") != "openai":
            return self.local_query(payload, home_scope)
        if payload.get("consent") is not True:
            raise ValueError("Cloud processing requires explicit consent; local feedback is available.")
        block_id = int(payload["block_id"])
        start, end = self.bounds(home_scope, block_id)
        as_of = epoch(payload.get("as_of")) if payload.get("as_of") is not None else end
        public_request = payload.get("request")
        request_mode = public_request.get("args", {}).get("mode") if isinstance(public_request, dict) and isinstance(public_request.get("args"), dict) else None
        inferred_mode = "revised" if re.search(r"\brevised\b|\brevisions?\b|\bretrospect", str(payload.get("question", "")), re.I) else "online"
        requested_mode = payload.get("estimate_mode", request_mode or inferred_mode)
        revision_unavailable = requested_mode == "revised" and as_of < end
        fixed_mode = "online" if revision_unavailable else requested_mode
        context = {"block_id": block_id, "start": start, "end": end, "as_of": as_of,
                   "synthetic_fixture": self.store.synthetic_fixture,
                   "input_kind": self.store.source_metadata()["input_kind"],
                   "data_source": self.store.source_metadata()["data_source"],
                   "estimate_mode": fixed_mode, "requested_estimate_mode": requested_mode,
                   "revision_unavailable": revision_unavailable,
                   "inventory": payload.get("inventory", []), "constraints": normalize_constraints(payload.get("constraints")),
                   "archive_replay": True}
        tick = time.monotonic()
        try:
            if fixed_mode not in ("online", "revised"):
                raise APIError("request_check", "The selected estimate mode is invalid.")
            if public_request is not None:
                if not isinstance(public_request, dict) or set(public_request) != {"tool", "args"} or not isinstance(public_request.get("args"), dict):
                    raise APIError("request_check", "A structured energy request accepts only tool and args.")
                request_args = {k: v for k, v in public_request["args"].items() if v is not None}
                if revision_unavailable:
                    request_args["mode"] = "online"
                try:
                    # Validate scope, keys, times and data availability before paid work.
                    self.execute(public_request["tool"], request_args, home_scope, block_id, as_of, fixed_mode=fixed_mode)
                except (ValueError, TypeError, KeyError) as exc:
                    raise APIError("request_check", str(exc)) from None
                context["request"] = {"tool": public_request["tool"], "args": {**request_args, "block_id": block_id, "as_of": as_of}}
            generated = self.agent.run(str(payload.get("question", ""))[:2000], context,
                                       lambda name, args: self.execute(name, args, home_scope, block_id, as_of, fixed_mode=fixed_mode))
            evidence = generated["tool_evidence"]
            allowed_ids = {item["evidence_id"] for item in evidence}
            if not generated.get("evidence_ids") or not set(generated["evidence_ids"]) <= allowed_ids:
                raise APIError("evidence_check", "The explanation did not cite available evidence.")
            annotation_labels = [item.get("label", {}).get("label") for item in evidence
                                 if isinstance(item.get("label"), dict) and item["label"].get("status") in ("occupant-confirmed", "verified")]
            prose = [generated.get("answer", "")]
            if generated.get("clarification") is not None:
                prose.append(generated["clarification"])
            comfort_notes = generated.get("comfort_notes", [])
            if not isinstance(comfort_notes, list):
                raise APIError("explanation_check", "The model returned invalid comfort notes.")
            prose.extend(comfort_notes)
            for text in prose:
                screen_model_text(text, annotation_labels=annotation_labels)
            explanation = " ".join(text.strip() for text in prose if text.strip())
            grouped = {}
            for proposed in generated.get("label_candidates", []):
                if not isinstance(proposed, dict):
                    raise APIError("label_evidence", "An appliance suggestion was invalid.")
                component_id = proposed.get("component_id", "")
                matching = [item for item in evidence if item.get("component_id") == component_id and
                            item.get("evidence_id") == proposed.get("evidence_id")]
                if not matching or not re.fullmatch(r"component_\d{3}", component_id):
                    raise APIError("label_evidence", "An appliance label lacked component evidence.")
                if not isinstance(proposed.get("label"), str) or not proposed["label"].strip() or len(proposed["label"]) > 80:
                    raise APIError("label_evidence", "An appliance label was invalid.")
                alternatives = proposed.get("alternatives", [])
                if not isinstance(alternatives, list):
                    raise APIError("label_evidence", "Appliance alternatives must be a list.")
                screen_model_text(proposed["label"], candidate_name=True)
                screen_model_text(proposed.get("reason", ""), annotation_labels=annotation_labels)
                for alternative in alternatives:
                    screen_model_text(alternative, candidate_name=True)
                item = matching[0]
                if component_id not in grouped:
                    grouped[component_id] = {**proposed, "label": proposed["label"].strip(), "alternatives": [],
                                             "status": "candidate", "model_version": item.get("model_version"),
                                             "ordering_note": "Unranked alternatives; no calibrated identity probabilities are available."}
                group = grouped[component_id]
                if group["model_version"] != item.get("model_version"):
                    raise APIError("label_evidence", "Suggestions cannot combine different model versions.")
                for label in [proposed["label"], *alternatives]:
                    label = label.strip()
                    if label and label.casefold() != group["label"].casefold() and label.casefold() not in {v.casefold() for v in group["alternatives"]}:
                        group["alternatives"].append(label)
            # Every displayed model string is checked before any annotation write.
            candidates = list(grouped.values())
            for proposed in candidates:
                current = self.labels.get(home_scope, proposed["component_id"], model_version=proposed["model_version"])
                if current["status"] in ("occupant-confirmed", "verified"):
                    proposed["registry_status"] = current["status"]
                    proposed["annotation_preserved"] = True
                    continue
                merged_alternatives = list(proposed["alternatives"])
                if current["status"] == "candidate":
                    for label in [current.get("label"), *current.get("alternatives", [])]:
                        if isinstance(label, str) and label.casefold() != proposed["label"].casefold() and label.casefold() not in {v.casefold() for v in merged_alternatives}:
                            merged_alternatives.append(label)
                proposed["alternatives"] = merged_alternatives
                self.labels.set_label(home_scope, proposed["component_id"], proposed["label"], status="candidate",
                                      source={"kind": "openai_proposal", "simulation": True}, evidence=[proposed["evidence_id"]],
                                      alternatives=merged_alternatives, model_version=proposed["model_version"], available_at=as_of)
            refreshed_summary = self.summary(home_scope, block_id, as_of=as_of)
            for proposed in candidates:
                proposed["confirmation_evidence_id"] = refreshed_summary["evidence_id"]
                proposed["confirmation_as_of"] = iso(as_of)
            if revision_unavailable:
                explanation = "Revised estimates are unavailable at this query time; only available immediate observations are shown. " + explanation
            return {"answer": explanation, "fields": fields_from_evidence(evidence), "evidence": evidence,
                    "evidence_ids": generated["evidence_ids"], "label_candidates": candidates,
                    "display_summary": refreshed_summary, "comfort_notes": comfort_notes,
                    "warnings": ["Numeric cards come from deterministic evidence tools. Model explanations still require independent factuality review."],
                    "constraints": normalize_constraints(payload.get("constraints")), "mode": "openai", "abstained": revision_unavailable,
                    "status": "revision_unavailable" if revision_unavailable else "answer",
                    "freshness": {"archive_replay": True, "as_of": iso(as_of), "available_time": refreshed_summary.get("available_time")},
                    "usage": generated["usage"], "latency_s": time.monotonic() - tick,
                    "explanation_source": "OpenAI tool-grounded explanation; checked numeric fields from software"}
        except APIError as exc:
            local = self.local_query({**payload, "mode": "local"}, home_scope)
            local["warnings"].append(str(exc))
            local["cloud_error"] = {"code": exc.code, "message": str(exc)}
            local["requested_mode"] = "openai"
            local["usage"] = self.agent.usage()
            return local

    def confirm_label(self, payload, home_scope):
        if payload.get("home", home_scope) != home_scope:
            raise ValueError("Label confirmation is outside the current household session.")
        if payload.get("confirm") is not True:
            raise ValueError("Explicit label confirmation is required.")
        block_id = int(payload["block_id"])
        as_of = epoch(payload.get("as_of")) if payload.get("as_of") is not None else self.bounds(home_scope, block_id)[1]
        summary = self.summary(home_scope, block_id, as_of=as_of)
        component_id = payload.get("component_id")
        known = {item["component_id"] for item in summary["components"]}
        if component_id not in known:
            raise ValueError("Choose a component with evidence in the current interval.")
        evidence_id = payload.get("evidence_id")
        if evidence_id != summary.get("evidence_id"):
            raise ValueError("The label evidence has changed; refresh the summary before confirming.")
        version = summary.get("model_version", "quiet_fusion_v3a/control/P")
        if payload.get("model_version", version) != version:
            raise ValueError("A label cannot transfer to another model version.")
        label = str(payload.get("label", "")).strip()
        if not label or len(label) > 80 or re.search(r"[<>\x00-\x1f]", label):
            raise ValueError("Enter a short appliance name.")
        record = self.labels.set_label(home_scope, component_id, label, status="occupant-confirmed",
                                       source={"kind": "occupant_confirmation", "actor": "prototype_operator",
                                               "simulation": True},
                                       evidence=[{"evidence_id": evidence_id, "kind": "replay_operator_annotation"}], model_version=version,
                                       available_at=as_of)
        return {"ok": True, "record": record,
                "notice": "Operator-confirmed annotation in a replay prototype; not independently verified identity."}
