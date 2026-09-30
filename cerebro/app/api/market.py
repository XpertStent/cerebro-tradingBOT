from fastapi import APIRouter, HTTPException, Query
from app.services.opend import opend

router = APIRouter(
    prefix="/market",
    tags=["Market Data"]
)


@router.get("/snapshots")
def market_snapshots(
    symbols: str = Query(
        ...,
        description="Comma-separated symbols, e.g. AAPL,NVDA,MSFT"
    )
):
    try:
        requested = [
            symbol.strip()
            for symbol in symbols.split(",")
            if symbol.strip()
        ]

        if not requested:
            raise HTTPException(
                status_code=400,
                detail="At least one symbol is required"
            )

        return {
            "count": len(requested),
            "quotes": opend.get_snapshots(requested)
        }

    except HTTPException:
        raise

    except Exception as e:
        raise HTTPException(
            status_code=503,
            detail=str(e)
        )


@router.get("/{symbol}/candles")
def market_candles(
    symbol: str,
    timeframe: str = Query(
        "1d",
        description="Supported: 1m, 5m, 15m, 30m, 60m, 1d, 1w"
    ),
    count: int = Query(
        100,
        ge=1,
        le=1000
    )
):
    try:
        return opend.get_candles(
            symbol=symbol,
            timeframe=timeframe,
            count=count
        )

    except ValueError as e:
        raise HTTPException(
            status_code=400,
            detail=str(e)
        )

    except Exception as e:
        raise HTTPException(
            status_code=503,
            detail=str(e)
        )


@router.get("/{symbol}")
def market_snapshot(symbol: str):
    try:
        return opend.get_snapshot(symbol)

    except Exception as e:
        raise HTTPException(
            status_code=503,
            detail=str(e)
        )
