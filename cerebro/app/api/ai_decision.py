from copy import deepcopy

from fastapi import APIRouter, HTTPException, Query

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
    return data


@router.get("/latest")
def get_latest_decision():
    return {"result": ai_decision_jobs.latest()}


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
    result = ai_history_reset.clear_all()
    activity.write(
        category="AI",
        action="AI_HISTORY_CLEARED",
        message="Cleared AI decision history and thesis memory for testing",
        level="WARN",
        details=result,
    )
    return result


def _individual_action(run_id: str, decision_id: int, action: str):
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
        updated = ai_execution.reject(proposal, reason="Rejected individually by user")
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
    return result


@router.post("/{run_id}/proposal/{decision_id}/approve")
def approve_one_decision(run_id: str, decision_id: int):
    try:
        return _individual_action(run_id, decision_id, "approve")
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/{run_id}/proposal/{decision_id}/reject")
def reject_one_decision(run_id: str, decision_id: int):
    try:
        return _individual_action(run_id, decision_id, "reject")
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/{run_id}/approve")
def approve_decision(run_id: str):
    try:
        result = ai_decision_jobs.approve(run_id)
        activity.write(
            category="AI",
            action="AI_BATCH_APPROVED",
            message="Approved all remaining AI decisions",
            details={"run_id": run_id},
        )
        return result
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/{run_id}/reject")
def reject_decision(run_id: str):
    try:
        result = ai_decision_jobs.reject(run_id)
        activity.write(
            category="AI",
            action="AI_BATCH_REJECTED",
            message="Rejected all remaining AI decisions",
            details={"run_id": run_id},
        )
        return result
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
