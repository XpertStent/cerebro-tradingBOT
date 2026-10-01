import ast
import math
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from zoneinfo import ZoneInfo


class Frame:
    def __init__(self, rows): self.rows = rows
    def iterrows(self): return enumerate(self.rows)


class CandleTests(unittest.TestCase):
    def client(self, responses):
        source = Path(__file__).resolve().parents[1] / 'app/services/opend.py'
        cls = next(n for n in ast.parse(source.read_text()).body if isinstance(n, ast.ClassDef))
        method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name=='get_candles')
        ns = dict(math=math, datetime=datetime, timedelta=timedelta, ZoneInfo=ZoneInfo,
                  RET_OK=0, AuType=SimpleNamespace(NONE='NONE', QFQ='QFQ'))
        exec(compile(ast.Module(body=[method], type_ignores=[]), str(source), 'exec'), ns)
        ctx = Mock(); ctx.request_history_kline.side_effect = responses
        client = SimpleNamespace(normalize_symbol=lambda s:s, TIMEFRAMES={'1m':'1m','60m':'60m','1d':'day'},
                                 _context=lambda:ctx, _clean=lambda v:v)
        return lambda **kwargs: ns['get_candles'](client, **kwargs), ctx

    def row(self, time, price):
        return dict(code='US.MU', time_key=time, open=price, high=price+1, low=price-1, close=price, volume=10)

    def test_latest_page_and_dst(self):
        old = self.row('2026-01-02 09:30:00', 189.57)
        latest = self.row('2026-09-30 15:30:00', 1065.11)
        load, ctx = self.client([(0, Frame([old]), b'next'), (0, Frame([latest]), None)])
        result = load(symbol='US.MU', timeframe='60m', count=1)
        self.assertEqual(result['candles'][0]['close'], 1065.11)
        expected = datetime(2026,9,30,15,30,tzinfo=ZoneInfo('America/New_York')).timestamp()
        self.assertEqual(result['candles'][0]['timestamp'], expected)
        self.assertEqual(ctx.request_history_kline.call_args.kwargs['page_req_key'], b'next')
        self.assertIn('start', ctx.request_history_kline.call_args.kwargs)
        ctx.close.assert_called_once()

    def test_failed_next_page_is_not_old_chart(self):
        load, ctx = self.client([(0, Frame([self.row('2026-01-02 09:30:00', 189.57)]), b'next'), (1, 'failed', None)])
        with self.assertRaisesRegex(RuntimeError, 'failed'): load(symbol='US.MU', timeframe='1m')
        ctx.close.assert_called_once()

    def test_duplicates_sort_and_symbol_guard(self):
        latest = self.row('2026-09-30 15:30:00', 1065.11)
        old = self.row('2026-09-30 14:30:00', 1064)
        load, _ = self.client([(0, Frame([latest,old,latest]), None)])
        result = load(symbol='US.MU', timeframe='60m', count=2)
        self.assertEqual([c['close'] for c in result['candles']], [1064,1065.11])
        latest['code']='US.AAPL'
        load, _ = self.client([(0,Frame([latest]),None)])
        with self.assertRaisesRegex(RuntimeError,'symbol'): load(symbol='US.MU', timeframe='60m')


if __name__ == '__main__': unittest.main()
