import email.utils
import random
import re
from datetime import datetime, timezone


_RETRY_PATTERNS = (
    re.compile(
        r"(?:please\s+)?try\s+again\s+in\s+([0-9]+(?:\.[0-9]+)?)\s*"
        r"(ms|milliseconds?|s|secs?|seconds?|m|mins?|minutes?)",
        re.IGNORECASE,
    ),
    re.compile(
        r"retry\s+after\s+([0-9]+(?:\.[0-9]+)?)\s*"
        r"(ms|milliseconds?|s|secs?|seconds?|m|mins?|minutes?)",
        re.IGNORECASE,
    ),
)


def _unit_seconds(value, unit):
    unit = str(unit).lower()
    value = float(value)
    if unit.startswith("ms") or unit.startswith("millisecond"):
        return value / 1000.0
    if unit.startswith("m") and not unit.startswith("ms"):
        return value * 60.0
    return value


def _header_retry_after(exc):
    """Read Retry-After from an SDK/API exception when available."""
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None)
    if not headers:
        return None

    raw = headers.get("retry-after") or headers.get("Retry-After")
    if raw in (None, ""):
        return None

    try:
        return max(0.0, float(raw))
    except (TypeError, ValueError):
        pass

    try:
        target = email.utils.parsedate_to_datetime(str(raw))
        if target.tzinfo is None:
            target = target.replace(tzinfo=timezone.utc)
        return max(0.0, (target - datetime.now(timezone.utc)).total_seconds())
    except Exception:
        return None


def advertised_retry_after(exc):
    """Return the provider-advertised retry delay in seconds, if present.

    OpenAI rate-limit errors commonly include text such as
    `Please try again in 425ms`. We prefer the authoritative Retry-After HTTP
    header when present and otherwise parse that provider message.
    """
    header_value = _header_retry_after(exc)
    if header_value is not None:
        return header_value

    text = str(exc)
    for pattern in _RETRY_PATTERNS:
        match = pattern.search(text)
        if match:
            return max(0.0, _unit_seconds(match.group(1), match.group(2)))
    return None


def retry_delay(exc, *, attempt, base_delay=2.0, safety_seconds=1.0):
    """Choose a retry delay while respecting the provider's exact guidance.

    If OpenAI supplies a retry-after duration, Cerebro waits that duration plus
    the configured one-second safety margin. Otherwise it falls back to
    exponential backoff with small jitter for transient failures.
    """
    advertised = advertised_retry_after(exc)
    if advertised is not None:
        return advertised + float(safety_seconds), "PROVIDER_RETRY_AFTER", advertised

    fallback = float(base_delay) * (2 ** max(0, int(attempt) - 1))
    fallback += random.uniform(0.0, 1.0)
    return fallback, "EXPONENTIAL_BACKOFF", None


def is_retryable_openai_error(exc):
    text = str(exc).lower()
    markers = (
        "429",
        "rate limit",
        "rate_limit",
        "too many requests",
        "timeout",
        "timed out",
        "temporarily unavailable",
        "502",
        "503",
        "504",
        "connection reset",
        "connection error",
    )
    return any(marker in text for marker in markers)
