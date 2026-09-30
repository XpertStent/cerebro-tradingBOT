from fastapi import (
    APIRouter,
    Query
)

from app.services.quant_screener import (
    quant_screener
)


router = APIRouter(
    prefix="/quant",
    tags=["Quant Screener"]
)


@router.get("/screen")
def run_quant_screen(
    limit: int = Query(
        25,
        ge=5,
        le=25
    ),

    per_screen: int = Query(
        40,
        ge=10,
        le=60
    ),

    deep_limit: int = Query(
        60,
        ge=20,
        le=100
    )
):
    return quant_screener.run(
        final_limit=limit,
        per_screen=per_screen,
        deep_limit=deep_limit
    )


from fastapi import HTTPException

from app.services.quant_jobs import (
    quant_jobs
)


@router.post("/run")
def start_quant_run(
    limit: int = 25,
    per_screen: int = 40,
    deep_limit: int = 60
):
    return quant_jobs.start(
        final_limit=limit,
        per_screen=per_screen,
        deep_limit=deep_limit
    )


@router.get("/progress/{run_id}")
def get_quant_progress(
    run_id: str
):
    data = quant_jobs.progress(
        run_id
    )

    if data is None:
        raise HTTPException(
            status_code=404,
            detail="Quant run not found"
        )

    return data


@router.get("/result/{run_id}")
def get_quant_result(
    run_id: str
):
    data = quant_jobs.result(
        run_id
    )

    if data is None:
        raise HTTPException(
            status_code=404,
            detail="Quant run not found"
        )

    return data
