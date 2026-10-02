import threading
import time

from fastapi import APIRouter, HTTPException, Query

from app.services.opend import opend


router = APIRouter(prefix="/market", tags=["Market Data"])
_search_cache = {}
_search_cache_lock = threading.Lock()
_SEARCH_CACHE_TTL = 60.0
_SEARCH_CACHE_MAX = 250


def _cached_search(query, markets, limit):
    key = (query.strip().lower(), tuple(markets), int(limit))
    now = time.monotonic()
    with _search_cache_lock:
        cached = _search_cache.get(key)
        if cached and now - cached[0] <= _SEARCH_CACHE_TTL:
            return cached[1]

    result = opend.search_symbols(query, markets=markets, limit=limit)
    with _search_cache_lock:
        if result:
            _search_cache[key] = (time.monotonic(), result)
        if len(_search_cache) > _SEARCH_CACHE_MAX:
            oldest = sorted(_search_cache.items(), key=lambda item: item[1][0])
            for stale_key, _ in oldest[: len(_search_cache) - _SEARCH_CACHE_MAX]:
                _search_cache.pop(stale_key, None)
    return result


@router.get("/search")
def search_market(
    q: str = Query(..., min_length=1),
    markets: str = Query(
        "US,HK,SH,SZ,SG,MY,JP",
        description="Comma-separated market codes"
    ),
    limit: int = Query(20, ge=1, le=50)
):
    try:
        selected_markets = [
            market.strip().upper()
            for market in markets.split(",")
            if market.strip()
        ]
        return {
            "query": q,
            "markets": selected_markets,
            "results": _cached_search(q, selected_markets, limit),
        }
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/snapshots")
def market_snapshots(
    symbols: str = Query(..., description="Comma-separated symbols, e.g. AAPL,NVDA,MSFT")
):
    try:
        requested = [symbol.strip() for symbol in symbols.split(",") if symbol.strip()]
        if not requested:
            raise HTTPException(status_code=400, detail="At least one symbol is required")
        return {"count": len(requested), "quotes": opend.get_snapshots(requested)}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/{symbol}/candles")
def market_candles(
    symbol: str,
    timeframe: str = Query("1d", description="Supported: 1m, 5m, 15m, 30m, 60m, 1d, 1w"),
    count: int = Query(100, ge=1, le=1000),
    before: str | None = Query(None, description="Exclusive candle time in the market timezone")
):
    try:
        return opend.get_candles(symbol=symbol, timeframe=timeframe, count=count, before=before)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/{symbol}")
def market_snapshot(symbol: str):
    try:
        return opend.get_snapshot(symbol)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
