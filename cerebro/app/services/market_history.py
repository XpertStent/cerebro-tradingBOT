"""Compatibility API backed by the shared provider-aware candle cache."""

from app.services.market_data import market_data
from app.services.settings import settings


class MarketHistoryStore:
    def get(self, symbol, limit=None):
        count = int(settings.get("history.fetch_count")) if limit is None else limit
        expected = int(market_data.expected_date(symbol).replace("-", ""))
        return [
            row
            for row in market_data.cache.rows(market_data.key(symbol), limit=count + 1)
            if row["trade_date"] <= expected
        ][-count:]

    def count(self, symbol):
        return len(market_data.cache.rows(market_data.key(symbol)))

    def last_date(self, symbol):
        expected = int(market_data.expected_date(symbol).replace("-", ""))
        rows = [r for r in self.get(symbol) if r["trade_date"] <= expected]
        return rows[-1]["trade_date"] if rows else None

    def ensure_history(self, symbol, minimum_bars=None, fetch_count=None):
        # Fetch Count is owned by Settings; no separate hard-coded caller defaults.
        return market_data.completed_history(symbol, minimum_bars=minimum_bars)


market_history = MarketHistoryStore()
