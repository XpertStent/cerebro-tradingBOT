"""Exercise the real context builder without network, models or account storage."""
import ast
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock


class PatternContextTests(unittest.TestCase):
    def setUp(self):
        root=Path(__file__).resolve().parents[1]/'app/services'
        definitions=next(n.value for n in ast.parse((root/'settings.py').read_text()).body if isinstance(n,ast.Assign) and getattr(n.targets[0],'id','')=='DEFINITIONS')
        values={key:item['default'] for key,item in ast.literal_eval(definitions).items()}
        self.cfg={'mode':'observe'}
        self.patterns=Mock()
        self.patterns.configuration.side_effect=lambda:dict(self.cfg)
        self.patterns.is_current.side_effect=lambda result,symbol,cfg:bool(result and result.get('available') and result.get('version')=='current')
        self.patterns.build.side_effect=lambda symbol:{'symbol':symbol,'available':True,'version':'current','secret_observation':'geometry','mode':self.cfg['mode']}
        self.patterns.model_context.side_effect=lambda result:({'available':result['available'],'reason':result.get('reason'),'evidence':'advisory'} if self.cfg['mode']=='advisory' else None)
        self.patterns.unavailable.side_effect=lambda symbol,reason,cfg:{'available':False,'reason':reason,'mode':cfg['mode']}
        self.market=Mock()
        self.market.configuration.return_value={'provider':'alpaca'}
        self.market.metrics_current.return_value=True
        self.market.get_snapshots.return_value=[]
        self.saved={'symbol':'US.QUANT','metrics':{'available':True},'technical_analysis':{'available':True,'version':'current','mode':'observe','secret_observation':'saved geometry'}}
        research=Mock()
        research.research_many.return_value={}
        self.research=research
        namespace=dict(datetime=datetime,timezone=timezone,ThreadPoolExecutor=ThreadPoolExecutor,
            settings=SimpleNamespace(get=values.get,get_bool=lambda key:bool(values.get(key))),
            technical_analysis=self.patterns,market_data=self.market,
            opend=SimpleNamespace(get_market_states=lambda:[]),
            trading=SimpleNamespace(get_account_summary=lambda refresh:{'mode':'REAL','total_value':1000,'cash':200,'market_value':800},
                get_positions=lambda:[{'symbol':'US.HELD','market_value':800}],
                get_orders=lambda:[{'symbol':'US.PENDING','status':'SUBMITTED'}]),
            watchlist=SimpleNamespace(list=lambda:[{'symbol':'US.WATCH','enabled':True,'market':'US'}]),
            latest_quant=SimpleNamespace(load=lambda:{},candidates=lambda:[self.saved]),
            ai_context=SimpleNamespace(build_memory_context=lambda **kwargs:{}),ai_research_batches=research)
        cls=next(n for n in ast.parse((root/'ai_run_context.py').read_text()).body if isinstance(n,ast.ClassDef) and n.name=='AIRunContextBuilder')
        exec(compile(ast.Module(body=[cls],type_ignores=[]),'ai_run_context.py','exec'),namespace)
        self.builder=namespace['AIRunContextBuilder']()

    def test_observation_is_visible_in_progress_but_excluded_from_every_candidate(self):
        progress=Mock()
        context=self.builder.build(enrich_research=False,research_progress_callback=progress)
        self.assertEqual({c['symbol'] for c in context['candidates']},{'US.HELD','US.PENDING','US.QUANT','US.WATCH'})
        self.assertTrue(all('technical_analysis' not in c for c in context['candidates']))
        self.assertNotIn('secret_observation',str(context))
        self.assertEqual(progress.call_count,4)
        self.assertEqual(self.patterns.build.call_count,3)  # Existing quant evidence reused.
        self.assertEqual(context['portfolio']['account']['cash'],200)
        self.assertIn('max_position_pct',context['deterministic_risk_policy'])

    def test_advisory_includes_per_symbol_evidence_and_refreshes_old_adapter(self):
        self.cfg['mode']='advisory';self.saved['technical_analysis']['version']='old'
        context=self.builder.build(enrich_research=False)
        self.assertEqual(self.patterns.build.call_count,4)
        self.assertTrue(all(c['technical_analysis']['evidence']=='advisory' for c in context['candidates']))

    def test_research_session_boundary_withholds_saved_evidence(self):
        self.cfg['mode']='advisory'
        def research(*args,**kwargs):
            self.patterns.is_current.return_value=False
            self.patterns.is_current.side_effect=None
            return {}
        self.research.research_many.side_effect=research
        context=self.builder.build(enrich_research=True)
        self.assertTrue(all(not c['technical_analysis']['available'] for c in context['candidates']))
        self.assertTrue(all(c['technical_analysis']['reason']=='CURRENT_COMPLETED_HISTORY_REQUIRED' for c in context['candidates']))

    def test_disabled_mode_makes_no_pattern_history_requests(self):
        self.cfg['mode']='off'
        context=self.builder.build(enrich_research=False)
        self.patterns.build.assert_not_called()
        self.assertTrue(all('technical_analysis' not in c for c in context['candidates']))


if __name__=='__main__':unittest.main()
