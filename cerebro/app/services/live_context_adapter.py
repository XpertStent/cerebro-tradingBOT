from types import MethodType

from app.services.account_fields import account_context
from app.services.execution_context import build_execution_context
from app.services.trading import trading


def install_live_context(ai_run_context):
    """Make the established AI context builder execution-environment aware."""
    if getattr(ai_run_context, "_live_context_installed", False):
        return ai_run_context

    original_risk_policy = ai_run_context._risk_policy
    original_build = ai_run_context.build

    def risk_policy(self):
        policy = original_risk_policy()
        mode = trading.mode().upper()
        policy["trading_mode"] = mode.lower()
        policy["execution_boundary"] = mode
        policy["live_trading"] = mode == "LIVE"
        policy["sizing_note"] = (
            "desired_exposure_pct is applied to the currently selected account's real total value, "
            "converted to whole shares, then constrained by current-account cash, position, invested-capital, "
            "liquidity and deterministic risk limits before broker submission. Available funds are cash-only USD capacity; do not treat market value or margin power as spendable. Sales do not replenish verified available funds until broker confirmation. daily_pnl is equity change since first observation, not realized profit."
        )
        return policy

    def build(self, *args, **kwargs):
        context = original_build(*args, **kwargs)
        account = trading.get_account_summary(refresh=False)
        mode = trading.mode().upper()
        execution_context = build_execution_context(mode=mode, account=account)

        run = context.setdefault("run", {})
        run["execution_environment"] = mode
        run["execution_context_id"] = execution_context["context_id"]

        portfolio_account = context.setdefault("portfolio", {}).setdefault("account", {})
        portfolio_account.update({
            **account_context(account),
            "mode": account.get("mode"),
            "account_id_masked": execution_context.get("account_id_masked"),
            "security_firm": execution_context.get("security_firm"),
            "execution_context_id": execution_context.get("context_id"),
            "total_value": account.get("total_value"),
            "cash": account.get("cash"),
            "available_cash": account.get("available_cash"),
            "market_value": account.get("market_value"),
        })
        return context

    ai_run_context._risk_policy = MethodType(risk_policy, ai_run_context)
    ai_run_context.build = MethodType(build, ai_run_context)
    ai_run_context._live_context_installed = True
    return ai_run_context
