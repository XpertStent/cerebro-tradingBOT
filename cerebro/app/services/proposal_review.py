"""Stable confirmation identity and serialized proposal resolution."""
import fcntl
import hashlib
import json
import threading
from contextlib import contextmanager
from pathlib import Path

_LOCK = threading.RLock()
_LOCAL = threading.local()


def review_key(proposal):
    fields = {key: proposal.get(key) for key in ("decision_id", "symbol", "action", "order", "desired_exposure_pct", "execution_context", "status")}
    return hashlib.sha256(json.dumps(fields, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


@contextmanager
def resolution_lock(path=Path("/data/ai_proposal_actions.lock")):
    # RLock serializes threads; flock also serializes independent API workers.
    with _LOCK:
        if getattr(_LOCAL, "active", False):
            yield
            return
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            _LOCAL.active = True
            try:
                yield
            finally:
                _LOCAL.active = False
                fcntl.flock(handle, fcntl.LOCK_UN)


def decorate_reviews(value):
    if not isinstance(value, dict):
        return value
    execution = value.get("execution")
    if isinstance(execution, dict):
        for proposal in execution.get("proposals") or []:
            proposal["review_key"] = review_key(proposal)
    for key in ("result",):
        if isinstance(value.get(key), dict):
            decorate_reviews(value[key])
    return value


def validate_batch(proposals, reviewed):
    pending = {int(p["decision_id"]): p for p in proposals if p.get("status") == "PENDING_APPROVAL"}
    seen = set()
    for item in reviewed:
        decision_id = int(item["decision_id"])
        if decision_id in seen:
            raise RuntimeError("Duplicate decision in batch confirmation")
        seen.add(decision_id)
        proposal = pending.get(decision_id)
        if proposal is None or review_key(proposal) != item["review_key"]:
            raise RuntimeError("The pending decision list changed. Refresh and review the remaining actions again.")
    if not seen:
        raise RuntimeError("No pending decisions selected")
    return [pending[int(item["decision_id"])] for item in reviewed]
