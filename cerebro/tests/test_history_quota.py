import ast
import importlib.util
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1] / 'app/services'
spec = importlib.util.spec_from_file_location('history_quota', ROOT / 'history_quota.py')
quota = importlib.util.module_from_spec(spec)
spec.loader.exec_module(quota)


class HistoryQuotaTests(unittest.TestCase):
    def test_new_stocks_preserve_reserve_but_existing_stocks_can_refresh(self):
        details = [{'code': 'US.EXISTING'}]
        for remaining in (0, 10):
            with self.assertRaises(quota.HistoryQuotaReserved):
                quota.check_history_reserve('US.NEW', (290, remaining, details), 10)
            quota.check_history_reserve('us.existing', (290, remaining, details), 10)
        quota.check_history_reserve('US.NEW', (289, 11, details), 10)
        frame = SimpleNamespace(to_dict=lambda orient: details)
        quota.check_history_reserve('US.EXISTING', (300, 0, frame), 10)

    def test_invalid_broker_responses_do_not_spend_slots(self):
        for invalid in (None, (1, 2), (-1, 12, []), (1, '12', []), (1, 12, None)):
            with self.assertRaises(RuntimeError):
                quota.check_history_reserve('US.NEW', invalid, 10)

    def test_client_checks_live_quota_closes_connection_and_opt_out(self):
        cls = next(n for n in ast.parse((ROOT / 'opend.py').read_text()).body if isinstance(n, ast.ClassDef))
        method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == 'check_history_capacity')
        namespace = dict(RET_OK=0, check_history_reserve=quota.check_history_reserve)
        exec(compile(ast.Module(body=[method], type_ignores=[]), 'opend', 'exec'), namespace)
        ctx = Mock()
        ctx.get_history_kl_quota.return_value = (0, (290, 10, []))
        client = SimpleNamespace(_context=lambda: ctx, normalize_symbol=lambda s: s.upper())
        check = lambda: namespace['check_history_capacity'](client, 'US.NEW', 10)
        with self.assertRaises(quota.HistoryQuotaReserved): check()
        ctx.get_history_kl_quota.assert_called_once_with(get_detail=True)
        ctx.close.assert_called_once()
        ctx.reset_mock()
        namespace['check_history_capacity'](client, 'US.NEW', 0)
        ctx.get_history_kl_quota.assert_not_called()
        ctx.close.assert_not_called()
        ctx.get_history_kl_quota.return_value = (1, 'unavailable')
        with self.assertRaisesRegex(RuntimeError, 'quota could not be checked'): check()
        ctx.close.assert_called_once()


if __name__ == '__main__': unittest.main()
