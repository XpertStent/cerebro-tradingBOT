import importlib.util
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.services.account_fields import securities_funds, position_pnl


class FundsTests(unittest.TestCase):
    def test_screenshot_reconciliation(self):
        funds = securities_funds(dict(usd_assets=1806.27, us_cash=78.07,
                                      usd_net_cash_power=78.07, market_val=1728.20,
                                      power=5000, available_funds=9999))
        self.assertAlmostEqual(funds['total_value'], funds['cash'] + funds['market_value'])
        self.assertEqual(funds['available_cash'], 78.07)
        rows = [dict(profit_loss=p, unrealized_pnl=p, today_pnl=t)
                for p, t in [(-1.90, -.52), (139.90, 6.89), (-3.18, .34), (.90, 1.54)]]
        pnl = position_pnl(rows)
        self.assertEqual(pnl['position_pnl'], 135.72)
        self.assertEqual(pnl['unrealized_pnl'], 135.72)
        self.assertEqual(pnl['today_position_pnl'], 8.25)
        self.assertIsNone(pnl['realized_pnl'])

    def test_zero_missing_and_margin(self):
        for power, expected in [(0, 0), (20, 20), (2000, 78.07), (-1, 0), (None, None), (float('nan'), None)]:
            self.assertEqual(securities_funds(dict(us_cash=78.07, usd_net_cash_power=power))['available_cash'], expected)
        self.assertIsNone(position_pnl([dict(profit_loss=None)])['position_pnl'])
        self.assertIsNone(position_pnl([dict(profit_loss=10)])['unrealized_pnl'])

    def test_live_risk_funds_and_equity_loss(self):
        values = {'risk.max_order_value': 1000, 'risk.max_daily_loss': 10,
                  'risk.max_position_pct': 100, 'risk.max_invested_pct': 100,
                  'risk.min_cash_reserve_pct': 0, 'risk.max_order_adv_pct': 1}
        fake = SimpleNamespace(settings=SimpleNamespace(get=lambda k: values[k], get_bool=lambda k: True))
        with patch.dict(sys.modules, {'app.services.settings': fake}):
            spec = importlib.util.spec_from_file_location('risk_under_test', Path(__file__).resolve().parents[1] / 'app/services/risk.py')
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        args = dict(trading_enabled=True, mode='LIVE', symbol='US.AAPL', side='BUY', quantity=1,
                    estimated_price=30, portfolio_total=1806.27, portfolio_cash=78.07,
                    portfolio_market_value=1728.20, current_position_value=0)
        for available, approved in [(20, False), (78.07, True), (None, False), (0, False)]:
            self.assertEqual(module.risk.evaluate_order(**args, portfolio_available_cash=available)['approved'], approved)
        result = module.risk.evaluate_order(**args, portfolio_available_cash=78.07, daily_equity_pnl=-11, realized_pnl=500)
        self.assertFalse(result['approved'])
        self.assertTrue(any(c['name']=='daily_equity_loss_guard' and not c['passed'] for c in result['risk_checks']))


if __name__ == '__main__':
    unittest.main()
