from fastapi import APIRouter

from app.services.market_history import (
    market_history
)
from app.services.market_data import market_data


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
            1000
        )
    )

    return {
        **market_data.provenance(symbol.upper()),
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
