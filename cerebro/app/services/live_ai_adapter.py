from copy import deepcopy
from types import MethodType

from app.services.activity import activity
from app.services.ai_memory import ai_memory
from app.services.ai_thesis_store import ai_theses
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
        order, fresh_risk = self._fresh_execution_order(proposal)
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
        result["message"] = f"{mode} order submitted after fresh risk validation"
        return result

    ai_execution.build = MethodType(build_with_environment, ai_execution)
    ai_execution.execute = MethodType(execute, ai_execution)
    ai_execution._live_adapter_installed = True
    return ai_execution
