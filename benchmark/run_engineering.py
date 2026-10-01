# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Stephen Makonin
"""Bounded, no-key HTTP soak and atomic-revision benchmarks (NumPy only)."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
from http.cookiejar import CookieJar
import json
import multiprocessing as mp
import os
from pathlib import Path
import platform
import resource
import subprocess
import sys
import tempfile
import threading
import time
from urllib.request import build_opener, HTTPCookieProcessor, ProxyHandler, Request

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from benchmark.engineering_fixtures import service, cases, check, RevisionProducer, attach_producer, leaves
from wattdialogue.server import DisplayServer


def save(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False)+'\n')


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def hashes():
    paths = sorted((ROOT/'wattdialogue').glob('*.py')) + [Path(__file__), ROOT/'benchmark/engineering_fixtures.py', ROOT/'benchmark/oracle.py']
    return {str(p.relative_to(ROOT)): digest(p) for p in paths}


def disable_keys():
    for name in ('OPENAI_API_KEY', 'OPENAI_API_KEY_BACKUP', 'WATTDIALOGUE_MODEL', 'WATTDIALOGUE_LIVE_CALL_LIMIT'):
        os.environ.pop(name, None)


def server_process(channel, stop, directory):
    disable_keys()
    target = service(Path(directory))
    server = DisplayServer(('127.0.0.1', 0), target)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    channel.send({'port': server.server_port, 'pid': os.getpid()})
    stop.wait()
    server.shutdown()
    server.server_close()
    worker.join(10)
    maximum = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    channel.send({'server_peak_rss_mib': maximum/(1024**2 if sys.platform=='darwin' else 1024), 'provider_calls': target.agent.usage()})
    channel.close()


class Client:
    def __init__(self, base, home):
        self.base = base
        self.opener = build_opener(ProxyHandler({}), HTTPCookieProcessor(CookieJar()))
        self.token = self.call('/api/status')['csrf_token']
        self.call('/api/home', {'home': home})

    def call(self, path, payload=None):
        body = json.dumps(payload).encode() if payload is not None else None
        headers = {'Content-Type':'application/json'}
        if payload is not None:
            headers['X-WattDialogue-Token'] = self.token
        req = Request(self.base+path, data=body, headers=headers)
        with self.opener.open(req, timeout=10) as response:
            encoded = response.read()
        return json.loads(encoded)


def stats(records, elapsed):
    okay = [r for r in records if not r['errors']]
    times = [r['http_json_ms'] for r in records if r['http_json_ms'] is not None]
    return {'attempts':len(records), 'passed':len(okay), 'failed':len(records)-len(okay),
            'elapsed_s':elapsed, 'successful_queries_s':len(okay)/elapsed,
            'median_ms':float(np.median(times)) if times else None,
            'p95_ms':float(np.percentile(times,95)) if times else None,
            'p99_ms':float(np.percentile(times,99)) if times else None}


def soak(base, count, seconds, workload):
    clients = [{home:Client(base,home) for home in ('R1Hz','AMPds2')} for _ in range(count)]
    begin = threading.Barrier(count+1)
    phase_start = 0
    records = []
    lock = threading.Lock()
    def worker(index):
        nonlocal phase_start
        begin.wait()
        sequence = index
        local = []
        while time.monotonic() < phase_start+seconds:
            case = workload[sequence % len(workload)]
            sequence += count
            tick = time.monotonic()
            latency = None
            try:
                answer = clients[index][case['home']].call('/api/query', case['payload'])
                latency = (time.monotonic()-tick)*1000
                errors = check(case, answer)
            except Exception as exc:
                errors = [type(exc).__name__+': '+str(exc)[:180]]
            local.append({'client':index, 'case':case['id'], 'start_s':tick-phase_start,
                          'completed_s':time.monotonic()-phase_start, 'http_json_ms':latency, 'errors':errors})
        with lock:
            records.extend(local)
    with ThreadPoolExecutor(max_workers=count) as pool:
        tasks = [pool.submit(worker,i) for i in range(count)]
        phase_start = time.monotonic()
        begin.wait()
        for task in tasks:
            task.result()
    elapsed = time.monotonic()-phase_start
    records.sort(key=lambda r:r['start_s'])
    result = stats(records, elapsed)
    result['clients'] = count
    result['offered_window_s'] = seconds
    result['bins'] = []
    for start in range(0, int(np.ceil(seconds)), 5):
        end = min(start+5,seconds)
        cohort = [r for r in records if start<=r['completed_s']<end]
        result['bins'].append({'start_s':start, 'end_s':end, **stats(cohort,end-start)})
    result['drain_completions'] = sum(r['completed_s']>=seconds for r in records)
    return result, records


def canonical(answer):
    return {k:v for k,v in answer.items() if k != 'latency_s'}


def revision_tests(directory, repetitions=8, negative_control=True):
    target = service(directory)
    producer = RevisionProducer()
    attach_producer(target, producer)
    start,end = target.bounds('R1Hz',17422)
    scenarios = [
        ('summary-online', {'question':'consumption'}),
        ('summary-revised', {'question':'revised consumption'}),
        ('component-online', {'question':'appliance 0'}),
        ('component-revised', {'question':'revised appliance 0'}),
        ('comparison-online', {'question':'compare consumption'}),
        ('comparison-revised', {'question':'compare revised consumption'}),
        ('early-revised', {'question':'revised consumption','as_of':end-1}),
        ('label-version', {'request':{'tool':'get_label','args':{'component_id':'component_000'}}}),
    ]
    target.labels.set_label('R1Hz','component_000','Fridge',status='occupant-confirmed',
                           source={'kind':'occupant_confirmation','simulation':True}, evidence=['synthetic-test'], model_version='synthetic-revision-0', available_at=end)
    records = []
    def interleave(name, extra, generation, pinned):
        producer.publish(generation)
        payload = {'block_id':17422, 'mode':'local','as_of':end, **extra}
        before = target.query(payload,'R1Hz')
        arrived, resume = threading.Event(), threading.Event()
        def hook(load_count):
            if load_count == (1 if name=='label-version' else 3):
                arrived.set()
                if not resume.wait(10):
                    raise RuntimeError('Revision test barrier timed out')
        producer.hook = hook
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(target.query if pinned else target._query, payload, 'R1Hz')
            try:
                if not arrived.wait(10):
                    raise RuntimeError('Query did not reach forced interleaving')
                producer.publish(generation+1)
            finally:
                resume.set()
            answer = future.result(timeout=10)
        producer.hook = None
        after = target.query(payload,'R1Hz')
        consistent = canonical(answer)==canonical(before)
        fresh = canonical(after)!=canonical(before)
        versions = [v.get('model_version') for e in answer['evidence'] for v in leaves(e)]
        return {'scenario':name, 'old_generation':generation, 'new_generation':generation+1,
                'pinned':pinned, 'inflight_matches_old':consistent, 'next_query_changed':fresh,
                'versions':versions, 'passed':consistent and fresh,
                'before_sha256':sha256(json.dumps(canonical(before),sort_keys=True).encode()).hexdigest(),
                'inflight_sha256':sha256(json.dumps(canonical(answer),sort_keys=True).encode()).hexdigest(),
                'after_sha256':sha256(json.dumps(canonical(after),sort_keys=True).encode()).hexdigest()}
    control = interleave('comparison-online',{'question':'compare consumption'},0,False) if negative_control else None
    for iteration in range(repetitions):
        for number,(name,extra) in enumerate(scenarios):
            records.append(interleave(name,extra,2*(iteration*len(scenarios)+number),True))
    # Confirmation from a superseded snapshot must be rejected.
    producer.publish(0)
    old = target.summary('R1Hz',17422,as_of=end)
    producer.publish(1)
    try:
        target.confirm_label({'block_id':17422,'as_of':end,'component_id':'component_000','confirm':True,
                              'label':'Fridge','model_version':old['model_version'],'evidence_id':old['evidence_id']},'R1Hz')
        stale_rejected=False
    except ValueError:
        stale_rejected=True
    label_not_transferred = target.labels.get('R1Hz','component_000',model_version='synthetic-revision-1',as_of=end)['status']=='unknown'
    return {'cases':len(records), 'passed':sum(r['passed'] for r in records), 'records':records,
            'negative_control':control,'stale_confirmation_rejected':stale_rejected,
            'old_label_not_transferred':label_not_transferred,
            'provider_calls':target.agent.usage()}


def run(args):
    disable_keys()
    out = args.output.resolve()
    out.mkdir(parents=True,exist_ok=False)
    implementation = hashes()
    for name in implementation:
        target = out/'implementation'/name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT/name).read_bytes())
    workload = cases()
    save(out/'PROTOCOL.json', {'version':1, 'created_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),
         'platform':platform.platform(),'machine':platform.machine(),'logical_cpus':os.cpu_count(),
         'python':platform.python_version(),'numpy':np.__version__,'clients':args.clients,'seconds_per_phase':args.seconds,
         'revision_repetitions':args.repetitions,'workload_cases':len(workload),'workload_sha256':sha256(json.dumps(workload,sort_keys=True).encode()).hexdigest(),
         'implementation_sha256':implementation, 'input':'generated demo signals only; ten compatibility-alias blocks',
         'timing':'client request through full body read and JSON decoding; scoring after stopwatch, inside closed-loop cycle',
         'throughput':'successful completions / elapsed phase including final drain; no think time; HTTP/1.0 new connections',
         'memory':'isolated server-process RSS sampled every second; final process high-water RSS; no client/oracle memory',
         'cache':'four-entry production LRU; ten blocks and two modes force cache churn; no OS cache flush',
         'revision':'controlled in-memory publisher; stable meter/timestamps; changed component arrays/hash/model version; forced publication after query begins',
         'boundary':'local HTTP/template only; no provider, browser, network meter, inference or live ingestion timing',
         'limits':'bounded clients, 10-second HTTP/barrier timeout; uncontrolled host background load; one host',
         'external_provider_requests':0})
    save(out/'CASES.json',workload)
    ctx = mp.get_context('spawn')
    channel, child = ctx.Pipe()
    stop = ctx.Event()
    with tempfile.TemporaryDirectory() as temporary:
        process = ctx.Process(target=server_process,args=(child,stop,temporary))
        process.start()
        memory = []
        sampler_stop = threading.Event()
        def sample():
            while not sampler_stop.wait(1):
                try:
                    value = subprocess.run(['ps','-o','rss=','-p',str(process.pid)],capture_output=True,text=True,check=True)
                    memory.append({'elapsed_s':time.monotonic()-sample_start,'rss_mib':int(value.stdout.strip())/1024})
                except (OSError,ValueError,subprocess.CalledProcessError):
                    pass
        sample_start=time.monotonic()
        sampler=threading.Thread(target=sample,daemon=True)
        summaries=[]
        try:
            if not channel.poll(30):
                raise RuntimeError('Local test server did not start')
            info=channel.recv()
            sampler.start()
            base=f"http://127.0.0.1:{info['port']}"
            for clients in args.clients:
                print(f'Sustained phase: {clients} clients, {args.seconds:g} seconds',flush=True)
                summary,records=soak(base,clients,args.seconds,workload)
                summaries.append(summary)
                (out/f'HTTP_{clients}_CLIENTS.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in records))
                save(out/f'HTTP_{clients}_SUMMARY.json',summary)
                print(f"Completed: {summary['passed']}/{summary['attempts']}; p95 {summary['p95_ms']:.2f} ms",flush=True)
        finally:
            stop.set()
            sampler_stop.set()
            if sampler.is_alive(): sampler.join(3)
            process.join(15)
            if process.is_alive():
                process.terminate(); process.join(5)
        if process.exitcode != 0:
            raise RuntimeError(f'Local server exited {process.exitcode}')
        ending=channel.recv() if channel.poll(5) else {}
        save(out/'SERVER_MEMORY.json', {'samples':memory, **ending})
        print('Forced in-flight revisions',flush=True)
        revisions=revision_tests(Path(temporary)/'revisions',args.repetitions)
    save(out/'REVISIONS.json',revisions)
    verified=hashes()==implementation
    passes=all(s['failed']==0 for s in summaries) and revisions['passed']==revisions['cases'] and revisions['stale_confirmation_rejected'] and revisions['old_label_not_transferred'] and not revisions['negative_control']['inflight_matches_old'] and verified
    save(out/'RESULTS.json',{'passed':passes,'implementation_unchanged':verified,'http':summaries,
         'revision_cases':revisions['cases'],'revision_passed':revisions['passed'],
         'negative_control_exposed_mixing':not revisions['negative_control']['inflight_matches_old'],
         'stale_confirmation_rejected':revisions['stale_confirmation_rejected'],'old_label_not_transferred':revisions['old_label_not_transferred'],
         'server_peak_rss_mib':ending.get('server_peak_rss_mib'),'external_provider_requests':0})
    save(out/'ARTIFACT_SHA256.json',{str(p.relative_to(out)):digest(p) for p in sorted(out.rglob('*')) if p.is_file()})
    print(json.dumps({'passed':passes,'http_attempts':sum(s['attempts'] for s in summaries),'revision_passed':revisions['passed'],'output':str(out)}),flush=True)
    return 0 if passes else 1


def arguments():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,required=True,help='New output directory; never overwrite')
    p.add_argument('--clients',type=int,nargs='+',default=[1,4,8])
    p.add_argument('--seconds',type=float,default=60)
    p.add_argument('--repetitions',type=int,default=8)
    args=p.parse_args()
    if not 1<=args.seconds<=600 or not 1<=args.repetitions<=100 or any(not 1<=n<=16 for n in args.clients) or len(set(args.clients))!=len(args.clients) or len(args.clients)>4:
        p.error('Use 1..600 seconds, 1..100 repetitions and 1..4 distinct client levels in 1..16')
    return args


if __name__=='__main__':
    raise SystemExit(run(arguments()))
