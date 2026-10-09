from fastapi import APIRouter
from app.services.technical_analysis import technical_analysis

router = APIRouter(prefix="/patterns", tags=["Technical Pattern Analysis"])


@router.get("/{symbol}")
def symbol_patterns(symbol: str):
    return technical_analysis.build(symbol.upper())
