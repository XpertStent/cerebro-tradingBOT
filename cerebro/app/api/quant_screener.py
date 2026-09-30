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
