"""Completed, consistently adjusted history for deterministic indicators."""

from app.services.market_data import market_data


class MarketSeries:
    def build(self, symbol, snapshot=None, market_state=None, minimum_bars=None):
        history = market_data.completed_history(symbol, minimum_bars=minimum_bars)
        if not history["usable"]:
            raise ValueError(
                history["skip_reason"]
                + ": complete current history is required for quant analysis."
            )
        return {
            "symbol": symbol,
            "history_sync": {k: v for k, v in history.items() if k != "candles"},
            "completed_bars": len(history["candles"]),
            "has_live_bar": False,
            "live_bar": None,
            "bars": history["candles"],
        }


market_series = MarketSeries()
