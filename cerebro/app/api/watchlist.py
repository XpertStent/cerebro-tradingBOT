from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services.activity import activity
from app.services.opend import opend
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


def _quote_change(snapshot):
    if not snapshot:
        return None, None
    price = snapshot.get("price")
    previous = snapshot.get("previous_close")
    try:
        price = float(price)
        previous = float(previous)
    except (TypeError, ValueError):
        return None, None
    if previous == 0:
        return price - previous, None
    change = price - previous
    return change, change / previous * 100.0


@router.get("/")
def list_watchlist():
    items = watchlist.list()
    symbols = [item.get("symbol") for item in items if item.get("symbol")]
    snapshots = {}
    quote_error = None

    if symbols:
        try:
            snapshots = {
                str(row.get("symbol") or "").upper(): row
                for row in opend.get_snapshots(symbols)
                if row.get("symbol")
            }
        except Exception as exc:
            # The persistent watchlist must remain available even if market data
            # is briefly unavailable. Quote status is surfaced separately.
            quote_error = str(exc)

    enriched = []
    for item in items:
        row = dict(item)
        quote = snapshots.get(str(item.get("symbol") or "").upper())
        if quote:
            change, change_pct = _quote_change(quote)
            row["quote"] = {
                **quote,
                "change": change,
                "change_pct": change_pct,
            }
        else:
            row["quote"] = None
        enriched.append(row)

    return {
        "count": len(enriched),
        "items": enriched,
        "quote_status": "READY" if quote_error is None else "UNAVAILABLE",
        "quote_error": quote_error,
    }


@router.post("/")
def add_watchlist_item(request: WatchlistItem):
    symbol = opend.normalize_symbol(request.symbol.strip())
    item = watchlist.upsert(
        symbol=symbol,
        name=request.name,
        market=request.market or symbol.split(".", 1)[0],
        source=request.source,
        status=request.status,
        score=request.score,
        reason=request.reason,
        strategy_hint=request.strategy_hint,
        enabled=request.enabled
    )

    activity.write(
        category="AI" if request.source.upper() == "AI" else "SYSTEM",
        action="WATCHLIST_UPDATED",
        message=f"Added {item['symbol']} to watchlist",
        symbol=item["symbol"],
        details=f"source={request.source}; status={request.status}"
    )

    return item


@router.delete("/{symbol:path}")
def remove_watchlist_item(symbol: str):
    existing = watchlist.get(symbol)

    if not existing:
        raise HTTPException(status_code=404, detail="Watchlist item not found")

    watchlist.delete(symbol)

    activity.write(
        category="SYSTEM",
        action="WATCHLIST_REMOVED",
        message=f"Removed {existing['symbol']} from watchlist",
        symbol=existing["symbol"]
    )

    return {"deleted": True}
