from fastapi import APIRouter, HTTPException, Query

from app.services.ai_decision_jobs import ai_decision_jobs


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
