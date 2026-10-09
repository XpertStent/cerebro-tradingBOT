"""Broker history limits, kept separate from trading permissions."""


class HistoricalCandleQuotaError(RuntimeError):
    code = "HISTORICAL_CANDLE_QUOTA_EXHAUSTED"


class HistoryQuotaReserved(RuntimeError):
    code = "HISTORICAL_CANDLE_QUOTA_RESERVED"


def is_history_quota_error(message):
    text = str(message).lower()
    return "quota" in text and ("historical" in text or "k-line" in text or "kline" in text)


def check_history_reserve(symbol, quota, reserve):
    """Allow already-counted stocks; keep remaining new-stock slots for charts.

    OpenD returns (used_quota, remain_quota, detail_list). Details may be a
    DataFrame or a list of records, depending on the SDK version.
    """
    if not isinstance(quota, (tuple, list)) or len(quota) < 3:
        raise RuntimeError("OpenD returned an invalid historical candle quota response.")
    used, remaining, details = quota[:3]
    if not isinstance(used, int) or not isinstance(remaining, int) or min(used, remaining) < 0:
        raise RuntimeError("OpenD returned invalid historical candle quota counts.")
    if hasattr(details, "to_dict"):
        details = details.to_dict("records")
    if not isinstance(details, (list, tuple)):
        raise RuntimeError("OpenD returned invalid historical candle quota details.")
    counted = {str(row.get("code", "")).upper() for row in details if isinstance(row, dict)}
    if symbol.upper() not in counted and remaining <= reserve:
        raise HistoryQuotaReserved(
            f"Historical analysis skipped: OpenD has {remaining} new-stock candle slots remaining; "
            f"{reserve} are reserved for manually opened charts. Existing stock history can still refresh."
        )
