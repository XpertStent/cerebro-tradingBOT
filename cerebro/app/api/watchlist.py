from fastapi import (
    APIRouter,
    HTTPException
)

from pydantic import BaseModel

from app.services.activity import activity
from app.services.watchlist import watchlist


router = APIRouter(
    prefix="/watchlist",
    tags=["Watchlist"]
)


class WatchlistItem(BaseModel):
    symbol: str
    name: str | None = None
    market: str | None = None
    source: str = "MANUAL"
    status: str = "WATCH"
    score: float | None = None
    reason: str | None = None
    strategy_hint: str | None = None
    enabled: bool = True


@router.get("/")
def list_watchlist():
    items = watchlist.list()

    return {
        "count": len(items),
        "items": items
    }


@router.post("/")
def add_watchlist_item(
    request: WatchlistItem
):
    item = watchlist.upsert(
        symbol=request.symbol.strip(),
        name=request.name,
        market=request.market,
        source=request.source,
        status=request.status,
        score=request.score,
        reason=request.reason,
        strategy_hint=request.strategy_hint,
        enabled=request.enabled
    )

    activity.write(
        category="AI"
        if request.source.upper() == "AI"
        else "SYSTEM",
        action="WATCHLIST_UPDATED",
        message=(
            f"Added {item['symbol']} "
            f"to watchlist"
        ),
        symbol=item["symbol"]
    )

    return item


@router.delete("/{symbol:path}")
def remove_watchlist_item(
    symbol: str
):
    existing = watchlist.get(symbol)

    if not existing:
        raise HTTPException(
            status_code=404,
            detail="Watchlist item not found"
        )

    watchlist.delete(symbol)

    activity.write(
        category="SYSTEM",
        action="WATCHLIST_REMOVED",
        message=(
            f"Removed {existing['symbol']} "
            f"from watchlist"
        ),
        symbol=existing["symbol"]
    )

    return {
        "deleted": True
    }
