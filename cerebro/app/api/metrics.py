from fastapi import APIRouter

from app.services.market_metrics import (
    market_metrics
)


router = APIRouter(
    prefix="/metrics",
    tags=["Market Metrics"]
)


@router.get("/{symbol:path}")
def symbol_metrics(
    symbol: str
):
    return market_metrics.build(
        symbol.upper()
    )
