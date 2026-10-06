"""Exchange dates/closures, including holidays, early closes and DST."""

from datetime import datetime, timedelta, timezone
from functools import lru_cache

import exchange_calendars as calendars
import pandas as pd

NAMES = {
    "US": "XNYS",
    "HK": "XHKG",
    "SH": "XSHG",
    "SZ": "XSHG",
    "SG": "XSES",
    "MY": "XKLS",
    "JP": "XTKS",
}


@lru_cache(maxsize=16)
def calendar_for(symbol):
    market = symbol.split(".", 1)[0]
    if market not in NAMES:
        raise ValueError("No exchange calendar is configured for this market.")
    return calendars.get_calendar(NAMES[market])


def now_utc():
    return datetime.now(timezone.utc)


def latest_completed(
    symbol, now=None, delay_minutes=0, grace_minutes=15, aggregate_day=False
):
    calendar = calendar_for(symbol)
    cutoff = pd.Timestamp(now or now_utc()) - pd.Timedelta(
        minutes=delay_minutes + grace_minutes
    )
    day = cutoff.tz_convert(calendar.tz).date()
    if aggregate_day:
        # Native Alpaca daily aggregates can still receive extended-session
        # volume. Do not call that daily bar final at the regular close.
        day -= timedelta(days=1)
        return calendar.date_to_session(str(day), direction="previous").strftime(
            "%Y-%m-%d"
        )
    session = calendar.date_to_session(str(day), direction="previous")
    if calendar.session_close(session) > cutoff:
        session = calendar.previous_session(session)
    return session.strftime("%Y-%m-%d")


def is_regular_bar(symbol, timestamp):
    calendar = calendar_for(symbol)
    moment = pd.Timestamp(timestamp, unit="s", tz="UTC")
    date = str(moment.tz_convert(calendar.tz).date())
    if not calendar.is_session(date):
        return False
    if not calendar.session_open(date) <= moment < calendar.session_close(date):
        return False
    pause, resume = calendar.session_break_start(date), calendar.session_break_end(date)
    return pd.isna(pause) or not pause <= moment < resume


def adjustment_session(symbol, now=None):
    calendar = calendar_for(symbol)
    date = (now or now_utc()).astimezone(calendar.tz).date()
    return calendar.date_to_session(str(date), direction="previous").strftime(
        "%Y-%m-%d"
    )


def aggregate_regular_minutes(symbol, bars, minutes):
    """Align Alpaca hourly bars to the regular open, excluding premarket trades."""
    calendar = calendar_for(symbol)
    groups = {}
    for bar in sorted(bars, key=lambda item: item["timestamp"]):
        if not is_regular_bar(symbol, bar["timestamp"]):
            continue
        local = datetime.fromtimestamp(bar["timestamp"], calendar.tz)
        opening = int(calendar.session_open(str(local.date())).timestamp())
        bucket = (
            opening + ((bar["timestamp"] - opening) // (minutes * 60)) * minutes * 60
        )
        if bucket not in groups:
            first = dict(bar)
            first.update(
                timestamp=bucket,
                time=datetime.fromtimestamp(bucket, calendar.tz).strftime(
                    "%Y-%m-%d %H:%M:%S"
                ),
            )
            groups[bucket] = first
            continue
        current = groups[bucket]
        current["high"] = max(current["high"], bar["high"])
        current["low"] = min(current["low"], bar["low"])
        current["close"] = bar["close"]
        current["volume"] = (current.get("volume") or 0) + (bar.get("volume") or 0)
        current["turnover"] = (current.get("turnover") or 0) + (
            bar.get("turnover") or 0
        )
        current["trade_count"] = (current.get("trade_count") or 0) + (
            bar.get("trade_count") or 0
        )
        current["vwap"] = (
            current["turnover"] / current["volume"] if current["volume"] else None
        )
    return list(groups.values())


def quote_is_current(symbol, timestamp, now=None, delay_minutes=0):
    if not timestamp:
        return False
    calendar = calendar_for(symbol)
    effective = (now or now_utc()) - timedelta(minutes=delay_minutes)
    moment = datetime.fromtimestamp(float(timestamp), timezone.utc)
    if moment > effective + timedelta(minutes=2):
        return False
    day = str(effective.astimezone(calendar.tz).date())
    if calendar.is_session(day):
        opening = calendar.session_open(day).to_pydatetime()
        closing = calendar.session_close(day).to_pydatetime()
        if opening <= effective <= closing + timedelta(minutes=15):
            return moment >= max(opening, effective - timedelta(minutes=10))
    expected = latest_completed(symbol, now=effective, grace_minutes=0)
    return moment.astimezone(calendar.tz).date().isoformat() >= expected
