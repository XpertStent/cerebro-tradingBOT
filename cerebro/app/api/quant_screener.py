from fastapi import APIRouter, HTTPException, Query

from app.services.latest_quant import latest_quant
from app.services.quant_jobs import quant_jobs
from app.services.quant_screener import quant_screener


router = APIRouter(
    prefix="/quant",
    tags=["Quant Screener"],
)


@router.get("/screen")
def run_quant_screen(
    limit: int | None = Query(None, ge=5, le=100),
    per_screen: int | None = Query(None, ge=1, le=200),
    deep_limit: int | None = Query(None, ge=20, le=500),
):
    return quant_screener.run(
        final_limit=limit,
        per_screen=per_screen,
        deep_limit=deep_limit,
    )


@router.post("/run")
def start_quant_run(
    limit: int | None = Query(None, ge=5, le=100),
    per_screen: int | None = Query(None, ge=1, le=200),
    deep_limit: int | None = Query(None, ge=20, le=500),
):
    return quant_jobs.start(
        final_limit=limit,
        per_screen=per_screen,
        deep_limit=deep_limit,
    )


@router.get("/progress/{run_id}")
def get_quant_progress(run_id: str):
    data = quant_jobs.progress(run_id)
    if data is None:
        raise HTTPException(status_code=404, detail="Quant run not found")
    return data


@router.get("/result/{run_id}")
def get_quant_result(run_id: str):
    data = quant_jobs.result(run_id)
    if data is None:
        raise HTTPException(status_code=404, detail="Quant run not found")
    return data


@router.get("/latest")
def get_latest_quant():
    return {"result": latest_quant.load()}


@router.delete("/latest")
def clear_latest_quant():
    latest_quant.delete()
    return {"cleared": True}
