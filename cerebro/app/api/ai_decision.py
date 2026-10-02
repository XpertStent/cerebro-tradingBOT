from copy import deepcopy

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.services.proposal_review import decorate_reviews, resolution_lock, review_key, validate_batch
from app.services.live_trading_hardening import EXECUTION_LOCK
from app.services.ai_memory import ai_memory
from app.services.trading import TradeUnlockRequired

from app.services.activity import activity
from app.services.ai_decision_jobs import ai_decision_jobs
from app.services.ai_execution import ai_execution
from app.services.ai_history_reset import ai_history_reset
from app.services.latest_ai_decision import latest_ai_decision


router = APIRouter(prefix="/ai/decision", tags=["AI Decision Engine"])


@router.post("/run")
def start_decision_run(
    run_type: str = Query("MANUAL"),
    enrich_research: bool | None = Query(None),
):
    try:
        job = ai_decision_jobs.start(run_type=run_type, enrich_research=enrich_research)
        activity.write(
            category="AI",
            action="AI_WORKFLOW_STARTED",
            message=f"Started {str(run_type).upper()} AI decision workflow",
            details={
                "run_id": job.get("run_id"),
                "run_type": str(run_type).upper(),
                "enrich_research": job.get("enrich_research"),
            },
        )
        return job
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


def _audit_terminal_progress(run_id: str, data: dict):
    if data.get("status") not in {"COMPLETE", "FAILED"}:
        return
    if data.get("activity_terminal_logged"):
        return

    failed = data.get("status") == "FAILED"
    activity.write(
        category="AI",
        action="AI_WORKFLOW_FAILED" if failed else "AI_WORKFLOW_COMPLETE",
        message=(
            f"AI workflow {run_id} failed: {data.get('error') or data.get('message') or 'unknown error'}"
            if failed
            else f"AI workflow {run_id} completed at stage {data.get('stage')}"
        ),
        level="ERROR" if failed else "INFO",
        details={
            "run_id": run_id,
            "stage": data.get("stage"),
            "elapsed_seconds": data.get("elapsed_seconds"),
            "candidate_count": (data.get("ai") or {}).get("candidate_count"),
            "research_ready": (data.get("ai") or {}).get("research_ready"),
            "research_errors": (data.get("ai") or {}).get("research_errors"),
            "error": data.get("error"),
        },
    )
    ai_decision_jobs.update(run_id, activity_terminal_logged=True)
    data["activity_terminal_logged"] = True


@router.get("/progress/{run_id}")
def get_decision_progress(run_id: str):
    data = ai_decision_jobs.progress(run_id)
    if data is None:
        raise HTTPException(status_code=404, detail="AI decision run not found")
    _audit_terminal_progress(run_id, data)
    return data


@router.get("/result/{run_id}")
def get_decision_result(run_id: str):
    data = ai_decision_jobs.result(run_id)
    if data is None:
        raise HTTPException(status_code=404, detail="AI decision run not found")
    return decorate_reviews(data)


@router.get("/latest")
def get_latest_decision():
    return decorate_reviews({"result": ai_decision_jobs.latest()})


@router.delete("/latest")
def clear_latest_decision():
    result = ai_decision_jobs.clear_latest()
    activity.write(
        category="AI",
        action="AI_RESULT_CLEARED",
        message="Cleared latest AI decision result for testing",
    )
    return result


@router.delete("/history")
def clear_ai_history_for_testing():
    with resolution_lock(), EXECUTION_LOCK:
        result = ai_history_reset.clear_all()
    activity.write(
        category="AI",
        action="AI_HISTORY_CLEARED",
        message="Cleared AI decision history and thesis memory for testing",
        level="WARN",
        details=result,
    )
    return result


def _resolve_one(run_id: str, decision_id: int, action: str, reason=None, expected_review_key=None):
    latest = latest_ai_decision.load()
    if latest and latest.get("run_id") != run_id:
        raise RuntimeError("A newer AI run is available. Refresh and review its decisions.")
    payload = ai_decision_jobs.result(run_id)
    if not payload or not payload.get("result"):
        raise RuntimeError("AI run result not found")

    result = deepcopy(payload["result"])
    execution = result.get("execution") or {}
    approval_mode = str(execution.get("approval_mode") or "")
    if approval_mode not in {"MANUAL", "MANUAL_PARTIAL"}:
        raise RuntimeError("This AI run is not awaiting manual proposal decisions")

    proposals = execution.get("proposals") or []
    target_index = next(
        (
            index
            for index, proposal in enumerate(proposals)
            if int(proposal.get("decision_id") or -1) == int(decision_id)
        ),
        None,
    )
    if target_index is None:
        raise RuntimeError(f"AI proposal {decision_id} not found in run {run_id}")

    proposal = proposals[target_index]
    if expected_review_key and review_key(proposal) != expected_review_key:
        raise RuntimeError("This decision changed. Refresh and review it again.")
    memory = ai_memory.get_decision(decision_id)
    if memory and memory.get("execution_status") in {"APPROVED", "EXECUTED", "REJECTED"}:
        raise RuntimeError("This decision has already been resolved and cannot be overwritten")
    if proposal.get("status") != "PENDING_APPROVAL":
        raise RuntimeError(
            f"Proposal {decision_id} is {proposal.get('status')} and is not awaiting approval"
        )

    symbol = proposal.get("symbol")
    proposal_action = str(proposal.get("action") or "").upper()
    if action == "approve":
        updated = ai_execution.approve(proposal)
        if proposal_action == "WATCH":
            message = f"Approved WATCH for {symbol}; added to Monitored Securities"
        else:
            message = f"Approved and executed {symbol}"
        event_kind = "SUCCESS"
        audit_action = "AI_PROPOSAL_APPROVED"
    else:
        updated = ai_execution.reject(proposal, reason=(reason or "").strip() or "Rejected by user; no reason provided")
        message = (
            f"Rejected WATCH for {symbol}; watchlist unchanged"
            if proposal_action == "WATCH"
            else f"Rejected {symbol}; no order submitted"
        )
        event_kind = "INFO"
        audit_action = "AI_PROPOSAL_REJECTED"

    proposals[target_index] = updated
    execution["proposals"] = proposals
    pending = sum(1 for item in proposals if item.get("status") == "PENDING_APPROVAL")
    execution["pending_approval_count"] = pending
    execution["approval_mode"] = "MANUAL_PARTIAL" if pending else "MANUAL_RESOLVED"
    result["execution"] = execution

    latest_ai_decision.save(run_id=run_id, result=result)
    ai_decision_jobs.update(
        run_id,
        stage="AWAITING_APPROVAL" if pending else "COMPLETE",
        message=(
            f"{message}. {pending} decision(s) still awaiting approval."
            if pending
            else f"{message}. All actionable decisions are resolved."
        ),
        result=result,
    )
    ai_decision_jobs._event(
        run_id,
        "APPROVAL",
        message,
        kind=event_kind,
        symbol=symbol,
    )
    activity.write(
        category="AI",
        action=audit_action,
        message=message,
        symbol=symbol,
        order_id=str((updated.get("broker_order") or {}).get("order_id") or "") or None,
        details={
            "run_id": run_id,
            "decision_id": decision_id,
            "decision_action": proposal_action,
            "proposal_status": updated.get("status"),
            "pending_remaining": pending,
        },
    )
    return decorate_reviews(result)


class DecisionRequest(BaseModel):
    review_key: str | None = Field(None, min_length=64, max_length=64)


class RejectionRequest(DecisionRequest):
    reason: str | None = Field(None, max_length=1000)


class ReviewedProposal(BaseModel):
    decision_id: int = Field(gt=0)
    review_key: str = Field(min_length=64, max_length=64)


class BatchRequest(RejectionRequest):
    proposals: list[ReviewedProposal] = Field(min_length=1, max_length=200)


def _individual_action(run_id, decision_id, action, reason=None, expected_review_key=None):
    with resolution_lock(), EXECUTION_LOCK:
        return _resolve_one(run_id, decision_id, action, reason, expected_review_key)


def _batch_action(run_id, action, request):
    with resolution_lock(), EXECUTION_LOCK:
        payload = ai_decision_jobs.result(run_id)
        if not payload or not payload.get("result"):
            raise RuntimeError("AI run result not found")
        proposals = (payload["result"].get("execution") or {}).get("proposals") or []
        selected = validate_batch(proposals, [p.model_dump() for p in request.proposals])
        completed, failures = [], []
        for index, proposal in enumerate(selected):
            decision_id = int(proposal["decision_id"])
            try:
                _resolve_one(run_id, decision_id, action, request.reason)
                completed.append(decision_id)
            except TradeUnlockRequired:
                if not completed:
                    raise
                failures.extend({"decision_id": int(p["decision_id"]), "message": "Trading locked; unlock and review remaining actions"} for p in selected[index:])
                break
            except Exception as exc:
                failures.append({"decision_id": decision_id, "message": str(exc)})
        result = deepcopy(ai_decision_jobs.result(run_id)["result"])
        result["batch_resolution"] = {"action": action, "completed_ids": completed, "failures": failures}
        return decorate_reviews(result)


def _legacy_batch(run_id, action, reason=None):
    with resolution_lock(), EXECUTION_LOCK:
        payload = ai_decision_jobs.result(run_id)
        if not payload or not payload.get("result"):
            raise RuntimeError("AI run result not found")
        pending = [p for p in (payload["result"].get("execution") or {}).get("proposals", []) if p.get("status") == "PENDING_APPROVAL"]
        if not pending:
            raise RuntimeError("No pending decisions remain")
        request = BatchRequest(reason=reason, proposals=[ReviewedProposal(decision_id=p["decision_id"], review_key=review_key(p)) for p in pending])
        return _batch_action(run_id, action, request)


def _action_error(exc):
    if isinstance(exc, TradeUnlockRequired):
        raise HTTPException(status_code=423, detail={"code": "TRADE_UNLOCK_REQUIRED", "message": str(exc).replace("TRADE_UNLOCK_REQUIRED: ", "")}) from exc
    raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/{run_id}/proposal/{decision_id}/approve")
def approve_one_decision(run_id: str, decision_id: int, request: DecisionRequest | None = None):
    try:
        return _individual_action(run_id, decision_id, "approve", expected_review_key=request.review_key if request else None)
    except RuntimeError as exc:
        _action_error(exc)


@router.post("/{run_id}/proposal/{decision_id}/reject")
def reject_one_decision(run_id: str, decision_id: int, request: RejectionRequest | None = None):
    try:
        return _individual_action(run_id, decision_id, "reject", request.reason if request else None, request.review_key if request else None)
    except RuntimeError as exc:
        _action_error(exc)


@router.post("/{run_id}/approve")
def approve_decision(run_id: str, request: BatchRequest | None = None):
    try:
        return _batch_action(run_id, "approve", request) if request else _legacy_batch(run_id, "approve")
    except RuntimeError as exc:
        _action_error(exc)


@router.post("/{run_id}/reject")
def reject_decision(run_id: str, request: BatchRequest | None = None):
    try:
        return _batch_action(run_id, "reject", request) if request else _legacy_batch(run_id, "reject")
    except RuntimeError as exc:
        _action_error(exc)
