from fastapi import APIRouter, HTTPException, Query

from app.services.quant_screener import quant_screener
from app.services.quant_jobs import quant_jobs


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
    """Synchronous scan.

    Omitted query parameters use the Settings registry. ``per_screen`` is a
    compatibility override that intentionally forces the same Top-N on every
    discovery screen; normally each screen uses its own configured Top-N.
    """
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
        raise HTTPException(
            status_code=404,
            detail="Quant run not found",
        )
    return data


@router.get("/result/{run_id}")
def get_quant_result(run_id: str):
    data = quant_jobs.result(run_id)
    if data is None:
        raise HTTPException(
            status_code=404,
            detail="Quant run not found",
        )
    return data
