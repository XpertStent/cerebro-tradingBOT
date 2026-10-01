from copy import deepcopy

from fastapi import APIRouter, HTTPException, Query

from app.services.ai_decision_jobs import ai_decision_jobs
from app.services.ai_execution import ai_execution
from app.services.ai_history_reset import ai_history_reset
from app.services.latest_ai_decision import latest_ai_decision


router = APIRouter(
    prefix="/ai/decision",
    tags=["AI Decision Engine"],
)


@router.post("/run")
def start_decision_run(
    run_type: str = Query("MANUAL"),
    enrich_research: bool | None = Query(None),
):
    try:
        return ai_decision_jobs.start(
            run_type=run_type,
            enrich_research=enrich_research,
        )
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
    return {
        "result": ai_decision_jobs.latest(),
    }


@router.delete("/latest")
def clear_latest_decision():
    return ai_decision_jobs.clear_latest()


@router.delete("/history")
def clear_ai_history_for_testing():
    """Clear persistent AI decision/thesis memory for explicit test resets."""
    return ai_history_reset.clear_all()


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

    if action == "approve":
        updated = ai_execution.execute(proposal)
        message = f"Approved and executed {proposal.get('symbol')}"
        event_kind = "SUCCESS"
    else:
        updated = ai_execution.reject(
            proposal,
            reason="Rejected individually by user",
        )
        message = f"Rejected {proposal.get('symbol')}; no order submitted"
        event_kind = "INFO"

    proposals[target_index] = updated
    execution["proposals"] = proposals

    pending = sum(
        1 for item in proposals
        if item.get("status") == "PENDING_APPROVAL"
    )
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
        symbol=proposal.get("symbol"),
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


# Backward-compatible batch endpoints. CerebroUI intentionally uses the
# per-proposal endpoints above so approving one idea never approves the batch.
@router.post("/{run_id}/approve")
def approve_decision(run_id: str):
    try:
        return ai_decision_jobs.approve(run_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/{run_id}/reject")
def reject_decision(run_id: str):
    try:
        return ai_decision_jobs.reject(run_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
