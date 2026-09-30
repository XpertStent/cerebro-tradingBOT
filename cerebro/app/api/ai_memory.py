from typing import Any

from fastapi import (
    APIRouter,
    HTTPException,
    Query
)

from pydantic import BaseModel

from app.services.ai_memory import (
    ai_memory
)


router = APIRouter(
    prefix="/ai",
    tags=["AI Memory"]
)


class RunCreate(BaseModel):
    run_type: str
    scheduled_for: str | None = None
    model: str | None = None
    notes: str | None = None


class DecisionCreate(BaseModel):
    run_id: int | None = None
    symbol: str
    action: str
    strategy: str | None = None
    confidence: float | None = None
    target_allocation_pct: float | None = None

    short_reason: str
    what_changed: str | None = None
    thesis_status: str | None = None
    invalidation: str | None = None

    market_context: dict[str, Any] | None = None
    portfolio_context: dict[str, Any] | None = None
    signals_snapshot: dict[str, Any] | None = None


class ExecutionResult(BaseModel):
    status: str

    rejection_code: str | None = None
    rejection_reason: str | None = None

    broker_status: str | None = None
    order_id: str | None = None


class ThesisCreate(BaseModel):
    symbol: str
    thesis: str
    strategy: str | None = None
    invalidation: str | None = None
    entry_decision_id: int | None = None


@router.post("/runs")
def create_run(
    request: RunCreate
):
    return ai_memory.create_run(
        run_type=request.run_type,
        scheduled_for=request.scheduled_for,
        model=request.model,
        notes=request.notes
    )


@router.get("/runs")
def list_runs(
    limit: int = Query(
        100,
        ge=1,
        le=1000
    )
):
    return {
        "runs": ai_memory.list_runs(
            limit=limit
        )
    }


@router.post("/decisions")
def create_decision(
    request: DecisionCreate
):
    try:
        return ai_memory.create_decision(
            run_id=request.run_id,
            symbol=request.symbol,
            action=request.action,
            strategy=request.strategy,
            confidence=request.confidence,
            target_allocation_pct=(
                request.target_allocation_pct
            ),
            short_reason=(
                request.short_reason
            ),
            what_changed=(
                request.what_changed
            ),
            thesis_status=(
                request.thesis_status
            ),
            invalidation=(
                request.invalidation
            ),
            market_context=(
                request.market_context
            ),
            portfolio_context=(
                request.portfolio_context
            ),
            signals_snapshot=(
                request.signals_snapshot
            )
        )

    except ValueError as e:
        raise HTTPException(
            status_code=400,
            detail=str(e)
        )


@router.get("/decisions")
def list_decisions(
    symbol: str | None = None,
    execution_status: str | None = None,
    limit: int = Query(
        100,
        ge=1,
        le=1000
    )
):
    return {
        "decisions":
            ai_memory.list_decisions(
                symbol=symbol,
                execution_status=(
                    execution_status
                ),
                limit=limit
            )
    }


@router.patch(
    "/decisions/{decision_id}/execution"
)
def set_execution_result(
    decision_id: int,
    request: ExecutionResult
):
    existing = ai_memory.get_decision(
        decision_id
    )

    if not existing:
        raise HTTPException(
            status_code=404,
            detail="AI decision not found"
        )

    try:
        return ai_memory.set_execution_result(
            decision_id,
            status=request.status,
            rejection_code=(
                request.rejection_code
            ),
            rejection_reason=(
                request.rejection_reason
            ),
            broker_status=(
                request.broker_status
            ),
            order_id=request.order_id
        )

    except ValueError as e:
        raise HTTPException(
            status_code=400,
            detail=str(e)
        )


@router.get("/rejections")
def recent_rejections(
    symbol: str | None = None,
    limit: int = Query(
        20,
        ge=1,
        le=100
    )
):
    return {
        "rejections":
            ai_memory.get_recent_rejections(
                symbol=symbol,
                limit=limit
            )
    }


@router.post("/theses")
def create_thesis(
    request: ThesisCreate
):
    return (
        ai_memory.create_or_replace_thesis(
            symbol=request.symbol,
            thesis=request.thesis,
            strategy=request.strategy,
            invalidation=(
                request.invalidation
            ),
            entry_decision_id=(
                request.entry_decision_id
            )
        )
    )


@router.get("/theses")
def list_theses(
    status: str | None = None,
    limit: int = Query(
        100,
        ge=1,
        le=1000
    )
):
    return {
        "theses":
            ai_memory.list_theses(
                status=status,
                limit=limit
            )
    }


@router.get(
    "/theses/{symbol:path}/active"
)
def active_thesis(
    symbol: str
):
    thesis = (
        ai_memory.get_active_thesis(
            symbol
        )
    )

    if not thesis:
        raise HTTPException(
            status_code=404,
            detail="No active thesis"
        )

    return thesis


from app.services.ai_context import ai_context


@router.get("/context/{symbol:path}")
def symbol_context(
    symbol: str,
    decision_limit: int = Query(
        10,
        ge=1,
        le=50
    ),
    rejection_limit: int = Query(
        10,
        ge=1,
        le=50
    )
):
    return ai_context.build_symbol_context(
        symbol=symbol,
        decision_limit=decision_limit,
        rejection_limit=rejection_limit
    )
