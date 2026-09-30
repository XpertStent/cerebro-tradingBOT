from fastapi import APIRouter, Query

from app.services.activity import activity


router = APIRouter(
    prefix="/activity",
    tags=["Activity"]
)


@router.get("/")
def activity_list(
    limit: int = Query(
        100,
        ge=1,
        le=1000
    ),
    category: str | None = None,
    level: str | None = None,
    search: str | None = None
):
    events = activity.list(
        limit=limit,
        category=category,
        level=level,
        search=search
    )

    return {
        "count": len(events),
        "events": events
    }
