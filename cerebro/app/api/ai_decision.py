from fastapi import APIRouter, HTTPException, Query

from app.services.ai_decision_jobs import ai_decision_jobs


router = APIRouter(
    prefix="/ai/decision",
    tags=["AI Decision Engine"],
)


@router.post("/run")
def start_decision_run(
    run_type: str = Query("MANUAL"),
    enrich_research: bool = Query(True),
):
    return ai_decision_jobs.start(
        run_type=run_type,
        enrich_research=enrich_research,
    )


@router.get("/progress/{run_id}")
def get_decision_progress(run_id: str):
    data = ai_decision_jobs.progress(run_id)
    if data is None:
        raise HTTPException(
            status_code=404,
            detail="AI decision run not found",
        )
    return data


@router.get("/result/{run_id}")
def get_decision_result(run_id: str):
    data = ai_decision_jobs.result(run_id)
    if data is None:
        raise HTTPException(
            status_code=404,
            detail="AI decision run not found",
        )
    return data
