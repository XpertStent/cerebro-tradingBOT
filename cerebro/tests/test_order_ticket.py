"""Ticket validation and SDK mapping without a broker connection."""
import ast
import importlib.util
import json
import sqlite3
import sys
import tempfile
import threading
import unittest
import uuid
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1] / 'app/services'
spec = importlib.util.spec_from_file_location('order_ticket', ROOT / 'order_ticket.py')
ticket = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ticket)


class TicketTests(unittest.TestCase):
    def test_types_expiry_and_stop_direction(self):
        for kind in ('STOP', 'STOP_LIMIT'):
            for side, trigger in [('BUY', 110), ('SELL', 90)]:
                args = dict(mode='LIVE', side=side, order_type=kind, trigger_price=trigger,
                            market_price=100, quantity=2, time_in_force='GTC')
                if kind == 'STOP_LIMIT': args['price'] = 111 if side == 'BUY' else 89
                value = ticket.validate_ticket(**args)
                self.assertEqual(value['time_in_force'], 'GTC')
                with self.assertRaises(ValueError): ticket.validate_ticket(**{**args, 'trigger_price':100})
                with self.assertRaises(ValueError): ticket.validate_ticket(**{**args, 'mode':'PAPER'})
        self.assertEqual(ticket.validate_ticket(mode='PAPER',side='BUY',order_type='LIMIT',price=100)['price'],100)
        with self.assertRaises(ValueError): ticket.validate_ticket(mode='PAPER',side='BUY',order_type='MARKET',time_in_force='GTC')

    def test_invalid_inputs_and_conservative_reference(self):
        for value in (0, -1, float('nan'), float('inf'), None):
            with self.assertRaises(ValueError): ticket.validate_ticket(mode='LIVE',side='BUY',order_type='STOP',trigger_price=value)
        for qty in (1.1, float('nan'), float('inf')):
            with self.assertRaises(ValueError): ticket.validate_ticket(mode='LIVE',side='BUY',order_type='MARKET',quantity=qty)
        for fields in ({'price':100},{'trigger_price':100},{'time_in_force':'IOC'}):
            with self.assertRaises(ValueError): ticket.validate_ticket(mode='LIVE',side='BUY',order_type='MARKET',**fields)
        value = ticket.validate_ticket(mode='LIVE',side='SELL',order_type='STOP',trigger_price=90,market_price=100)
        self.assertEqual(value['estimated_price'],100)

    def test_sdk_conditional_mapping_and_paper_boundary(self):
        installer = next(n for n in ast.parse((ROOT/'live_trading_hardening.py').read_text()).body if isinstance(n,ast.FunctionDef) and n.name=='install_hardened_trading')
        method = next(n for n in installer.body if isinstance(n,ast.FunctionDef) and n.name=='place_order')
        hardening = Mock(); hardening.get_intent.return_value=None
        ns = dict(uuid=uuid, EXECUTION_LOCK=threading.RLock(), validate_ticket=ticket.validate_ticket,
                  ORDER_TYPES=ticket.ORDER_TYPES, hardening=hardening, RET_OK=0,
                  TrdEnv=SimpleNamespace(REAL='REAL',SIMULATE='SIMULATE'), TrdSide=SimpleNamespace(BUY='BUY',SELL='SELL'),
                  OrderType=SimpleNamespace(MARKET='MARKET',NORMAL='NORMAL',STOP='STOP',STOP_LIMIT='STOP_LIMIT'),
                  TimeInForce=SimpleNamespace(DAY='DAY',GTC='GTC'), activity=Mock(),
                  build_execution_context=lambda **kw: {'context_id':'live:test'})
        exec(compile(ast.Module(body=[method],type_ignores=[]),'ticket','exec'),ns)
        ctx=Mock(); ctx.place_order.return_value=(0,SimpleNamespace(empty=False,iloc=[{'order_id':'1'}]))
        client=SimpleNamespace(mode=lambda:'live', current_account=lambda **kw:{'account_id':'9007199254741117','security_firm':'FUTUAU'},
                               _unlocked=True, _context=lambda firm:ctx, max_tradable_quantity=Mock(return_value={'maximum':5}),
                               _map_order=lambda row,**kw:{'order_id':'1','status':'SUBMITTED'}, clear_cache=Mock())
        fake_modules={'app.services.opend':SimpleNamespace(opend=SimpleNamespace(get_snapshot=lambda symbol:{'price':100})),
                      'app.services.live_safety':SimpleNamespace(live_safety=SimpleNamespace(quote_freshness_check=lambda **kw:{'passed':True}))}
        with patch.dict(sys.modules,fake_modules):
            ns['place_order'](client,symbol='US.TEST',side='BUY',quantity=2,order_type='STOP_LIMIT',price=112,trigger_price=110,time_in_force='GTC')
        kwargs=ctx.place_order.call_args.kwargs
        self.assertEqual((kwargs['order_type'],kwargs['aux_price'],kwargs['price'],kwargs['time_in_force']),('STOP_LIMIT',110,112,'GTC'))
        self.assertFalse(kwargs['fill_outside_rth'])
        self.assertEqual(kwargs['acc_id'],9007199254741117)
        client.mode=lambda:'paper'; ctx.place_order.reset_mock()
        with self.assertRaises(ValueError): ns['place_order'](client,symbol='US.TEST',side='BUY',quantity=2,order_type='STOP',trigger_price=110)
        ctx.place_order.assert_not_called()

    def test_reused_intent_cannot_change_trigger_or_expiry(self):
        cls=next(n for n in ast.parse((ROOT/'live_trading_hardening.py').read_text()).body if isinstance(n,ast.ClassDef))
        with tempfile.TemporaryDirectory() as directory:
            ns=dict(json=json,sqlite3=sqlite3,DB_PATH=Path(directory)/'db',datetime=datetime,timezone=timezone)
            exec(compile(ast.Module(body=[cls],type_ignores=[]),'intents','exec'),ns)
            store=ns['LiveTradingHardening']()
            store.put_intent(intent_id='1',context_id='live:test',source='MANUAL',symbol='US.TEST',side='BUY',quantity=2)
            value={'order_type':'STOP','trigger_price':110,'time_in_force':'DAY'}
            store.bind_ticket('1',value); store.bind_ticket('1',value)
            for changed in ({**value,'trigger_price':111},{**value,'time_in_force':'GTC'}):
                with self.assertRaises(RuntimeError): store.bind_ticket('1',changed)
