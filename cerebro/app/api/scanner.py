from fastapi import APIRouter, Query

from app.services.scanner import scanner


router = APIRouter(
    prefix="/scanner",
    tags=["Scanner"]
)


@router.get("/us")
def scan_us(
    limit: int = Query(
        30,
        ge=1,
        le=100
    ),
    min_price: float = 5,
    min_market_cap: float = 1_000_000_000,
    min_volume: float = 500_000
):
    return scanner.scan(
        limit=limit,
        min_price=min_price,
        min_market_cap=min_market_cap,
        min_volume=min_volume
    )
