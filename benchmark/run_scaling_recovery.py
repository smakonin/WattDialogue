# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Stephen Makonin
"""Resident synthetic scaling and simulated provider recovery (no API access)."""
from collections import defaultdict
from copy import deepcopy
from dataclasses import replace
from hashlib import sha256
import argparse
import json
import math
from pathlib import Path
import sys
import tempfile
import time
import numpy as np
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from benchmark.engineering_fixtures import service, cases, check
from benchmark.run_engineering import disable_keys, hashes, save, digest
from wattdialogue.adapter import ReplayStore, ReplayDataset, CADENCE_S
from wattdialogue.tools import EnergyTools
from wattdialogue.config import Settings
from wattdialogue.openai_agent import APIError

def now(): return time.perf_counter_ns()
def stats(a):
    return {"n":len(a),"median_ms":float(np.median(a)),"p95_ms":float(np.percentile(a,95)),"p99_ms":float(np.percentile(a,99))}

class FixtureStore(ReplayStore):
    """Resident synthetic arrays; production selection/tools remain unchanged."""
    def __init__(self, data):
        super().__init__()
        self.data = data
    def load(self, recording, block_id, mode="online"):
        if recording != self.data.recording or int(block_id) != self.data.block_id:
            raise ValueError("Fixture is outside the selected block")
        return replace(self.data, mode=mode)

def fixture(hours, home, active):
    dt = CADENCE_S[home]
    duration = hours*3600
    elapsed = np.arange(0, duration, dt)
    on = elapsed % 1800 < 600
    components = np.zeros((len(elapsed), 24))
    components[:, :active] = on[:, None]*(40+5*np.arange(active))[None, :]
    meter = 60+components.sum(axis=1)
    t = 1736928000+elapsed
    h = sha256()
    for a in (t, meter, components):
        h.update(a.tobytes()); a.setflags(write=False)
    return ReplayDataset(home, 17422 if home == "R1Hz" else 15431, "online", t, meter,
                         components, h.hexdigest(), "synthetic-scaling-v1", True)

def active_seconds(duration):
    return 600*math.floor(duration/1800)+min(duration % 1800, 600)

def scaling(temp):
    rows = []
    for home in ("AMPds2", "R1Hz"):
        for hours in (1, 6, 24, 72):
            for active in (1, 4, 12, 24):
                data = fixture(hours, home, active)
                s = service(Path(temp))
                s.store = FixtureStore(data)
                s.tools = EnergyTools(s.store, s.labels)
                for seconds in dict.fromkeys((300, 3600, hours*3600)):
                    for tool in ("get_window_summary", "get_component_features"):
                        args = {"block_id": data.block_id, "start": data.block_start,
                                "end": data.block_start+seconds, "as_of": data.block_end}
                        if tool == "get_component_features": args["component_id"] = "component_000"
                        req = {"home": home, "block_id": data.block_id, "as_of": data.block_end,
                               "question": "What does the available evidence show?", "mode": "local",
                               "request": {"tool": tool, "args": args}}
                        s.query(deepcopy(req), home)  # one unmeasured warm-up
                        for repeat in range(10):
                            begin = now(); result = s.query(deepcopy(req), home); finish = now()
                            ev = result["evidence"][0]
                            on_seconds = active_seconds(seconds)
                            expected = ((60*seconds+sum(40+5*i for i in range(active))*on_seconds)
                                        if tool == "get_window_summary" else 40*on_seconds)/3.6e6
                            value_ok = math.isclose(ev["energy_kwh"], expected, rel_tol=0, abs_tol=1e-9)
                            coverage_ok = ev["coverage_fraction"] == 1 and ev["estimated"]
                            rows.append({"home": home, "history_hours": hours, "rows": len(data.t),
                                         "active_components": active, "slot_capacity": 24,
                                         "window_seconds": seconds, "tool": tool, "repeat": repeat+1,
                                         "service_ms": (finish-begin)/1e6,
                                         "oracle_pass": value_ok and coverage_ok,
                                         "expected_energy_kwh": expected, "actual_energy_kwh": ev["energy_kwh"]})
                print(f"Scaling {home} {hours} h, {active} active slots complete", flush=True)
    grouped = defaultdict(list)
    for row in rows:
        key = f"{row['home']}/{row['history_hours']}h/{row['active_components']}active/{row['window_seconds']}s/{row['tool']}"
        grouped[key].append(row["service_ms"])
    return {"measured_calls": len(rows), "oracle_passes": sum(r["oracle_pass"] for r in rows),
            "cells": len(grouped), "by_cell": {k: stats(v) for k, v in grouped.items()},
            "scope": "generated periodic signals, resident immutable arrays; production bounds/selection/energy tools/service; no file loading/HTTP/inference; 24 allocated slots with varying active count; ten repeats per cell"}, rows

def fake_model(payload, key):
    items = payload["input"]
    if payload.get("tools") and items[-1].get("type") != "function_call_output":
        context = json.loads(items[0]["content"])["context"]
        request = context["request"]
        return {"id": "simulated-tool", "model": "SIMULATED", "status": "completed", "usage": {},
                "output": [{"type": "function_call", "call_id": "simulated", "name": request["tool"],
                            "arguments": json.dumps(request["args"])}]}
    ev = json.loads(items[-1]["output"])
    answer = {"answer": "Covered observations and uncertain estimates are shown separately.",
              "evidence_ids": [ev["evidence_id"]], "label_candidates": [],
              "clarification": None, "comfort_notes": []}
    return {"id": "simulated-answer", "model": "SIMULATED", "status": "completed", "usage": {},
            "output": [{"type": "message", "content": [{"type": "output_text", "text": json.dumps(answer)}]}]}


def recovery(directory):
    case = next(c for c in cases() if c['id'].endswith('online-meter'))
    rows=[]
    for code in ('timeout','rate_limit_exceeded','invalid_api_key','insufficient_quota'):
        target=service(directory/code)
        target.agent.settings_loader=lambda: Settings(primary_key='ENGINEERING_DUMMY',live_call_limit=30)
        state={'failed':True}
        def transport(payload,key):
            if state['failed']: raise APIError(code,'Injected engineering failure')
            return fake_model(payload,key)
        target.agent.transport=transport
        request={**case['payload'],'mode':'openai','consent':True}
        for index in range(6):
            state['failed']=index<3
            tick=now(); answer=target.query(deepcopy(request),case['home']); elapsed=(now()-tick)/1e6
            okay=not check(case,answer)
            okay=okay and answer['mode']==('local' if state['failed'] else 'openai')
            okay=okay and (answer.get('cloud_error',{}).get('code')==code if state['failed'] else 'cloud_error' not in answer)
            rows.append({'fault':code,'step':index+1,'outage':state['failed'],'passed':okay,'elapsed_ms':elapsed})
    return {'checks':len(rows),'passed':sum(r['passed'] for r in rows),'provider_network_requests':0},rows


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args(); out=args.output.resolve(); out.mkdir(parents=True,exist_ok=False)
    disable_keys()
    before={**hashes(),str(Path(__file__).relative_to(ROOT)):digest(Path(__file__))}
    save(out/'PROTOCOL.json',{'implementation_sha256':before,'synthetic':True,'provider_network_requests':0,
        'history_hours':[1,6,24,72],'cadence_s':[1,60],'active_slots':[1,4,12,24],'allocated_slots':24,
        'windows_s':[300,3600,'full'],'repetitions':10,'warmups_per_cell':1,
        'timing':'in-process complete service call; arrays already resident; no HTTP, rendering, inference or loading',
        'oracle':'closed-form independent 600-second ON pulse every 1800 seconds plus 60 W background',
        'recovery':'four simulated provider faults, three failed then three restored responses each'})
    with tempfile.TemporaryDirectory() as temporary:
        scale,records=scaling(temporary)
        rec,recs=recovery(Path(temporary)/'recovery')
    save(out/'SCALING.json',scale); save(out/'RECOVERY.json',rec)
    (out/'SCALING_RECORDS.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in records))
    (out/'RECOVERY_RECORDS.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in recs))
    after={**hashes(),str(Path(__file__).relative_to(ROOT)):digest(Path(__file__))}
    passed=before==after and scale['measured_calls']==scale['oracle_passes'] and rec['checks']==rec['passed']
    save(out/'RESULTS.json',{'passed':passed,'implementation_unchanged':before==after,'scaling_calls':scale['measured_calls'],
        'scaling_passed':scale['oracle_passes'],'recovery_passed':rec['passed'],'provider_network_requests':0})
    save(out/'ARTIFACT_SHA256.json',{p.name:digest(p) for p in sorted(out.iterdir()) if p.is_file()})
    print(json.dumps({'passed':passed,'scaling':scale['oracle_passes'],'recovery':rec['passed']}),flush=True)
    return 0 if passed else 1

if __name__=='__main__': raise SystemExit(main())
