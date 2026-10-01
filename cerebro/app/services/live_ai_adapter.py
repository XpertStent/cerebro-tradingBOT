from copy import deepcopy
from types import MethodType

from app.services.activity import activity
from app.services.ai_memory import ai_memory
from app.services.ai_thesis_store import ai_theses
from app.services.execution_context import build_execution_context
from app.services.live_safety import live_safety
from app.services.risk import risk
from app.services.settings import settings
from app.services.trading import trading


def install_live_ai_execution(ai_execution):
    """Route the mature AI proposal engine into PAPER or LIVE broker execution."""
    if getattr(ai_execution, "_live_adapter_installed", False):
        return ai_execution

    original_build = ai_execution.build
    original_approve = ai_execution.approve

    def proposal_origin(context):
        context = context or {}
        run = context.get("run") or {}
        account = (context.get("portfolio") or {}).get("account") or {}
        return {
            "environment": str(
                run.get("execution_environment") or account.get("mode") or ""
            ).upper() or None,
            "context_id": run.get("execution_context_id") or account.get("execution_context_id"),
            "account_id_masked": account.get("account_id_masked"),
            "security_firm": account.get("security_firm"),
            "generated_at": run.get("generated_at"),
        }

    def validate_execution_context(proposal):
        origin = proposal.get("execution_context") or {}
        origin_environment = str(
            origin.get("environment") or proposal.get("origin_environment") or ""
        ).upper()
        origin_context_id = origin.get("context_id") or proposal.get("origin_execution_context_id")

        if not origin_environment or not origin_context_id:
            message = (
                "This AI proposal predates execution-context binding and cannot be approved safely. "
                "Run a new AI decision cycle in the intended PAPER/LIVE account."
            )
            activity.write(
                category="SECURITY",
                action="AI_EXECUTION_CONTEXT_MISMATCH",
                message=message,
                level="WARN",
                symbol=proposal.get("symbol"),
                details={
                    "decision_id": proposal.get("decision_id"),
                    "origin_environment": origin_environment or None,
                    "origin_context_id": origin_context_id,
                    "reason": "MISSING_ORIGIN_CONTEXT",
                },
            )
            raise RuntimeError(f"EXECUTION_CONTEXT_MISMATCH: {message}")

        current_mode = trading.mode().upper()
        current_account = trading.current_account(refresh=True)
        current = build_execution_context(mode=current_mode, account=current_account)

        if (
            current_mode != origin_environment
            or current.get("context_id") != origin_context_id
        ):
            message = (
                f"AI proposal was generated for {origin_environment} "
                f"{origin.get('account_id_masked') or 'account'} but the active execution context is "
                f"{current_mode} {current.get('account_id_masked') or 'account'}. "
                "Approval is blocked; run a new AI decision cycle for the active account."
            )
            activity.write(
                category="SECURITY",
                action="AI_EXECUTION_CONTEXT_MISMATCH",
                message=message,
                level="WARN",
                symbol=proposal.get("symbol"),
                details={
                    "decision_id": proposal.get("decision_id"),
                    "origin": origin,
                    "current": current,
                    "reason": "MODE_OR_ACCOUNT_CHANGED",
                },
            )
            raise RuntimeError(f"EXECUTION_CONTEXT_MISMATCH: {message}")

        return current

    def build_with_environment(self, *args, **kwargs):
        result = original_build(*args, **kwargs)
        context = kwargs.get("context")
        if context is None and args:
            context = args[0]
        origin = proposal_origin(context)

        # Every decision proposal, including WATCH/non-order decisions, carries
        # the exact execution environment/account identity that generated it.
        # Approval validates this identity again, preventing PAPER -> LIVE,
        # LIVE -> PAPER, or LIVE account A -> account B migration.
        for proposal in result.get("proposals") or []:
            proposal["execution_context"] = deepcopy(origin)
            proposal["origin_environment"] = origin.get("environment")
            proposal["origin_execution_context_id"] = origin.get("context_id")

        mode = origin.get("environment") or trading.mode().upper()
        status = trading.trading_status(refresh=False)
        result["execution_environment"] = mode
        result["execution_context"] = deepcopy(origin)
        result["account"] = status.get("account")

        if mode == "LIVE" and result.get("auto_execute") and not status.get("unlocked"):
            result["auto_execute"] = False
            result["auto_execute_deferred_for_unlock"] = True
            result["auto_execute_message"] = (
                "LIVE auto-execution was deferred because trading is locked. "
                "Unlock trading and approve the pending decisions manually."
            )
        return result

    def approve(self, proposal):
        # Bind every approval to the exact mode/account used to generate it.
        # Rejection remains allowed across contexts because it cannot submit a
        # broker action or mutate the active account.
        validate_execution_context(proposal)
        return original_approve(proposal)

    def execute(self, proposal):
        if proposal.get("status") not in {"PENDING_APPROVAL", "APPROVED"}:
            raise RuntimeError("Proposal is not executable")
        if str(proposal.get("action") or "").upper() not in {"BUY", "ADD", "REDUCE", "SELL"}:
            raise RuntimeError("Proposal does not contain a broker-order action")

        # Defense in depth: execute() may be called directly by internal code,
        # so enforce the binding here even when approve() was bypassed.
        validate_execution_context(proposal)

        decision_id = proposal.get("decision_id")
        order, _ = self._fresh_execution_order(proposal)

        # Re-read the real/current account immediately before submission and run
        # every account-aware deterministic check again. This deliberately uses
        # the selected execution environment rather than any PAPER-era balance.
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

        mode = trading.mode().upper()
        original_price = ((proposal.get("order") or {}).get("estimated_price"))
        safety_checks = [
            live_safety.market_hours_check(mode=mode, symbol=order["symbol"]),
            live_safety.cooldown_check(mode=mode, symbol=order["symbol"], side=order["side"]),
            live_safety.slippage_check(
                mode=mode,
                reference_price=original_price,
                current_price=order["estimated_price"],
            ),
        ]
        fresh_risk = live_safety.apply_checks(fresh_risk, safety_checks)

        if not fresh_risk.get("approved"):
            failed = [
                check.get("message")
                for check in fresh_risk.get("risk_checks") or []
                if not check.get("passed")
            ]
            activity.write(
                category="RISK",
                action="AI_EXECUTION_BLOCKED",
                message=f"Final {mode} AI execution blocked for {order['symbol']}",
                level="WARN",
                symbol=order["symbol"],
                details={
                    "environment": mode,
                    "decision_id": decision_id,
                    "failed_checks": failed,
                    "risk": fresh_risk,
                },
            )
            raise RuntimeError("Final account-aware risk check blocked execution: " + "; ".join(failed))

        account = trading.current_account(refresh=True)
        broker = trading.place_order(
            symbol=order["symbol"],
            side=order["side"],
            quantity=order["quantity"],
            order_type=order["order_type"],
            price=order.get("price"),
            remark=f"CEREBRO:AI:{decision_id}",
        )
        # Do not mark the memory record approved before place_order: when LIVE is
        # locked the request must remain retryable/pending. Record EXECUTED only
        # after OpenD has accepted the broker submission.
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
                "execution_context": proposal.get("execution_context"),
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
    ai_execution.approve = MethodType(approve, ai_execution)
    ai_execution.execute = MethodType(execute, ai_execution)
    ai_execution._live_adapter_installed = True
    return ai_execution
