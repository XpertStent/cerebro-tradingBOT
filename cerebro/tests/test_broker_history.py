import ast
import importlib.util
import json
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace, MethodType
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1] / 'app/services'


def module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / f'{name}.py')
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


identity = module('broker_identity')
history_module = module('broker_history')
context_module = module('execution_context')


class BrokerTests(unittest.TestCase):
    def test_integer_ids_round_trip_without_browser_precision_loss(self):
        value = 9007199254741117  # Synthetic identifier above JavaScript's safe integer range.
        parsed = json.loads(json.dumps({'account_id': identity.broker_id(value)}))
        self.assertEqual(parsed['account_id'], str(value))
        self.assertEqual(int(parsed['account_id']), value)
        with self.assertRaises(ValueError): identity.broker_id(float(value))

    def test_account_selection_preserves_id_and_permissions(self):
        parsed = ast.parse((ROOT / 'trading.py').read_text())
        cls = next(n for n in parsed.body if isinstance(n, ast.ClassDef) and n.name == 'TradingClient')
        names = {'_accounts_for_firm', '_clean', '_enum_text', '_market_list', 'select_live_account'}
        cls.body = [n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name in names]
        ns = dict(broker_id=identity.broker_id, masked_id=identity.masked_id, RET_OK=0, activity=Mock())
        exec(compile(ast.Module(body=[cls], type_ignores=[]), 'trading', 'exec'), ns)
        client = ns['TradingClient']()
        row = dict(acc_id=9007199254741117, trd_env='REAL', acc_type='CASH', acc_status='ACTIVE', trdmarket_auth=['US'], security_firm='FUTUAU', uni_card_num='12345678')
        ctx = Mock(); ctx.get_acc_list.return_value = (0, Frame([row]))
        client._context = lambda firm: ctx
        accounts = client._accounts_for_firm('FUTUAU')
        client._live_candidates = lambda refresh: accounts
        client._runtime_set = Mock(); client.clear_cache = Mock()
        account = client.select_live_account(json.loads(json.dumps(accounts))[0]['account_id'])
        self.assertEqual(account['account_id'], '9007199254741117')
        self.assertEqual(account['universal_account_masked'], '••••5678')
        client._runtime_set.assert_any_call('live_account_id', '9007199254741117')
        with self.assertRaisesRegex(RuntimeError, 'ACTIVE REAL'): client.select_live_account('9007199254741116')
        client._live_candidates = lambda refresh: []
        with self.assertRaisesRegex(RuntimeError, 'ACTIVE REAL'): client.select_live_account(account['account_id'])

    def test_persistence_ttl_failure_and_account_isolation(self):
        with tempfile.TemporaryDirectory() as directory:
            store = history_module.BrokerHistory(Path(directory) / 'orders.db')
            loader = Mock(return_value=[{'order_id': '1', 'status': 'FILLED_ALL'}])
            with patch.object(history_module.time, 'time', return_value=1000):
                orders, refreshed, stale = store.history('live:A', loader)
                store.save('live:A', orders, refreshed)
            with patch.object(history_module.time, 'time', return_value=1599):
                restored = history_module.BrokerHistory(store.path)
                self.assertEqual(restored.history('live:A', loader)[0], orders)
                self.assertEqual(loader.call_count, 1)
                self.assertEqual(restored.read('paper:A')['orders'], [])
                self.assertEqual(restored.read('live:B')['orders'], [])
            with patch.object(history_module.time, 'time', return_value=1600):
                failed = Mock(side_effect=RuntimeError('offline'))
                cached, timestamp, stale = restored.history('live:A', failed)
                self.assertTrue(stale)
                self.assertEqual(cached, orders)
                self.assertEqual(timestamp, 1000)
                restored.history('live:A', failed)
                self.assertEqual(failed.call_count, 1)

    def test_fresh_current_orders_override_saved_history(self):
        parsed = ast.parse((ROOT / 'live_trading_hardening.py').read_text())
        installer = next(n for n in parsed.body if isinstance(n, ast.FunctionDef) and n.name == 'install_hardened_trading')
        methods = [n for n in installer.body if isinstance(n, ast.FunctionDef) and n.name in {'_get_orders','get_orders','_map_order'}]
        with tempfile.TemporaryDirectory() as directory:
            store = history_module.BrokerHistory(Path(directory) / 'orders.db')
            ns = dict(broker_id=identity.broker_id, broker_history=store, EXECUTION_LOCK=threading.RLock(), RET_OK=0, datetime=datetime, timedelta=timedelta, timezone=timezone, NY=ZoneInfo('America/New_York'), TrdEnv=SimpleNamespace(REAL='REAL',SIMULATE='SIMULATE'), TrdMarket=SimpleNamespace(US='US'), build_execution_context=context_module.build_execution_context)
            exec(compile(ast.Module(body=methods, type_ignores=[]), 'history', 'exec'), ns)
            ctx = Mock()
            ctx.order_list_query.side_effect = [(0,Frame([dict(order_id=1, order_status='SUBMITTED',create_time='2026-01-02')])), (0,Frame([dict(order_id=1, order_status='FILLED_ALL',create_time='2026-01-02')]))]
            ctx.history_order_list_query.return_value = (0, Frame([dict(order_id=1, order_status='SUBMITTED',create_time='2026-01-02'),dict(order_id=2,order_status='FILLED_ALL',create_time='2026-01-01'),dict(order_id=3,order_status='SUBMITTED',create_time='2026-01-01')]))
            client = SimpleNamespace(current_account=lambda:{'account_id':'9007199254741117','security_firm':'FUTUAU'}, mode=lambda:'live', _context=lambda firm:ctx, _clean=lambda value:value, _enum_text=lambda value:str(value))
            client._map_order = MethodType(ns['_map_order'],client)
            first = ns['get_orders'](client)
            second = ns['get_orders'](client)
            self.assertEqual([order['order_id'] for order in second], ['2','1'])
            self.assertEqual(first[-1]['status'], 'SUBMITTED')
            self.assertEqual(second[-1]['status'], 'FILLED_ALL')
            self.assertEqual(ctx.order_list_query.call_count, 2)
            self.assertEqual(ctx.history_order_list_query.call_count, 1)
            self.assertEqual(ctx.order_list_query.call_args.kwargs['acc_id'], 9007199254741117)
            self.assertFalse(client._order_history_status['history_stale'])
            ctx.order_list_query.side_effect = [(1, 'broker offline')]
            with self.assertRaisesRegex(RuntimeError, 'broker offline'):
                ns['get_orders'](client)
            # Saved history cannot replace the fresh execution-safety query.
            self.assertEqual(ctx.history_order_list_query.call_count, 1)


class Frame:
    def __init__(self, rows): self.rows = rows
    def iterrows(self): return enumerate(self.rows)
