from typing import Any

from fastapi import (
    APIRouter,
    HTTPException
)

from pydantic import BaseModel, Field

from app.services.activity import activity
from app.services.strategies import strategies


router = APIRouter(
    prefix="/strategies",
    tags=["Strategies"]
)


class StrategyCreate(BaseModel):
    name: str
    strategy_type: str
    symbol: str
    timeframe: str = "1d"
    parameters: dict[str, Any] = Field(
        default_factory=dict
    )


class StrategyToggle(BaseModel):
    enabled: bool


@router.get("/")
def list_strategies():
    data = strategies.list()

    return {
        "count": len(data),
        "strategies": data
    }


@router.post("/")
def create_strategy(
    request: StrategyCreate
):
    strategy = strategies.create(
        name=request.name.strip(),
        strategy_type=(
            request.strategy_type
            .strip()
            .upper()
        ),
        symbol=(
            request.symbol
            .strip()
            .upper()
        ),
        timeframe=request.timeframe,
        parameters=request.parameters
    )

    activity.write(
        category="STRATEGY",
        action="STRATEGY_CREATED",
        message=(
            f"Created strategy "
            f"{strategy['name']} "
            f"for {strategy['symbol']}"
        ),
        symbol=strategy["symbol"]
    )

    return strategy


@router.patch("/{strategy_id}/enabled")
def toggle_strategy(
    strategy_id: int,
    request: StrategyToggle
):
    existing = strategies.get(
        strategy_id
    )

    if not existing:
        raise HTTPException(
            status_code=404,
            detail="Strategy not found"
        )

    strategy = strategies.set_enabled(
        strategy_id,
        request.enabled
    )

    activity.write(
        category="STRATEGY",
        action=(
            "STRATEGY_ENABLED"
            if request.enabled
            else "STRATEGY_DISABLED"
        ),
        message=(
            f"{'Enabled' if request.enabled else 'Disabled'} "
            f"strategy {strategy['name']}"
        ),
        symbol=strategy["symbol"]
    )

    return strategy


@router.delete("/{strategy_id}")
def delete_strategy(
    strategy_id: int
):
    existing = strategies.get(
        strategy_id
    )

    if not existing:
        raise HTTPException(
            status_code=404,
            detail="Strategy not found"
        )

    strategies.delete(
        strategy_id
    )

    activity.write(
        category="STRATEGY",
        action="STRATEGY_DELETED",
        message=(
            f"Deleted strategy "
            f"{existing['name']}"
        ),
        symbol=existing["symbol"]
    )

    return {
        "deleted": True
    }
