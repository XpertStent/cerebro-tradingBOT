from fastapi import APIRouter

from app.services.market_history import (
    market_history
)


router = APIRouter(
    prefix="/history",
    tags=["Market History"]
)


@router.post("/sync/{symbol:path}")
def sync_history(
    symbol: str
):
    return market_history.ensure_history(
        symbol.upper(),
        minimum_bars=300,
        fetch_count=500
    )


@router.get("/{symbol:path}")
def get_history(
    symbol: str,
    limit: int = 20
):
    rows = market_history.get(
        symbol.upper(),
        limit=min(
            max(
                limit,
                1
            ),
            500
        )
    )

    return {
        "symbol":
            symbol.upper(),

        "count":
            len(rows),

        "last_date":
            market_history.last_date(
                symbol.upper()
            ),

        "candles":
            rows,
    }
