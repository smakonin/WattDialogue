# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Stephen Makonin
"""No-key tests for budget reservations, raw/fallback retention and execution freeze."""
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from benchmark.generate import build_benchmark
from benchmark.oracle import file_hash
from benchmark.run_model_evaluation import (ABLATION_INSTRUCTIONS, BudgetLedger, RecordingTransport,
    RunConfig, ablation_context, case_payload, execute_case, minute_bins, prepare_freeze,
    run_evaluation, token_upper_bound)
from wattdialogue.adapter import BLOCKS, CADENCE_S, ReplayStore
from wattdialogue.config import Settings
from wattdialogue.openai_agent import APIError, INSTRUCTIONS
from wattdialogue.service import WattDialogueService


class FormalEvaluationTests(unittest.TestCase):
    def setUp(self):
        self.temp=Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.config=RunConfig(repeats=1,workers=2)

    def payload(self):
        return {"model":"test","input":[],"max_output_tokens":100}

    def test_parallel_reservations_and_reported_cached_cost(self):
        ledger=BudgetLedger(self.temp/'budget.json',self.config)
        a=ledger.reserve(self.payload());b=ledger.reserve(self.payload())
        self.assertEqual(ledger.state['calls'],2)
        self.assertGreater(ledger.accounted,0)
        ledger.finish(a['request_index'],{'usage':{'input_tokens':1000,'output_tokens':200,
                     'input_tokens_details':{'cached_tokens':500}}})
        ledger.finish(b['request_index'],known_unbilled=True)
        expected=(500*.75+500*.075+200*4.5)/1e6
        self.assertAlmostEqual(ledger.accounted,expected)
        self.assertEqual(ledger.state['pending'],{})

    def test_parallel_journal_lines_and_shared_budget_remain_valid(self):
        ledger=BudgetLedger(self.temp/'budget.json',self.config)
        journal=self.temp/'journal.jsonl'
        def work(index):
            transport=RecordingTransport(ledger,journal,lambda *_:{'id':str(index),'model':'snapshot',
                     'usage':{'input_tokens':100,'output_tokens':10},'output':[]})
            transport.case_key=f'case-{index}'
            transport({'input':[{'role':'user','content':'x'*10000}],'max_output_tokens':100},'unit-test-token')
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(work,range(12)))
        records=[json.loads(line) for line in journal.read_text().splitlines()]
        self.assertEqual(len(records),24)
        self.assertEqual(sum(r['event']=='request_started' for r in records),12)
        self.assertEqual(len({r['request_index'] for r in records}),12)
        self.assertEqual(ledger.state['calls'],12)
        self.assertEqual(ledger.state['input_tokens'],1200)
        self.assertEqual(ledger.state['pending'],{})

    def test_unknown_cost_retains_reservation_and_crash_is_charged(self):
        ledger=BudgetLedger(self.temp/'budget.json',self.config)
        a=ledger.reserve(self.payload())
        resumed=BudgetLedger(self.temp/'budget.json',self.config)
        self.assertAlmostEqual(resumed.accounted,a['reserved_usd'])
        self.assertEqual(resumed.state['pending'],{})
        b=resumed.reserve(self.payload());resumed.finish(b['request_index'])
        self.assertGreater(resumed.state['uncertain_reserved_usd'],a['reserved_usd'])

    def test_preflight_caps_prevent_transport_and_no_key_serialized(self):
        ledger=BudgetLedger(self.temp/'budget.json',RunConfig(budget_usd=.000001))
        transport=RecordingTransport(ledger,self.temp/'journal.jsonl',lambda *_:self.fail('Paid request should not run'))
        with self.assertRaisesRegex(APIError,'cost cap'):
            transport(self.payload(),'sensitive-value')
        self.assertFalse((self.temp/'journal.jsonl').exists())
        ledger=BudgetLedger(self.temp/'budget2.json',self.config)
        transport=RecordingTransport(ledger,self.temp/'journal2.jsonl',lambda *_:{'id':'r','model':'snapshot','usage':{'input_tokens':10,'output_tokens':10},'output':[]})
        transport(self.payload(),'sensitive-value')
        self.assertNotIn('sensitive-value',(self.temp/'journal2.jsonl').read_text())
        self.assertEqual(transport.records[0]['returned_model'],'snapshot')

    def test_minute_bins_preserve_native_arithmetic_gap_and_component_mask(self):
        root=self.temp/'sources'
        path=root/'R1Hz/verification/17422.npz';path.parent.mkdir(parents=True)
        t=np.array([0.,1.,3.,4.])
        meter=np.array([3600.,7200.,1800.,3600.])
        comp=np.zeros((4,24));comp[:,0]=[1800,9000,3600,1800];comp[3,23]=np.nan
        np.savez(path,t=t,P=meter[:,None],control_P_online=comp,control_P_revised=comp)
        bins=minute_bins(ReplayStore(root),'R1Hz',17422,.5,4.5,5)
        row=bins['bins'][0]
        self.assertEqual(row[2],3)
        self.assertEqual(row[5],2.5)
        self.assertAlmostEqual(row[3]*row[2]/3.6e6,.0035)
        self.assertEqual(row[4],7200)
        self.assertAlmostEqual(bins['coverage_fraction'],.75)
        self.assertNotIn('energy_kwh',bins)
        self.assertNotIn('average_power_w',bins)
        self.assertNotIn('peak_power_w',bins)
        self.assertEqual(bins['label_status'],'unknown')

    def service(self,transport):
        service=WattDialogueService(registry_path=self.temp/'registry.json',env_file=self.temp/'absent.env',transport=transport)
        service.agent.settings_loader=lambda:Settings(primary_key='unit-test-token',live_call_limit=1800)
        return service

    def question(self):
        service=self.service(lambda *_:{})
        start,end=service.bounds('R1Hz',17422)
        return {'id':'example','recording':'R1Hz','block_id':'17422','split':'development','category':'numeric',
                'question':'How much energy in the first minute?', 'as_of':end, 'constraints':[],
                'request':{'tool':'get_window_summary','args':{'block_id':'17422','start':start,'end':start+60,'as_of':end}}}

    def fake_model(self,invalid=False):
        def transport(payload,key):
            items=payload['input']
            if payload.get('tools') and items[-1].get('type')!='function_call_output':
                context=json.loads(items[0]['content'])['context']
                req=context['request']
                return {'id':'toolreq','model':'snapshot','status':'completed','usage':{'input_tokens':100,'output_tokens':20},
                        'output':[{'type':'function_call','call_id':'call','name':req['tool'],'arguments':json.dumps(req['args'])}]}
            evidence=json.loads(items[-1]['output'])
            answer={'answer':'Unsupported 123 literal.' if invalid else 'The covered observations are shown separately from uncertain estimates.',
                    'evidence_ids':[evidence['evidence_id']],'label_candidates':[],'clarification':None,'comfort_notes':[]}
            return {'id':'finalreq','model':'snapshot','status':'completed','usage':{'input_tokens':120,'output_tokens':30},
                    'output':[{'type':'message','content':[{'type':'output_text','text':json.dumps(answer)}]}]}
        return transport

    def test_production_interval_honored_and_raw_rejected_output_retained(self):
        ledger=BudgetLedger(self.temp/'budget.json',self.config)
        recording=RecordingTransport(ledger,self.temp/'journal.jsonl',self.fake_model(invalid=True))
        service=self.service(recording)
        q=self.question()
        row=execute_case(q,'grounded',1,service,recording,self.config)
        self.assertTrue(row['production_fallback_used'])
        self.assertEqual(row['generated_answer']['answer'],'Unsupported 123 literal.')
        self.assertIn('123',row['raw_response_view']['answer'])
        self.assertNotIn('123',row['delivered_response']['answer'])
        self.assertEqual(row['execution_status'],'delivered_fallback')
        self.assertEqual(row['api_requests'][0]['payload']['instructions'],INSTRUCTIONS)
        requested=json.loads(row['api_requests'][0]['payload']['input'][0]['content'])['context']['request']
        self.assertEqual(requested['args']['end'],q['request']['args']['end'])
        self.assertEqual(len(row['api_requests']),2)

    def test_ablation_scope_prevents_exposing_another_block(self):
        q=self.question();q['request']['args']['block_id']='15437'
        context=ablation_context(self.service(lambda *_:{}),q)
        self.assertTrue(context['scope_denied'])
        self.assertTrue(context['evidence'][0]['scope_denied'])
        self.assertNotIn('bins',context['evidence'][0])

    def fixture(self):
        source=self.temp/'archive';store=ReplayStore(source)
        profile={'recordings':{h:{'blocks':list(blocks),'cadence_seconds':CADENCE_S[h],
                   'boundary':store.boundary(h),'model_version':store.model_version} for h,blocks in BLOCKS.items()}}
        for home,item in profile['recordings'].items():
            for block in item['blocks']:
                path=source/home/'verification'/f'{block}.npz';path.parent.mkdir(parents=True,exist_ok=True)
                step=CADENCE_S[home];t=np.arange(0,480*step,step)
                np.savez(path,t=t,P=np.full((len(t),1),3600.),control_P_online=np.zeros((len(t),24)),control_P_revised=np.zeros((len(t),24)))
        profile_path=self.temp/'profile.json';profile_path.write_text(json.dumps(profile))
        inputs=self.temp/'inputs';build_benchmark(source,inputs,source_profile=profile_path)
        # Small no-key development fixture; freeze keeps the exact selected rows.
        qpath=inputs/'dev_questions.jsonl';epath=inputs/'private/dev_expected.jsonl'
        qpath.write_text(qpath.read_text().splitlines()[0]+'\n');epath.write_text(epath.read_text().splitlines()[0]+'\n')
        mpath=inputs/'manifest.json';manifest=json.loads(mpath.read_text())
        manifest['hashes']['dev_questions.jsonl']=file_hash(qpath)
        manifest['hashes']['private/dev_expected.jsonl']=file_hash(epath)
        mpath.write_text(json.dumps(manifest))
        return source,profile_path,qpath,epath,mpath

    def test_freeze_before_calls_resume_and_changed_prompt_refused(self):
        source,profile,questions,expected,manifest=self.fixture()
        cfg=RunConfig(repeats=1,workers=1,split='development')
        output=self.temp/'run';env=self.temp/'keys.env';env.write_text('OPENAI_API_KEY=unit-test-token\n')
        arguments=dict(questions_path=questions,expected_path=expected,manifest_path=manifest,source_root=source,
                       profile_path=profile,output=output,env_file=env,config=cfg)
        report=run_evaluation(**arguments,transport=self.fake_model(),stop_after=1)
        self.assertEqual(report['run_status'],'checkpointed_stop_after')
        self.assertTrue((output/'execution_freeze.json').exists())
        self.assertEqual(report['budget_ledger']['calls'],0)
        # Resume does not repeat the completed template; model record follows.
        report=run_evaluation(**arguments,transport=self.fake_model(),stop_after=1)
        self.assertEqual(report['arms']['template']['completed_records'],1)
        self.assertEqual(report['arms']['grounded']['completed_records'],1)
        self.assertEqual(report['budget_ledger']['calls'],2)
        freeze=json.loads((output/'execution_freeze.json').read_text())
        self.assertFalse(freeze['untouched_holdout_claim'])
        self.assertNotIn('unit-test-token',(output/'execution_freeze.json').read_text())
        changed=RunConfig(repeats=1,workers=1,split='development',max_output_tokens=1000)
        with self.assertRaisesRegex(ValueError,'changed after freeze'):
            prepare_freeze(output,questions,expected,manifest,source,profile,changed)


if __name__=='__main__':
    unittest.main()
