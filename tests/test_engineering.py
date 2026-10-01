# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Stephen Makonin
"""Engineering invariants with no HTTP or provider required."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import tempfile
import threading
from dataclasses import replace
import unittest
from benchmark.engineering_fixtures import cases,check,service,RevisionProducer,attach_producer,FrozenRevisionView
from benchmark.run_engineering import revision_tests,canonical
from wattdialogue.adapter import ReplayStore,BLOCKS

class EngineeringTests(unittest.TestCase):
    def test_generated_workload_independent_oracle(self):
        with tempfile.TemporaryDirectory() as tmp:
            target=service(Path(tmp)); workload=cases()
            self.assertEqual(len(workload),60)
            for case in workload:
                self.assertEqual(check(case,target.query(case['payload'],case['home'])),[],case['id'])

    def test_revision_during_answer_and_comparison_negative_control(self):
        with tempfile.TemporaryDirectory() as tmp:
            results=revision_tests(Path(tmp),1)
            self.assertEqual(results['cases'],8)
            self.assertEqual(results['passed'],8)
            self.assertFalse(results['negative_control']['inflight_matches_old'])
            self.assertEqual(len(set(results['negative_control']['versions'])),2)
            self.assertTrue(results['stale_confirmation_rejected'])
            self.assertTrue(results['old_label_not_transferred'])

    def test_published_snapshot_survives_replacement(self):
        producer=RevisionProducer(); old=producer.snapshot('R1Hz',17422)
        producer.publish(1); new=producer.snapshot('R1Hz',17422)
        self.assertNotEqual(old.model_version,new.model_version)
        for mode in ('online','revised'):
            a=old.load('R1Hz',17422,mode); b=new.load('R1Hz',17422,mode)
            self.assertNotEqual(a.content_hash,b.content_hash)
            self.assertIs(a.aggregate_w,b.aggregate_w)
            with self.assertRaises(ValueError): a.components_w[0,0]=42
        with self.assertRaises(ValueError): old.snapshot('AMPds2',15431)

    def test_cache_churn_concurrent_eviction_keeps_returned_content(self):
        store=ReplayStore()
        keys=[(home,block,mode) for home,blocks in BLOCKS.items() for block in blocks for mode in ('online','revised')]
        expected={key:store.load(*key).content_hash for key in keys}
        with ThreadPoolExecutor(max_workers=8) as pool:
            actual=list(pool.map(lambda key:store.load(*key).content_hash,keys*4))
        self.assertEqual(actual,[expected[key] for key in keys*4])
        self.assertLessEqual(len(store._cache),4)

    def test_eight_inflight_queries_share_consistent_individual_snapshots(self):
        with tempfile.TemporaryDirectory() as tmp:
            target=service(Path(tmp)); producer=RevisionProducer(); attach_producer(target,producer)
            payload={'block_id':17422,'question':'compare revised consumption','mode':'local'}
            before=canonical(target.query(payload,'R1Hz'))
            arrived=threading.Barrier(9); resume=threading.Event()
            def hook(number):
                if number==1:
                    arrived.wait(timeout=10)
                    if not resume.wait(10): raise RuntimeError('Test resume timed out')
            producer.hook=hook
            with ThreadPoolExecutor(max_workers=8) as pool:
                tasks=[pool.submit(target.query,payload,'R1Hz') for _ in range(8)]
                try:
                    arrived.wait(timeout=10); producer.publish(1)
                finally:
                    resume.set()
                answers=[canonical(task.result(timeout=10)) for task in tasks]
            producer.hook=None
            self.assertEqual(answers,[before]*8)
            self.assertNotEqual(canonical(target.query(payload,'R1Hz')),before)

    def test_same_model_revision_is_pinned_and_rejects_old_confirmation(self):
        with tempfile.TemporaryDirectory() as tmp:
            target=service(Path(tmp)); producer=RevisionProducer(); attach_producer(target,producer)
            payload={'block_id':17422,'question':'compare revised consumption','mode':'local'}
            before=canonical(target.query(payload,'R1Hz')); summary=target.summary('R1Hz',17422)
            arrived,resume=threading.Event(),threading.Event()
            def hook(number):
                if number==3:
                    arrived.set()
                    if not resume.wait(10): raise RuntimeError('Test resume timed out')
            producer.hook=hook
            with ThreadPoolExecutor(max_workers=1) as pool:
                future=pool.submit(target.query,payload,'R1Hz')
                try:
                    self.assertTrue(arrived.wait(10)); producer.publish(1)
                    with producer._lock:
                        data={k:replace(v,model_version='synthetic-revision-0') for k,v in producer.current.datasets.items()}
                        metadata={**producer.current.source_metadata(),'model_version':'synthetic-revision-0'}
                        producer.current=FrozenRevisionView(data,metadata)
                finally: resume.set()
                inflight=canonical(future.result(timeout=10))
            producer.hook=None
            after=canonical(target.query(payload,'R1Hz'))
            self.assertEqual(inflight,before)
            self.assertNotEqual(after,before)
            self.assertEqual(after['evidence'][0]['model_version'],before['evidence'][0]['model_version'])
            self.assertNotEqual(after['evidence'][0]['period_a']['evidence_content_hash'],before['evidence'][0]['period_a']['evidence_content_hash'])
            with self.assertRaises(ValueError):
                target.confirm_label({'block_id':17422,'component_id':'component_000','confirm':True,'label':'Fridge',
                    'model_version':summary['model_version'],'evidence_id':summary['evidence_id']},'R1Hz')
