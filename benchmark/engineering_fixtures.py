# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Stephen Makonin
"""Public synthetic engineering cases and a controlled revision producer.

No household archive, configured environment file or external provider is read.
The revision producer is a test adapter, not a live HyNILM ingestion service.
"""
from dataclasses import replace
from hashlib import sha256
import math
import threading
from types import MappingProxyType

from benchmark.oracle import OracleDataset, summarize, compare_periods
from wattdialogue.adapter import ReplayStore, BLOCKS, CADENCE_S
from wattdialogue.config import Settings
from wattdialogue.service import WattDialogueService
from wattdialogue.tools import EnergyTools


def forbidden_transport(*args, **kwargs):
    raise AssertionError("Engineering benchmarks prohibit provider requests")


def service(directory):
    directory.mkdir(parents=True, exist_ok=True)
    empty = directory / 'empty.env'
    empty.write_text('')
    result = WattDialogueService(env_file=empty, registry_path=directory/'labels.json', transport=forbidden_transport)
    result.agent.settings_loader = lambda: Settings()
    return result


def cases():
    """60 cases, ten synthetic blocks, two estimate modes, three query types."""
    store = ReplayStore()
    result = []
    for home, blocks in BLOCKS.items():
        for block in blocks:
            for mode in ('online', 'revised'):
                data = store.load(home, block, mode)
                start, end = float(data.t[0]), data.block_end
                oracle = OracleDataset(home, str(block), data.t, data.aggregate_w, data.components_w, CADENCE_S[home])
                for kind in ('meter', 'component', 'comparison'):
                    args = {'mode': mode}
                    if kind == 'comparison':
                        middle = start + (end-start)/2
                        args.update(period_a={'start': start, 'end': middle}, period_b={'start': middle, 'end': end})
                        target = compare_periods(oracle, args['period_a'], args['period_b'], end)['fields']
                        target = {k: v for k,v in target.items() if k in ('period_a_energy_kwh', 'period_b_energy_kwh', 'difference_kwh', 'difference_percent')}
                        tool = 'compare_periods'
                    else:
                        args.update(start=start, end=end)
                        component = 'component_000' if kind == 'component' else None
                        if component:
                            args['component_id'] = component
                        values = summarize(oracle, start, end, end, component)['fields']
                        names = ('component_energy_kwh',) if component else ('energy_kwh', 'average_power_w', 'peak_power_w', 'coverage_fraction')
                        target = {k: values[k] for k in names}
                        tool = 'get_component_features' if component else 'get_window_summary'
                    result.append({'id': f'{home}-{block}-{mode}-{kind}', 'home': home, 'target': target,
                                   'source_hash': data.content_hash, 'mode': mode,
                                   'payload': {'block_id': block, 'mode': 'local', 'as_of': end,
                                               'request': {'tool': tool, 'args': args}}})
    return result


def leaves(evidence):
    if 'period_a' in evidence:
        return [evidence['period_a'], evidence['period_b']]
    return [evidence]


def check(case, answer):
    actual = {f['metric']: f for f in answer.get('fields', [])}
    problems = []
    for key, value in case['target'].items():
        item = actual.get(key, {})
        unit = '%' if key == 'difference_percent' else 'fraction' if key == 'coverage_fraction' else 'W' if key.endswith('_w') else 'kWh'
        source = 'derived' if key in ('coverage_fraction', 'difference_kwh', 'difference_percent') else 'nilm_estimate' if case['id'].endswith('-component') else 'meter'
        observed = item.get('value')
        if not isinstance(observed, (int, float)) or value is None or not math.isclose(observed, value, rel_tol=1e-9, abs_tol=1e-9) or item.get('unit') != unit or item.get('source') != source:
            problems.append(key)
    for outer in answer.get('evidence', []):
        for item in leaves(outer):
            if item.get('evidence_content_hash') != case['source_hash'] or item.get('home_id') != case['home'] or item.get('mode') != case['mode']:
                problems.append('provenance')
    if not answer.get('evidence') or answer.get('status') != 'answer':
        problems.append('status/evidence')
    return sorted(set(problems))


class FrozenRevisionView:
    synthetic_fixture = True

    def __init__(self, datasets, metadata, hook=None):
        self.datasets = MappingProxyType(dict(datasets))
        self._metadata = dict(metadata)
        self.hook = hook
        self.loads = threading.local()

    @property
    def model_version(self):
        return self._metadata['model_version']

    def source_metadata(self):
        return dict(self._metadata)

    def list_blocks(self):
        return {'R1Hz': [17422]}

    def boundary(self, home):
        return self._metadata['boundaries'][home]

    def snapshot(self, home, block):
        if home != 'R1Hz' or int(block) != 17422:
            raise ValueError('Outside synthetic revision fixture')
        return self

    def load(self, home, block, mode='online'):
        data = self.datasets[(home, int(block), mode)]
        self.loads.count = getattr(self.loads, 'count', 0) + 1
        if self.hook:
            self.hook(self.loads.count)
        return data

    def metadata(self, home, block):
        return self.load(home, block).metadata()


class RevisionProducer:
    """Atomically publish immutable component revisions; keep meter data fixed."""
    synthetic_fixture = True

    def __init__(self):
        store = ReplayStore()
        self.base = {('R1Hz', 17422, mode): store.load('R1Hz', 17422, mode) for mode in ('online', 'revised')}
        self._lock = threading.RLock()
        self._metadata = store.source_metadata()
        self.hook = None
        self.loads = threading.local()
        self.publish(0)

    def publish(self, generation):
        version = f'synthetic-revision-{generation}'
        datasets = {}
        for key, original in self.base.items():
            components = original.components_w * (1 + generation / 100)
            components.setflags(write=False)
            digest = sha256(original.content_hash.encode() + version.encode() + components.tobytes()).hexdigest()
            datasets[key] = replace(original, components_w=components, content_hash=digest, model_version=version)
        metadata = {**self._metadata, 'model_version': version}
        with self._lock:
            self.current = FrozenRevisionView(datasets, metadata)

    def snapshot(self, home, block):
        with self._lock:
            view = FrozenRevisionView(self.current.datasets, self.current.source_metadata(), self.hook)
        return view.snapshot(home, block)

    def load(self, home, block, mode='online'):
        data = self.snapshot(home, block).load(home, block, mode)
        self.loads.count = getattr(self.loads, 'count', 0) + 1
        # Direct (un-pinned) control uses one counter across its changing views.
        if self.hook:
            self.hook(self.loads.count)
        return data

    @property
    def model_version(self):
        return self.source_metadata()['model_version']

    def source_metadata(self):
        with self._lock:
            return self.current.source_metadata()

    def list_blocks(self):
        return {'R1Hz': [17422]}

    def boundary(self, home):
        return self.source_metadata()['boundaries'][home]

    def metadata(self, home, block):
        return self.load(home, block).metadata()


def attach_producer(target, producer):
    target.store = producer
    target.tools = EnergyTools(producer, target.labels)
