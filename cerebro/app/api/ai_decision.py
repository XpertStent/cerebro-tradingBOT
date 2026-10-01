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


@router.get("/progress/{run_id}")
def get_decision_progress(run_id: str):
    data = ai_decision_jobs.progress(run_id)
    if data is None:
        raise HTTPException(status_code=404, detail="AI decision run not found")
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
    if action == "approve":
        updated = ai_execution.execute(proposal)
        message = f"Approved and executed {symbol}"
        event_kind = "SUCCESS"
        audit_action = "AI_PROPOSAL_APPROVED"
    else:
        updated = ai_execution.reject(proposal, reason="Rejected individually by user")
        message = f"Rejected {symbol}; no order submitted"
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
            f"{message}. {pending} proposal(s) still awaiting a decision."
            if pending
            else f"{message}. All actionable proposals are resolved."
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
        order_id=(updated.get("order") or {}).get("order_id"),
        details={
            "run_id": run_id,
            "decision_id": decision_id,
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
            message="Approved all remaining AI proposals",
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
            message="Rejected all remaining AI proposals",
            details={"run_id": run_id},
        )
        return result
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
