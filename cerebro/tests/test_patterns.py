"""Native-library tests with synthetic prices; no broker, model or /data access."""
import ast
import json
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
from ta_patterns.chart_patterns import classic

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.services.pattern_detectors import ChartDetectors, VERSION, candle_evidence, pivots
from app.services.pattern_engine import DEFAULTS, clean_bars, pattern_engine
from app.services.technical_analysis import TechnicalAnalysisService


def bars(close=None, seed=0, count=250):
    if close is None:
        rng = np.random.default_rng(seed)
        close = 100 + np.cumsum(rng.normal(0, .8, count))
    return [{"trade_date": int((date(2024, 1, 1) + timedelta(days=i)).strftime("%Y%m%d")),
             "open": float(value), "high": float(value + .2), "low": float(value - .2),
             "close": float(value), "volume": 1000.0} for i, value in enumerate(close)]


def double_top():
    path = list(np.linspace(85, 100, 50))
    for start, end, count in ((100,120,8),(120,108,8),(108,120,8),(120,108,8),(108,103,8)):
        path.extend(np.linspace(start,end,count+1)[1:])
    return bars(path)


def quality(rows, provider="alpaca"):
    return {"fresh": True, "usable": True, "expected_complete_date": rows[-1]["trade_date"],
            "provider": provider, "feed": "sip" if provider == "alpaca" else "broker",
            "adjustment": "all", "session": "PROVIDER_AGGREGATE", "delay_minutes": 15,
            "adjustment_basis": "test-session"}


class DetectorTests(unittest.TestCase):
    def test_earlier_outputs_do_not_repaint_across_all_selected_families(self):
        for n in (2,3,5):
            cfg={**DEFAULTS,"window":40,"pivot_n":n}
            for seed in (0,1,8):
                dates, arrays=clean_bars(bars(seed=seed,count=180))
                detector=ChartDetectors(n); full=detector.scan(arrays,cfg)
                for end in (1,5,9,10,11,20,40,41,50,65,80,100,111,122,150,179):
                    pre=detector.scan(tuple(a[:end] for a in arrays),cfg)
                    for name in full:
                        np.testing.assert_array_equal(full[name][:end],pre[name],err_msg=f"{name}, seed {seed}, n {n}, end {end}")

    def test_scale_invariance_and_upstream_namespace_isolation(self):
        _, arrays=clean_bars(bars(seed=23,count=300))
        cfg={**DEFAULTS,"window":40}
        function=classic._flagpole
        detector=ChartDetectors(3); reference=detector.scan(arrays,cfg)
        for factor in (.01,100):
            scaled=tuple(a*factor for a in arrays[:4])+(arrays[4],)
            output=detector.scan(scaled,cfg)
            for name in reference:
                np.testing.assert_array_equal(reference[name],output[name],err_msg=name)
        self.assertIs(classic._flagpole,function)
        self.assertEqual(detector.classic['_flagpole'](arrays[3],10,.05,10),(-1,0))

    def test_pivots_use_real_prices_and_do_not_backfill_the_warmup(self):
        h=np.array([90,95,100,95,90,93,96,100,110,95,90,89,88],float)
        self.assertEqual(np.flatnonzero(pivots(h,2,.05)).tolist(),[4,10])
        decreasing=np.arange(20,0,-1,dtype=float)
        self.assertFalse(pivots(decreasing,5).any())
        self.assertFalse(pivots(decreasing[:10],5).any())

    def test_sloping_geometry_uses_swing_dates_but_gates_by_confirmation_dates(self):
        detector=ChartDetectors(5)
        fit=detector.classic['fit_line']
        slope,intercept,_=fit(np.array([15.,25.]),np.array([100.,110.]))
        self.assertAlmostEqual(slope*30+intercept,120.)

    def test_talib_engulfing_and_prefix_consistency(self):
        import talib
        o=np.full(40,100.);c=np.full(40,100.1);o[-2:]=[101,99];c[-2:]=[100,102]
        arrays=(o,np.maximum(o,c)+.1,np.minimum(o,c)-.1,c,np.ones(40))
        self.assertEqual(int(talib.CDLENGULFING(*arrays[:4])[-1]),100)
        dates=[str(i) for i in range(40)]
        self.assertTrue(any(e['name']=='CDLENGULFING' for e in candle_evidence(arrays,dates)))
        for name in talib.get_functions():
            if name.startswith('CDL'):
                full=getattr(talib,name)(*arrays[:4])
                for end in (15,30,39):
                    np.testing.assert_array_equal(full[:end],getattr(talib,name)(*(x[:end] for x in arrays[:4])))


class EngineTests(unittest.TestCase):
    def test_double_top_recognition_then_confirmation_without_backdating(self):
        rows=double_top();cfg={**DEFAULTS,'window':40,'breakout_atr':0}
        result=pattern_engine.analyze(rows,cfg)
        tops=[e for e in result['events'] if e['pattern']=='double_top' and e['status']=='CONFIRMED']
        self.assertTrue(tops)
        event=tops[0]
        self.assertGreater(event['recognition_date'],event['last_swing_date'])
        self.assertGreater(event['confirmation_date'],event['recognition_date'])
        recognition=next(i for i,r in enumerate(rows) if str(r['trade_date'])==event['recognition_date'].replace('-',''))
        prefix=pattern_engine.analyze(rows[:recognition+1],cfg)
        previous=next(e for e in prefix['events'] if e['id']==event['id'])
        self.assertEqual(previous['status'],'FORMING')
        self.assertIsNone(previous['confirmation_date'])
        self.assertFalse(event['orders_armed'])

    def test_invalidation_expiry_and_no_false_geometry_on_flat_history(self):
        cfg={**DEFAULTS,'window':40,'breakout_atr':0}
        rows=double_top()
        forming=pattern_engine.analyze(rows[:-8],cfg)
        event=next(e for e in forming['events'] if e['pattern']=='double_top')
        prefix=rows[:event['recognition_index']+1]
        # Append properly dated candles while preserving the recognized shape.
        def append(values):
            combined=prefix+[dict(prefix[-1],trade_date=int((date.fromisoformat(event['recognition_date'])+timedelta(days=j+1)).strftime('%Y%m%d')),open=v,high=v+.2,low=v-.2,close=v) for j,v in enumerate(values)]
            return pattern_engine.analyze(combined,cfg)
        invalid=next(e for e in append([130]*4)['events'] if e['id']==event['id'])
        self.assertEqual(invalid['status'],'INVALIDATED')
        self.assertEqual(invalid['last_evaluated_date'],invalid['invalidation_date'])
        self.assertEqual(invalid['lines'][0]['points'][-1]['date'],invalid['invalidation_date'])
        expired=next(e for e in append([110]*32)['events'] if e['id']==event['id'])
        self.assertEqual(expired['status'],'EXPIRED')
        flat=pattern_engine.analyze(bars(np.full(180,100.)),cfg)
        self.assertEqual(flat['events'],[])

    def test_invalid_history_is_rejected_without_silent_dropping(self):
        rows=bars(count=180)
        for kind in ('duplicate','nan','bad_ohlc'):
            changed=[dict(r) for r in rows]
            if kind=='duplicate':changed[10]['trade_date']=changed[9]['trade_date']
            elif kind=='nan':changed[10]['close']=float('nan')
            else:changed[10]['high']=1
            with self.assertRaises(ValueError):pattern_engine.analyze(changed,{**DEFAULTS,'window':40})


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.cfg={**DEFAULTS,'window':40};self.market=SimpleNamespace(configuration=lambda:{'provider':'alpaca'})
        self.settings=SimpleNamespace(get=lambda key,default=None:self.cfg.get(key.removeprefix('patterns.'),default))
        self.path=Path(self.temp.name)/'patterns.db'
        self.service=TechnicalAnalysisService(self.path,self.settings,self.market)
        self.rows=double_top();self.series={'bars':self.rows,'history_sync':quality(self.rows)}

    def test_cache_restart_provider_configuration_and_content_isolation(self):
        first=self.service.analyze_series('US.TEST',self.series)
        self.assertTrue(first['available'])
        restored=TechnicalAnalysisService(self.path,self.settings,self.market)
        cached=restored.analyze_series('US.TEST',self.series)
        self.assertEqual(cached['source'],'ANALYSIS_CACHE')
        other={'bars':self.rows,'history_sync':quality(self.rows,'opend')}
        self.assertEqual(restored.analyze_series('US.TEST',other)['source'],'ANALYZED')
        changed={'bars':[dict(r) for r in self.rows],'history_sync':quality(self.rows)}
        changed['bars'][-1]['volume']=2000
        self.assertEqual(restored.analyze_series('US.TEST',changed)['source'],'ANALYZED')
        self.cfg['symmetry_pct']=4
        self.assertEqual(restored.analyze_series('US.TEST',self.series)['source'],'ANALYZED')
        self.assertNotEqual(first['candle_fingerprint'],restored.analyze_series('US.TEST',changed)['candle_fingerprint'])

    def test_stale_incomplete_and_mixed_data_cannot_return_a_cached_signal(self):
        self.service.analyze_series('US.TEST',self.series)
        for change in ({'fresh':False},{'usable':False},{'expected_complete_date':20240101}):
            series={'bars':self.rows,'history_sync':{**quality(self.rows),**change}}
            self.assertFalse(self.service.analyze_series('US.TEST',series)['available'])
        mixed={'bars':[dict(r) for r in self.rows],'history_sync':quality(self.rows)}
        mixed['bars'][-1]['provider']='opend'
        self.assertFalse(self.service.analyze_series('US.TEST',mixed)['available'])
        missing={'bars':self.rows[:-1],'history_sync':quality(self.rows)}
        self.assertFalse(self.service.analyze_series('US.TEST',missing)['available'])

    def test_saved_evidence_revalidates_version_configuration_and_current_session(self):
        result=self.service.analyze_series('US.TEST',self.series)
        self.market.metrics_current=lambda symbol, metrics: metrics['data_quality']['last_cached_date']==self.rows[-1]['trade_date']
        self.assertTrue(self.service.is_current(result,'US.TEST'))
        self.assertFalse(self.service.is_current({**result,'version':'old-adapter'},'US.TEST'))
        self.assertFalse(self.service.is_current(result,'US.OTHER'))
        self.market.metrics_current=lambda symbol,metrics:False
        self.assertFalse(self.service.is_current(result,'US.TEST'))

    def test_adjustment_revision_recalculates_but_preserves_first_observation(self):
        first=self.service.analyze_series('US.TEST',self.series)
        revised={'bars':self.rows,'history_sync':{**quality(self.rows),'adjustment_basis':'new-session'}}
        second=self.service.analyze_series('US.TEST',revised)
        self.assertEqual(second['source'],'ANALYZED')
        old={e['id']:e for e in first['events']}
        self.assertTrue(second['events'])
        self.assertTrue(all(e['first_observed_at']==old[e['id']]['first_observed_at'] for e in second['events']))

    def test_observation_is_excluded_and_advisory_is_compact_and_preserves_context(self):
        result=self.service.analyze_series('US.TEST',self.series)
        self.assertIsNone(self.service.model_context(result))
        self.cfg['mode']='advisory'
        result=self.service.analyze_series('US.TEST',self.series)
        context=self.service.model_context(result)
        self.assertEqual(context['mode'],'advisory')
        self.assertLessEqual(len(context['chart_patterns']),6)
        self.assertLessEqual(len(context['candle_evidence']),16)
        self.assertIn('provenance',context)
        self.assertNotIn('lines',json.dumps(context))
        self.assertTrue(all(len(e['points'])<=6 for e in context['chart_patterns']))
        self.assertTrue(all('index' not in p for e in context['chart_patterns'] for p in e['points']))

    def test_shared_history_and_disabled_mode_does_not_fetch(self):
        calls=[]
        def history(symbol,minimum_bars):
            calls.append((symbol,minimum_bars));return {**quality(self.rows),'candles':self.rows}
        self.market.completed_history=history
        self.assertTrue(self.service.build('US.TEST')['available'])
        self.assertEqual(len(calls),1)
        self.service.analyze_series('US.TEST',self.series)
        self.assertEqual(len(calls),1)
        self.cfg['mode']='off'
        self.assertFalse(self.service.build('US.TEST')['available'])
        self.assertEqual(len(calls),1)


if __name__=='__main__':unittest.main()
