from copy import deepcopy
from types import MethodType

from app.services.activity import activity
from app.services.ai_memory import ai_memory
from app.services.ai_thesis_store import ai_theses
from app.services.risk import risk
from app.services.settings import settings
from app.services.trading import trading


def install_live_ai_execution(ai_execution):
    """Route the mature AI proposal engine into PAPER or LIVE broker execution."""
    if getattr(ai_execution, "_live_adapter_installed", False):
        return ai_execution

    original_build = ai_execution.build

    def build_with_environment(self, *args, **kwargs):
        result = original_build(*args, **kwargs)
        mode = trading.mode().upper()
        status = trading.trading_status(refresh=False)
        result["execution_environment"] = mode
        result["account"] = status.get("account")

        if mode == "LIVE" and result.get("auto_execute") and not status.get("unlocked"):
            result["auto_execute"] = False
            result["auto_execute_deferred_for_unlock"] = True
            result["auto_execute_message"] = (
                "LIVE auto-execution was deferred because trading is locked. "
                "Unlock trading and approve the pending decisions manually."
            )
        return result

    def execute(self, proposal):
        if proposal.get("status") not in {"PENDING_APPROVAL", "APPROVED"}:
            raise RuntimeError("Proposal is not executable")
        if str(proposal.get("action") or "").upper() not in {"BUY", "ADD", "REDUCE", "SELL"}:
            raise RuntimeError("Proposal does not contain a broker-order action")

        decision_id = proposal.get("decision_id")
        order, _ = self._fresh_execution_order(proposal)

        # The mature execution service already refreshes price/account state and
        # performs risk checks. Re-run the expanded LIVE-aware guard here with
        # the full broker account fields (including available funds, sellable
        # quantity and broker-reported realized P&L) immediately before submit.
        account_summary = trading.get_account_summary(refresh=True)
        positions = trading.get_positions(refresh=True)
        position = next(
            (
                item for item in positions
                if str(item.get("symbol") or "").upper() == str(order["symbol"]).upper()
            ),
            None,
        )
        fresh_risk = risk.evaluate_order(
            trading_enabled=settings.get_bool("trading.enabled"),
            mode=trading.mode(),
            symbol=order["symbol"],
            side=order["side"],
            quantity=order["quantity"],
            estimated_price=order["estimated_price"],
            portfolio_total=float(account_summary.get("total_value") or 0),
            portfolio_cash=float(account_summary.get("cash") or 0),
            portfolio_available_cash=float(
                account_summary.get("available_cash")
                if account_summary.get("available_cash") is not None
                else account_summary.get("cash") or 0
            ),
            portfolio_market_value=float(account_summary.get("market_value") or 0),
            current_position_value=float((position or {}).get("market_value") or 0),
            current_position_qty=float((position or {}).get("quantity") or 0),
            available_position_qty=float((position or {}).get("available_quantity") or 0),
            median_turnover_60d=proposal.get("median_turnover_60d"),
            realized_pnl=account_summary.get("realized_pnl"),
        )
        if not fresh_risk.get("approved"):
            failed = [
                check.get("message")
                for check in fresh_risk.get("risk_checks") or []
                if not check.get("passed")
            ]
            raise RuntimeError("Final account-aware risk check blocked execution: " + "; ".join(failed))

        ai_memory.set_execution_result(decision_id, status="APPROVED")
        mode = trading.mode().upper()
        account = trading.current_account(refresh=True)
        broker = trading.place_order(
            symbol=order["symbol"],
            side=order["side"],
            quantity=order["quantity"],
            order_type=order["order_type"],
            price=order.get("price"),
            remark=f"CEREBRO:AI:{decision_id}",
        )
        ai_memory.set_execution_result(
            decision_id,
            status="EXECUTED",
            broker_status=str(broker.get("status")),
            order_id=str(broker.get("order_id")),
        )

        if proposal.get("action") == "SELL":
            ai_theses.close_active(
                symbol=order["symbol"],
                closing_decision_id=decision_id,
                reason=f"Position exited by AI SELL decision in {mode}",
            )

        activity.write(
            category="AI",
            action="AI_ORDER_EXECUTED",
            message=(
                f"AI decision {decision_id} executed {mode} {order['side']} "
                f"{order['quantity']} {order['symbol']}"
            ),
            symbol=order["symbol"],
            order_id=str(broker.get("order_id", "")),
            level="WARN" if mode == "LIVE" else "INFO",
            details={
                "environment": mode,
                "account_id": account.get("account_id"),
                "security_firm": account.get("security_firm"),
                "decision_id": decision_id,
                "source": "AI",
                "risk": fresh_risk,
            },
        )

        result = deepcopy(proposal)
        result["status"] = "EXECUTED"
        result["order"] = order
        result["risk"] = fresh_risk
        result["broker_order"] = broker
        result["execution_environment"] = mode
        result["message"] = f"{mode} order submitted after fresh account-aware risk validation"
        return result

    ai_execution.build = MethodType(build_with_environment, ai_execution)
    ai_execution.execute = MethodType(execute, ai_execution)
    ai_execution._live_adapter_installed = True
    return ai_execution
