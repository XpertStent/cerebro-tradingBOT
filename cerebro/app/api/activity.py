import json

from fastapi import APIRouter, Query

from app.services.activity import activity
from app.services.ai_decision_jobs import ai_decision_jobs


router = APIRouter(
    prefix="/activity",
    tags=["Activity"]
)


def _matches_live(event, *, category, level, search):
    if category and str(category).upper() != "AI":
        return False
    event_level = str(event.get("kind") or "INFO").upper()
    if event_level == "SUCCESS":
        event_level = "INFO"
    if level and str(level).upper() != event_level:
        return False
    if search:
        haystack = " ".join([
            "AI",
            str(event.get("stage") or ""),
            str(event.get("message") or ""),
            str(event.get("symbol") or ""),
        ]).lower()
        if search.strip().lower() not in haystack:
            return False
    return True


def _live_ai_events(*, category=None, level=None, search=None):
    latest = ai_decision_jobs.latest()
    if not latest or latest.get("status") not in {"QUEUED", "RUNNING"}:
        return []

    run_id = latest.get("run_id")
    output = []
    for index, item in enumerate(reversed(latest.get("events") or []), start=1):
        if not _matches_live(item, category=category, level=level, search=search):
            continue
        event_level = str(item.get("kind") or "INFO").upper()
        if event_level == "SUCCESS":
            event_level = "INFO"
        output.append({
            "id": f"live:{run_id}:{index}",
            "timestamp": item.get("at"),
            "category": "AI",
            "level": event_level,
            "action": item.get("stage") or "AI_WORKFLOW",
            "message": item.get("message") or "AI workflow event",
            "symbol": item.get("symbol"),
            "order_id": None,
            "details": json.dumps({
                "live": True,
                "run_id": run_id,
                "workflow_status": latest.get("status"),
                "workflow_stage": latest.get("stage"),
                "event": item,
            }, ensure_ascii=False, default=str),
        })
    return output


@router.get("/")
def activity_list(
    limit: int = Query(100, ge=1, le=1000),
    category: str | None = None,
    level: str | None = None,
    search: str | None = None
):
    persisted = activity.list(
        limit=limit,
        category=category,
        level=level,
        search=search
    )
    live = _live_ai_events(category=category, level=level, search=search)

    # Live workflow events are prepended for observability while the run is
    # active. Persisted audit entries remain unchanged in SQLite.
    events = (live + persisted)[:limit]

    return {
        "count": len(events),
        "events": events
    }
