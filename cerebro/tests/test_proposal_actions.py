"""Approval/rejection regression tests using SQLite and a mocked broker."""
import ast
import importlib.util
import json
import sqlite3
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1] / 'app'


def module(name):
    spec=importlib.util.spec_from_file_location(name,ROOT/'services'/f'{name}.py')
    value=importlib.util.module_from_spec(spec); spec.loader.exec_module(value)
    return value


review=module('proposal_review')
latest=module('latest_ai_decision')


def load_class(filename, name, ns, methods=None):
    cls=next(n for n in ast.parse((ROOT/'services'/filename).read_text()).body if isinstance(n,ast.ClassDef) and n.name==name)
    if methods is not None: cls.body=[n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name in methods]
    exec(compile(ast.Module(body=[cls],type_ignores=[]),filename,'exec'),ns)
    return ns[name]


class ProposalTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'db'
        ns=dict(json=json,sqlite3=sqlite3,threading=threading,datetime=datetime,timezone=timezone,Path=Path,DB_PATH=self.path,_lock=threading.RLock())
        tree=ast.parse((ROOT/'services/ai_memory.py').read_text())
        for n in tree.body:
            if isinstance(n,ast.Assign) and getattr(n.targets[0],'id','').startswith('VALID_'):
                ns[n.targets[0].id]=ast.literal_eval(n.value)
        self.memory=load_class('ai_memory.py','AIMemoryStore',ns)()
        self.theses=load_class('ai_thesis_store.py','AIThesisStore',ns)()
        self.store=latest.LatestAIDecisionStore(Path(self.temp.name)/'latest.json')
        self.exec_ns=dict(deepcopy=deepcopy,ai_memory=self.memory,ai_theses=self.theses)
        self.engine=load_class('ai_execution.py','AIExecutionService',self.exec_ns,{'_persist_decision','approve','_activate_approved_thesis','reject','_fresh_execution_order'})()

    def decision(self, symbol='US.TEST'):
        return self.memory.create_decision(symbol=symbol,action='BUY',strategy='AI_PORTFOLIO',short_reason='Synthetic test',signals_snapshot={'research_context':{'status':'READY'}})['id']

    def proposal(self, decision_id, symbol='US.TEST'):
        return dict(decision_id=decision_id,symbol=symbol,action='BUY',status='PENDING_APPROVAL',thesis_update='Synthetic thesis',
                    order=dict(side='BUY',quantity=2,order_type='MARKET',estimated_price=100),execution_context={'context_id':'live:test'})

    def api(self, proposals):
        self.store.save(run_id='run',result={'execution':{'approval_mode':'MANUAL','proposals':proposals}})
        jobs=Mock(); jobs.result.side_effect=lambda run_id:{'result':deepcopy(self.store.load()['result'])}
        broker=Mock()
        def approve(proposal):
            broker(proposal['decision_id'])
            self.memory.set_execution_result(proposal['decision_id'],status='EXECUTED')
            return {**proposal,'status':'EXECUTED'}
        engine=SimpleNamespace(approve=approve,reject=self.engine.reject)
        ns=dict(deepcopy=deepcopy,latest_ai_decision=self.store,ai_decision_jobs=jobs,ai_memory=self.memory,ai_execution=engine,
                activity=Mock(),resolution_lock=lambda:review.resolution_lock(Path(self.temp.name)/'review.lock'),
                EXECUTION_LOCK=threading.RLock(),review_key=review.review_key,validate_batch=review.validate_batch,
                decorate_reviews=review.decorate_reviews,TradeUnlockRequired=type('TradeUnlockRequired',(RuntimeError,),{}))
        names={'_resolve_one','_individual_action','_batch_action'}
        functions=[n for n in ast.parse((ROOT/'api/ai_decision.py').read_text()).body if isinstance(n,ast.FunctionDef) and n.name in names]
        exec(compile(ast.Module(body=functions,type_ignores=[]),'actions','exec'),ns)
        return ns,broker

    def batch(self, proposals, reason=None):
        return SimpleNamespace(reason=reason,proposals=[SimpleNamespace(model_dump=lambda p=p:{'decision_id':p['decision_id'],'review_key':review.review_key(p)}) for p in proposals])

    def test_user_rejection_reason_and_stale_bulk_cannot_overwrite(self):
        ids=[self.decision(),self.decision('US.OTHER')]
        proposals=[self.proposal(ids[0]),self.proposal(ids[1],'US.OTHER')]
        api,broker=self.api(proposals)
        old_batch=self.batch(proposals)
        api['_individual_action']('run',ids[0],'reject','Wait for earnings')
        with self.assertRaises(RuntimeError): api['_batch_action']('run','approve',old_batch)
        broker.assert_not_called()
        stored=self.memory.get_decision(ids[0])
        self.assertEqual((stored['rejection_code'],stored['rejection_reason']),('USER_REJECTED','Wait for earnings'))
        result=api['_batch_action']('run','approve',self.batch([proposals[1]]))
        self.assertEqual(result['batch_resolution']['completed_ids'],[ids[1]])
        self.assertEqual([p['status'] for p in result['execution']['proposals']],['REJECTED','EXECUTED'])
        broker.assert_called_once_with(ids[1])
        with self.assertRaises(RuntimeError): api['_individual_action']('run',ids[0],'approve')

    def test_concurrent_updates_preserve_both_terminal_decisions(self):
        proposals=[self.proposal(self.decision()),self.proposal(self.decision('US.OTHER'),'US.OTHER')]
        api,broker=self.api(proposals)
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures=[executor.submit(api['_individual_action'],'run',p['decision_id'],'reject',f'Reason {p["decision_id"]}') for p in proposals]
            for future in futures: future.result(timeout=5)
        self.assertEqual([p['status'] for p in self.store.load()['result']['execution']['proposals']],['REJECTED','REJECTED'])
        broker.assert_not_called()

    def test_stale_individual_and_newer_run_are_blocked(self):
        p=self.proposal(self.decision()); api,broker=self.api([p])
        with self.assertRaises(RuntimeError): api['_individual_action']('run',p['decision_id'],'approve',expected_review_key='changed')
        self.store.save(run_id='newer',result={'execution':{'approval_mode':'MANUAL','proposals':[p]}})
        with self.assertRaises(RuntimeError): api['_individual_action']('run',p['decision_id'],'approve')
        broker.assert_not_called()

    def test_batch_reports_partial_completion_without_resubmitting(self):
        proposals=[self.proposal(self.decision()),self.proposal(self.decision('US.OTHER'),'US.OTHER')]
        api,broker=self.api(proposals)
        def submit(id):
            if id==proposals[1]['decision_id']: raise RuntimeError('Synthetic broker failure')
        broker.side_effect=submit
        result=api['_batch_action']('run','approve',self.batch(proposals))
        self.assertEqual(result['batch_resolution']['completed_ids'],[proposals[0]['decision_id']])
        self.assertEqual(result['batch_resolution']['failures'][0]['decision_id'],proposals[1]['decision_id'])
        self.assertEqual(result['execution']['proposals'][1]['status'],'PENDING_APPROVAL')

    def test_proposed_thesis_retained_but_activated_only_after_success(self):
        record=self.engine._persist_decision(item={'symbol':'US.TEST','action':'BUY','thesis_update':'Proposed'},context={'portfolio':{}},candidate={'quant':{'score':1}},position=None,run_id=None)
        self.assertIsNone(record['thesis_status'])
        self.assertEqual(record['signals_snapshot']['proposed_thesis'],'Proposed')
        with sqlite3.connect(self.path) as conn: self.assertEqual(conn.execute('SELECT COUNT(*) FROM ai_theses').fetchone()[0],0)
        p=self.proposal(record['id']); self.engine.execute=Mock(side_effect=RuntimeError('Locked'))
        with self.assertRaises(RuntimeError): self.engine.approve(p)
        with sqlite3.connect(self.path) as conn: self.assertEqual(conn.execute('SELECT COUNT(*) FROM ai_theses').fetchone()[0],0)
        def execute(proposal):
            self.memory.set_execution_result(proposal['decision_id'],status='EXECUTED')
            return {**proposal,'status':'EXECUTED'}
        self.engine.execute=execute; self.engine.approve(p)
        self.assertEqual(self.memory.get_decision(record['id'])['thesis_status'],'ACTIVE')
        rejected=self.proposal(self.decision('US.OTHER'),'US.OTHER'); self.engine.reject(rejected,'Prefer less exposure')
        with sqlite3.connect(self.path) as conn:
            self.assertEqual(conn.execute('SELECT symbol FROM ai_theses WHERE status="ACTIVE"').fetchall(),[('US.TEST',)])

    def test_legacy_thesis_repair_retains_history_and_restores_approved(self):
        approved=self.decision(); self.memory.set_execution_result(approved,status='EXECUTED')
        self.theses.replace_active(symbol='US.TEST',thesis='Approved',strategy='AI_PORTFOLIO',entry_decision_id=approved)
        pending=self.decision(); self.memory.set_thesis_status(pending,'ACTIVE')
        self.theses.replace_active(symbol='US.TEST',thesis='Unapproved',strategy='AI_PORTFOLIO',entry_decision_id=pending)
        self.theses.repair_unapproved_theses(); self.theses.repair_unapproved_theses()
        with sqlite3.connect(self.path) as conn:
            self.assertEqual(conn.execute('SELECT thesis,status FROM ai_theses ORDER BY id').fetchall(),[('Approved','ACTIVE'),('Unapproved','INVALIDATED')])
        self.assertIsNone(self.memory.get_decision(pending)['thesis_status'])

    def test_legacy_risk_code_normalized_without_source_column(self):
        id=self.decision(); self.memory.set_execution_result(id,status='REJECTED',rejection_code='RISK_BLOCKED',rejection_reason='Synthetic policy limit')
        self.assertEqual(self.memory.get_decision(id)['rejection_code'],'CURRENT_SET_RISK_POLICY_BLOCKED')
        with sqlite3.connect(self.path) as conn:
            conn.execute("UPDATE ai_decisions SET rejection_code='RISK_BLOCKED' WHERE id=?",(id,))
        self.memory._init_db()
        self.assertEqual(self.memory.get_decision(id)['rejection_code'],'CURRENT_SET_RISK_POLICY_BLOCKED')
        with sqlite3.connect(self.path) as conn:
            columns=[row[1] for row in conn.execute('PRAGMA table_info(ai_decisions)')]
        self.assertNotIn('rejection_source',columns)

    def test_changed_sizing_blocks_and_limit_price_remains_reviewed(self):
        p=self.proposal(self.decision()); p['desired_exposure_pct']=20
        self.engine._has_pending_order=lambda *args:False
        self.engine._price=lambda *args:100
        self.engine._size=lambda **kwargs:('BUY',3)
        self.exec_ns.update(trading=SimpleNamespace(get_orders=lambda:[],get_account_summary=lambda **kw:{'total_value':1000,'cash':1000},get_positions=lambda **kw:[]),
                            settings=SimpleNamespace(get=lambda key:'LIMIT' if key=='execution.default_order_type' else 'paper',get_bool=lambda key:True),risk=Mock())
        with self.assertRaises(RuntimeError): self.engine._fresh_execution_order(p)
        p['order'].update(order_type='LIMIT',price=99)
        self.engine._size=lambda **kwargs:('BUY',2)
        self.exec_ns['risk'].evaluate_order.return_value={'approved':True}
        order,_=self.engine._fresh_execution_order(p)
        self.assertEqual(order['price'],99)
        self.assertEqual(self.exec_ns['risk'].evaluate_order.call_args.kwargs['estimated_price'],99)
