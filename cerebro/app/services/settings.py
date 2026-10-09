import json
import os
import sqlite3
import threading
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path


DB_PATH = Path("/data/cerebro.db")
_lock = threading.RLock()


# Central registry for operator-configurable behaviour.
# Defaults intentionally mirror the current stable build.
DEFINITIONS = {
    # General / trading
    "trading.enabled": {
        "section": "General",
        "subsection": "Trading",
        "label": "Trading Enabled",
        "type": "boolean",
        "default": True,
        "description": "Master execution enable switch.",
    },
    "trading.mode": {
        "section": "General",
        "subsection": "Trading",
        "label": "Trading Mode",
        "type": "enum",
        "default": "paper",
        "options": ["paper", "live"],
        "description": "Broker execution environment.",
    },
    "market.default": {
        "section": "General",
        "subsection": "Market",
        "label": "Default Market",
        "type": "enum",
        "default": "US",
        "options": ["US"],
        "description": "Primary market for discovery and trading.",
    },

    # API credentials are grouped separately from model configuration.
    "openai.api_key": {
        "section": "API KEYS",
        "subsection": "OpenAI",
        "label": "OpenAI API Key",
        "type": "secret",
        "default": None,
        "env": "OPENAI_API_KEY",
        "description": "Write-only OpenAI API credential. Existing values are never returned to the browser.",
    },
    "alpaca.api_key": {
        "section": "API KEYS",
        "subsection": "Alpaca",
        "label": "Alpaca API Key ID",
        "type": "secret",
        "default": None,
        "description": "API Key ID for US market data. Select the source in Data & Quality. Trading remains with Moomoo.",
    },
    "alpaca.secret_key": {
        "section": "API KEYS",
        "subsection": "Alpaca",
        "label": "Alpaca Secret Key",
        "type": "secret",
        "default": None,
        "description": "Secret paired with the Alpaca API Key ID. Stored on the server and never returned to the browser.",
    },

    # Model configuration
    "ai.research.enabled": {
        "section": "AI & Models",
        "subsection": "Research",
        "label": "AI Web Research Enabled",
        "type": "boolean",
        "default": True,
        "description": "Enable evidence-gathering web research for decision candidates.",
    },
    "ai.research.model": {
        "section": "AI & Models",
        "subsection": "Research",
        "label": "Research / News Model",
        "type": "string",
        "default": "gpt-5.6-luna",
        "env": "OPENAI_RESEARCH_MODEL",
        "description": "Model used for company/news/event research. Separate from the portfolio decision model.",
    },
    "ai.decision.model": {
        "section": "AI & Models",
        "subsection": "Decision Model",
        "label": "Decision-Making Model",
        "type": "string",
        "default": "gpt-5.6-luna",
        "description": "Model reserved for final portfolio decisions in the next phase.",
        "future": True,
    },
    "ai.research.reasoning_effort": {
        "section": "AI & Models",
        "subsection": "Research",
        "label": "Research Reasoning Effort",
        "type": "enum",
        "default": "medium",
        "options": ["low", "medium", "high"],
        "description": "Reasoning effort sent to the research model.",
    },
    "ai.decision.reasoning_effort": {
        "section": "AI & Models",
        "subsection": "Decision Model",
        "label": "Decision Reasoning Effort",
        "type": "enum",
        "default": "high",
        "options": ["low", "medium", "high"],
        "description": "Reasoning effort reserved for the final portfolio decision model.",
        "future": True,
    },
    "ai.research.max_workers": {
        "section": "AI & Models",
        "subsection": "Research",
        "label": "Concurrent Research Requests",
        "type": "integer",
        "default": 12,
        "min": 1,
        "max": 50,
        "env": "AI_RESEARCH_MAX_WORKERS",
        "description": "Maximum symbols researched concurrently.",
    },
    "ai.research.cache_ttl_seconds": {
        "section": "AI & Models",
        "subsection": "Research",
        "label": "Research Cache TTL",
        "type": "integer",
        "default": 3600,
        "min": 0,
        "max": 86400,
        "unit": "seconds",
        "description": "How long a matching research result remains reusable.",
    },
    "ai.research.search_context_size": {
        "section": "AI & Models",
        "subsection": "Research",
        "label": "Web Search Context Size",
        "type": "enum",
        "default": "medium",
        "options": ["low", "medium", "high"],
        "description": "Web-search context size supplied to the research model.",
    },

    # Independent snapshot discovery screens
    "discovery.daily_momentum.enabled": {
        "section": "Quant & Discovery",
        "subsection": "Discovery Screens",
        "label": "Daily Momentum Screen",
        "type": "boolean",
        "default": True,
    },
    "discovery.daily_momentum.top_n": {
        "section": "Quant & Discovery",
        "subsection": "Discovery Screens",
        "label": "Daily Momentum Top N",
        "type": "integer",
        "default": 40,
        "min": 1,
        "max": 200,
    },
    "discovery.volume_surge.enabled": {
        "section": "Quant & Discovery",
        "subsection": "Discovery Screens",
        "label": "Volume Surge Screen",
        "type": "boolean",
        "default": True,
    },
    "discovery.volume_surge.top_n": {
        "section": "Quant & Discovery",
        "subsection": "Discovery Screens",
        "label": "Volume Surge Top N",
        "type": "integer",
        "default": 40,
        "min": 1,
        "max": 200,
    },
    "discovery.turnover_rate.enabled": {
        "section": "Quant & Discovery",
        "subsection": "Discovery Screens",
        "label": "Turnover Rate Screen",
        "type": "boolean",
        "default": True,
    },
    "discovery.turnover_rate.top_n": {
        "section": "Quant & Discovery",
        "subsection": "Discovery Screens",
        "label": "Turnover Rate Top N",
        "type": "integer",
        "default": 40,
        "min": 1,
        "max": 200,
    },
    "discovery.liquidity.enabled": {
        "section": "Quant & Discovery",
        "subsection": "Discovery Screens",
        "label": "Liquidity Screen",
        "type": "boolean",
        "default": True,
    },
    "discovery.liquidity.top_n": {
        "section": "Quant & Discovery",
        "subsection": "Discovery Screens",
        "label": "Liquidity Top N",
        "type": "integer",
        "default": 40,
        "min": 1,
        "max": 200,
    },
    "discovery.near_52w_high.enabled": {
        "section": "Quant & Discovery",
        "subsection": "Discovery Screens",
        "label": "Near 52-Week High Screen",
        "type": "boolean",
        "default": True,
    },
    "discovery.near_52w_high.top_n": {
        "section": "Quant & Discovery",
        "subsection": "Discovery Screens",
        "label": "Near 52-Week High Top N",
        "type": "integer",
        "default": 40,
        "min": 1,
        "max": 200,
    },
    "discovery.consensus_bonus": {
        "section": "Quant & Discovery",
        "subsection": "Discovery Screens",
        "label": "Cross-Screen Consensus Bonus",
        "type": "number",
        "default": 0.30,
        "min": 0,
        "max": 5,
        "description": "Bonus added for every additional independent discovery screen that selects the same symbol.",
    },
    "discovery.union_pool": {
        "section": "Quant & Discovery",
        "subsection": "Run Size",
        "label": "Discovery Union Pool",
        "type": "integer",
        "default": 200,
        "min": 20,
        "max": 1000,
        "description": "Maximum deduplicated snapshot candidates retained before historical analysis.",
    },
    "quant.deep_limit": {
        "section": "Quant & Discovery",
        "subsection": "Run Size",
        "label": "Historical Deep-Analysis Pool",
        "type": "integer",
        "default": 60,
        "min": 20,
        "max": 500,
        "description": "Maximum discovery candidates sent through expensive historical analysis.",
    },
    "quant.final_limit": {
        "section": "Quant & Discovery",
        "subsection": "Run Size",
        "label": "Final Quant Results",
        "type": "integer",
        "default": 25,
        "min": 5,
        "max": 100,
    },
    "quant.min_price": {
        "section": "Quant & Discovery",
        "subsection": "Universe Filters",
        "label": "Minimum Price",
        "type": "number",
        "default": 5.0,
        "min": 0,
        "max": 10000,
        "unit": "USD",
    },
    "quant.min_market_cap": {
        "section": "Quant & Discovery",
        "subsection": "Universe Filters",
        "label": "Minimum Market Cap",
        "type": "number",
        "default": 1000000000,
        "min": 0,
        "max": 10000000000000,
        "unit": "USD",
    },
    "quant.min_current_turnover": {
        "section": "Quant & Discovery",
        "subsection": "Liquidity",
        "label": "Minimum Current / Projected Turnover",
        "type": "number",
        "default": 5000000,
        "min": 0,
        "max": 10000000000,
        "unit": "USD",
    },
    "quant.min_median_turnover": {
        "section": "Quant & Discovery",
        "subsection": "Liquidity",
        "label": "Minimum 60-Day Median Turnover",
        "type": "number",
        "default": 5000000,
        "min": 0,
        "max": 10000000000,
        "unit": "USD",
    },
    "quant.benchmark_symbol": {
        "section": "Quant & Discovery",
        "subsection": "Advanced",
        "label": "Relative-Strength Benchmark",
        "type": "string",
        "default": "US.SPY",
    },
    "quant.snapshot_batch_size": {
        "section": "Quant & Discovery",
        "subsection": "Advanced",
        "label": "Snapshot Batch Size",
        "type": "integer",
        "default": 400,
        "min": 10,
        "max": 1000,
    },
    "quant.rate_limit_retry_seconds": {
        "section": "Quant & Discovery",
        "subsection": "Advanced",
        "label": "Moomoo Rate-Limit Retry Delay",
        "type": "integer",
        "default": 31,
        "min": 1,
        "max": 300,
        "unit": "seconds",
    },

    # Final ensemble factor weights
    "quant.factor_weights.momentum": {
        "section": "Quant & Discovery", "subsection": "Factor Weights", "label": "Momentum Weight", "type": "number", "default": 0.22, "min": 0, "max": 1, "weight_group": "quant.factor_weights"
    },
    "quant.factor_weights.trend": {
        "section": "Quant & Discovery", "subsection": "Factor Weights", "label": "Trend Weight", "type": "number", "default": 0.22, "min": 0, "max": 1, "weight_group": "quant.factor_weights"
    },
    "quant.factor_weights.relative_strength": {
        "section": "Quant & Discovery", "subsection": "Factor Weights", "label": "Relative Strength Weight", "type": "number", "default": 0.18, "min": 0, "max": 1, "weight_group": "quant.factor_weights"
    },
    "quant.factor_weights.breakout": {
        "section": "Quant & Discovery", "subsection": "Factor Weights", "label": "Breakout Weight", "type": "number", "default": 0.12, "min": 0, "max": 1, "weight_group": "quant.factor_weights"
    },
    "quant.factor_weights.volume": {
        "section": "Quant & Discovery", "subsection": "Factor Weights", "label": "Volume Weight", "type": "number", "default": 0.10, "min": 0, "max": 1, "weight_group": "quant.factor_weights"
    },
    "quant.factor_weights.volatility_quality": {
        "section": "Quant & Discovery", "subsection": "Factor Weights", "label": "Volatility Quality Weight", "type": "number", "default": 0.08, "min": 0, "max": 1, "weight_group": "quant.factor_weights"
    },
    "quant.factor_weights.overextension_quality": {
        "section": "Quant & Discovery", "subsection": "Factor Weights", "label": "Overextension Quality Weight", "type": "number", "default": 0.08, "min": 0, "max": 1, "weight_group": "quant.factor_weights"
    },

    # Advanced raw factor composition
    "quant.momentum_weights.return_10d": {
        "section": "Advanced Quant Model", "subsection": "Momentum", "label": "10-Day Return Weight", "type": "number", "default": 0.10, "min": 0, "max": 1, "weight_group": "quant.momentum_weights"
    },
    "quant.momentum_weights.return_20d": {
        "section": "Advanced Quant Model", "subsection": "Momentum", "label": "20-Day Return Weight", "type": "number", "default": 0.25, "min": 0, "max": 1, "weight_group": "quant.momentum_weights"
    },
    "quant.momentum_weights.return_50d": {
        "section": "Advanced Quant Model", "subsection": "Momentum", "label": "50-Day Return Weight", "type": "number", "default": 0.20, "min": 0, "max": 1, "weight_group": "quant.momentum_weights"
    },
    "quant.momentum_weights.return_60d": {
        "section": "Advanced Quant Model", "subsection": "Momentum", "label": "60-Day Return Weight", "type": "number", "default": 0.25, "min": 0, "max": 1, "weight_group": "quant.momentum_weights"
    },
    "quant.momentum_weights.return_120d": {
        "section": "Advanced Quant Model", "subsection": "Momentum", "label": "120-Day Return Weight", "type": "number", "default": 0.20, "min": 0, "max": 1, "weight_group": "quant.momentum_weights"
    },
    "quant.relative_strength_weights.return_20d": {
        "section": "Advanced Quant Model", "subsection": "Relative Strength", "label": "20-Day Relative Strength Weight", "type": "number", "default": 0.30, "min": 0, "max": 1, "weight_group": "quant.relative_strength_weights"
    },
    "quant.relative_strength_weights.return_60d": {
        "section": "Advanced Quant Model", "subsection": "Relative Strength", "label": "60-Day Relative Strength Weight", "type": "number", "default": 0.40, "min": 0, "max": 1, "weight_group": "quant.relative_strength_weights"
    },
    "quant.relative_strength_weights.return_120d": {
        "section": "Advanced Quant Model", "subsection": "Relative Strength", "label": "120-Day Relative Strength Weight", "type": "number", "default": 0.30, "min": 0, "max": 1, "weight_group": "quant.relative_strength_weights"
    },
    "quant.confidence.bullish_factor_threshold": {
        "section": "Advanced Quant Model", "subsection": "Signal Confidence", "label": "Bullish Factor Threshold", "type": "number", "default": 60, "min": 0, "max": 100
    },
    "quant.confidence.factor_average_weight": {
        "section": "Advanced Quant Model", "subsection": "Signal Confidence", "label": "Factor Average Contribution", "type": "number", "default": 0.55, "min": 0, "max": 1, "weight_group": "quant.confidence_weights"
    },
    "quant.confidence.agreement_weight": {
        "section": "Advanced Quant Model", "subsection": "Signal Confidence", "label": "Agreement Contribution", "type": "number", "default": 0.45, "min": 0, "max": 1, "weight_group": "quant.confidence_weights"
    },
    "quant.volume_ratio_cap": {
        "section": "Advanced Quant Model", "subsection": "Volume", "label": "Volume Ratio Cap", "type": "number", "default": 5.0, "min": 1, "max": 100
    },

    # Shared chart, quant and AI market-data configuration.
    "data.provider": {
        "section": "Data & Quality", "subsection": "Market Data", "label": "Market Data Provider",
        "type": "enum", "default": "opend", "options": ["opend", "alpaca"],
        "option_labels": {"opend": "OpenD (Moomoo)", "alpaca": "Alpaca"},
        "description": "Source for candles and market prices. Alpaca supports US stocks; account data, security fundamentals and order execution remain with OpenD. Provider caches remain separate.",
    },
    "data.adjustment": {
        "section": "Data & Quality", "subsection": "Market Data", "label": "Historical Price Adjustment",
        "type": "enum", "default": "adjusted", "options": ["adjusted", "raw"],
        "description": "Shared by charts and quant metrics. Adjusted uses OpenD QFQ or Alpaca all corporate-action adjustments. Adjusted caches are fully refreshed at each new trading date and completed exchange session. Quotes and execution prices remain raw.",
    },
    "alpaca.feed": {
        "section": "Data & Quality", "subsection": "Alpaca", "label": "Alpaca Stock Feed",
        "type": "enum", "default": "sip", "options": ["sip", "iex"],
        "description": "SIP covers US exchanges; IEX covers one exchange and has different volumes. Feed caches are isolated.",
    },
    "alpaca.delay_minutes": {
        "section": "Data & Quality", "subsection": "Alpaca", "label": "SIP Data Delay",
        "type": "enum", "default": "15", "options": ["15", "0"], "unit": "minutes",
        "option_labels": {"15": "15 minutes (free SIP)", "0": "Real-time SIP (subscription)"},
        "description": "Use 15 for free historical SIP data and delayed SIP snapshots. Set 0 only with real-time SIP entitlement. Delayed prices are clearly labelled and are not execution prices.",
    },
    "alpaca.requests_per_minute": {
        "section": "Data & Quality", "subsection": "Alpaca", "label": "Alpaca Request Limit",
        "type": "integer", "default": 180, "min": 1, "max": 180, "unit": "requests/minute",
        "description": "Shared request pacing for every history page and snapshot batch, below the Basic 200/minute limit. Provider Retry-After and reset headers apply additional cooldowns.",
    },
    "data.cache_ttl_seconds": {
        "section": "Data & Quality", "subsection": "History", "label": "Latest Candle Cache Refresh",
        "type": "integer", "default": 30, "min": 15, "max": 600, "unit": "seconds",
        "description": "Minimum interval between on-demand refreshes of the same candle series. Earlier chart pages are also saved in the persistent provider cache.",
    },
    # Metrics / data quality
    "metrics.minimum_history_bars": {
        "section": "Data & Quality", "subsection": "History", "label": "Minimum Usable Metric History", "type": "integer", "default": 60, "min": 20, "max": 500
    },
    "history.chart_quota_reserve": {
        "section": "Quant & Discovery",
        "subsection": "Run Size",
        "label": "Historical Candle Slots Reserved for Charts",
        "type": "integer",
        "default": 10,
        "min": 0,
        "max": 1000,
        "description": "Stop automatic history downloads for new stocks at this remaining OpenD quota. Already-counted stocks and cached history remain usable. Set 0 to disable the reserve.",
    },
    "history.minimum_completed_bars": {
        "section": "Data & Quality", "subsection": "History", "label": "Required Completed Bars", "type": "integer", "default": 300, "min": 60, "max": 1000
    },
    "history.fetch_count": {
        "section": "Data & Quality", "subsection": "History", "label": "History Fetch Count", "type": "integer", "default": 500, "min": 60, "max": 1000
    },
    "metrics.max_invalid_ohlc_bars": {
        "section": "Data & Quality", "subsection": "Validation", "label": "Maximum Invalid OHLC Bars", "type": "integer", "default": 2, "min": 0, "max": 20
    },
    "metrics.stale_unchanged_sessions": {
        "section": "Data & Quality", "subsection": "Validation", "label": "Stale Series Unchanged Sessions", "type": "integer", "default": 8, "min": 1, "max": 20
    },
    "metrics.discontinuity_abs_threshold_pct": {
        "section": "Data & Quality", "subsection": "Event Review", "label": "Extreme Move Absolute Threshold", "type": "number", "default": 35.0, "min": 1, "max": 500, "unit": "%"
    },
    "metrics.discontinuity_multiple_threshold": {
        "section": "Data & Quality", "subsection": "Event Review", "label": "Extreme Move Typical-Move Multiple", "type": "number", "default": 8.0, "min": 1, "max": 100, "unit": "x"
    },
    "metrics.discontinuity_baseline_floor_pct": {
        "section": "Data & Quality", "subsection": "Event Review", "label": "Typical-Move Baseline Floor", "type": "number", "default": 0.25, "min": 0.01, "max": 10, "unit": "%"
    },

    # AI context / memory
    "ai.context.max_candidates": {
        "section": "AI & Models", "subsection": "Context & Memory", "label": "Context Soft Candidate Target", "type": "integer", "default": 30, "min": 5, "max": 200
    },
    "ai.context.recent_decisions_per_symbol": {
        "section": "AI & Models", "subsection": "Context & Memory", "label": "Recent Decisions Per Symbol", "type": "integer", "default": 5, "min": 0, "max": 100
    },
    "ai.context.recent_rejections_per_symbol": {
        "section": "AI & Models", "subsection": "Context & Memory", "label": "Recent Rejections Per Symbol", "type": "integer", "default": 5, "min": 0, "max": 100
    },
    "ai.context.include_watchlist": {
        "section": "AI & Models", "subsection": "Context & Memory", "label": "Fill Spare Context With Watchlist", "type": "boolean", "default": True
    },

    # Risk / execution
    "risk.enabled": {
        "section": "Risk & Execution", "subsection": "Risk", "label": "Risk Engine Enabled", "type": "boolean", "default": True
    },
    "risk.max_order_value": {
        "section": "Risk & Execution", "subsection": "Risk", "label": "Maximum Order Value", "type": "number", "default": 1000.0, "min": 0, "max": 100000000, "unit": "USD"
    },
    "risk.max_daily_loss": {
        "section": "Risk & Execution", "subsection": "Risk", "label": "Maximum Daily Loss", "type": "number", "default": 250.0, "min": 0, "max": 100000000, "unit": "USD", "description": "Configured now; enforcement will be completed with the decision/execution engine.", "future": True
    },
    "risk.max_position_pct": {
        "section": "Risk & Execution", "subsection": "Portfolio Limits", "label": "Maximum Single Position", "type": "number", "default": 15.0, "min": 0, "max": 100, "unit": "%", "future": True
    },
    "risk.max_invested_pct": {
        "section": "Risk & Execution", "subsection": "Portfolio Limits", "label": "Maximum Invested Capital", "type": "number", "default": 90.0, "min": 0, "max": 100, "unit": "%", "future": True
    },
    "risk.min_cash_reserve_pct": {
        "section": "Risk & Execution", "subsection": "Portfolio Limits", "label": "Minimum Cash Reserve", "type": "number", "default": 10.0, "min": 0, "max": 100, "unit": "%", "future": True
    },
    "risk.max_new_positions_per_run": {
        "section": "Risk & Execution", "subsection": "Portfolio Limits", "label": "Maximum New Positions Per Run", "type": "integer", "default": 3, "min": 0, "max": 100, "future": True
    },
    "risk.max_order_adv_pct": {
        "section": "Risk & Execution", "subsection": "Liquidity Risk", "label": "Maximum Order / ADV", "type": "number", "default": 2.0, "min": 0.01, "max": 100, "unit": "%", "future": True
    },
    "execution.auto_execute": {
        "section": "Risk & Execution", "subsection": "Execution", "label": "Automatic Execution", "type": "boolean", "default": False, "future": True
    },
    "execution.require_preview": {
        "section": "Risk & Execution", "subsection": "Execution", "label": "Require Order Preview", "type": "boolean", "default": True, "future": True
    },
    "execution.default_order_type": {
        "section": "Risk & Execution", "subsection": "Execution", "label": "Default Order Type", "type": "enum", "default": "MARKET", "options": ["MARKET", "LIMIT"], "future": True
    },
    "execution.max_slippage_pct": {
        "section": "Risk & Execution", "subsection": "Execution", "label": "Maximum Slippage", "type": "number", "default": 0.5, "min": 0, "max": 20, "unit": "%", "future": True
    },
    "execution.cooldown_minutes": {
        "section": "Risk & Execution", "subsection": "Execution", "label": "Symbol Action Cooldown", "type": "integer", "default": 30, "min": 0, "max": 10080, "unit": "minutes", "future": True
    },

    # Automation reserved for final decision scheduler
    "automation.enabled": {
        "section": "Automation", "subsection": "AI Cycles", "label": "Scheduled AI Cycles Enabled", "type": "boolean", "default": False, "future": True
    },
    "automation.market_hours_only": {
        "section": "Automation", "subsection": "AI Cycles", "label": "Market Hours Only", "type": "boolean", "default": True, "future": True
    },
    "automation.run_quant_before_cycle": {
        "section": "Automation", "subsection": "AI Cycles", "label": "Run Quant Before AI Cycle", "type": "boolean", "default": True, "future": True
    },
    "automation.cycle_times_et": {
        "section": "Automation", "subsection": "AI Cycles", "label": "Cycle Times (ET)", "type": "string", "default": "10:00,13:00,15:30", "description": "Comma-separated Eastern Time run times.", "future": True
    },

    "patterns.mode": {
        "section": "Technical Patterns", "subsection": "Analysis", "label": "Pattern Analysis Mode",
        "type": "enum", "default": "observe", "options": ["off", "observe", "advisory"],
        "option_labels": {"off": "Off", "observe": "Observation only", "advisory": "AI advisory"},
        "description": "Completed daily candles only. Observation displays and stores evidence without sending it to AI or changing quant scores. Advisory includes compact per-symbol evidence in decision input. Neither mode arms orders or changes risk limits.",
    },
    "patterns.pivot_n": {"section": "Technical Patterns", "subsection": "Geometry", "label": "Pivot Confirmation Delay", "type": "integer", "default": 3, "min": 2, "max": 10, "unit": "completed candles", "description": "A swing requires this many following completed candles. Signals are dated at recognition, never backdated to the swing."},
    "patterns.window": {"section": "Technical Patterns", "subsection": "Geometry", "label": "Chart Pattern Window", "type": "integer", "default": 120, "min": 40, "max": 400, "unit": "candles", "description": "Rolling shape window. Flags use up to 30 candles; pennants up to 15. History Fetch Count remains the shared history setting."},
    "patterns.swing_pct": {"section": "Technical Patterns", "subsection": "Geometry", "label": "Minimum Swing Change", "type": "number", "default": 0, "min": 0, "max": 30, "unit": "%", "description": "Filter same-kind pivots using actual swing prices. Zero disables this filter."},
    "patterns.symmetry_pct": {"section": "Technical Patterns", "subsection": "Geometry", "label": "Peak / Shoulder Symmetry Tolerance", "type": "number", "default": 5, "min": 0.1, "max": 20, "unit": "%"},
    "patterns.separation": {"section": "Technical Patterns", "subsection": "Geometry", "label": "Minimum Swing Separation", "type": "integer", "default": 6, "min": 2, "max": 30, "unit": "candles"},
    "patterns.flat_slope": {"section": "Technical Patterns", "subsection": "Geometry", "label": "Flat Boundary Slope Tolerance", "type": "number", "default": 0.02, "min": 0.001, "max": 0.2, "description": "Price units per candle after scaling the first history close to 100. Keeps identical scaled shapes consistent."},
    "patterns.min_pole_pct": {"section": "Technical Patterns", "subsection": "Confirmation", "label": "Minimum Flagpole Move", "type": "number", "default": 5, "min": 1, "max": 100, "unit": "%"},
    "patterns.breakout_atr": {"section": "Technical Patterns", "subsection": "Confirmation", "label": "Breakout Buffer", "type": "number", "default": 0.1, "min": 0, "max": 2, "unit": "ATR", "description": "Completed close must cross the frozen boundary plus this fraction of ATR measured at recognition."},
    "patterns.volume_ratio": {"section": "Technical Patterns", "subsection": "Confirmation", "label": "Minimum Breakout Volume Ratio", "type": "number", "default": 0, "min": 0, "max": 5, "description": "Breakout volume / preceding 20-candle average. Zero disables the requirement; provider feed volumes remain distinct."},
    "patterns.expiry_bars": {"section": "Technical Patterns", "subsection": "Confirmation", "label": "Unconfirmed Pattern Expiry", "type": "integer", "default": 30, "min": 1, "max": 120, "unit": "candles"},
    "patterns.candle_lookback": {"section": "Technical Patterns", "subsection": "Candlestick Evidence", "label": "Recent Candle Evidence Window", "type": "integer", "default": 10, "min": 1, "max": 30, "unit": "candles"},
    "patterns.candles": {"section": "Technical Patterns", "subsection": "Candlestick Evidence", "label": "TA-Lib Candlestick Evidence", "type": "boolean", "default": True, "description": "All 61 detectors. Signed values represent geometry, not probabilities. Doji, spinning tops and other nondirectional shapes remain neutral; all evidence requires trend context."},
    "patterns.doubles": {"section": "Technical Patterns", "subsection": "Chart Families", "label": "Double Tops / Bottoms", "type": "boolean", "default": True},
    "patterns.head_shoulders": {"section": "Technical Patterns", "subsection": "Chart Families", "label": "Head and Shoulders / Inverse", "type": "boolean", "default": True},
    "patterns.triangles": {"section": "Technical Patterns", "subsection": "Chart Families", "label": "Ascending / Descending / Symmetrical Triangles", "type": "boolean", "default": True},
    "patterns.wedges": {"section": "Technical Patterns", "subsection": "Chart Families", "label": "Rising / Falling Wedges", "type": "boolean", "default": True},
    "patterns.flags": {"section": "Technical Patterns", "subsection": "Chart Families", "label": "Bull / Bear Flags", "type": "boolean", "default": True},
    "patterns.pennants": {"section": "Technical Patterns", "subsection": "Chart Families", "label": "Bull / Bear Pennants", "type": "boolean", "default": True},
    "patterns.rectangles": {"section": "Technical Patterns", "subsection": "Chart Families", "label": "Rectangles", "type": "boolean", "default": True},

    # Infrastructure is intentionally read-only in the app.
    "infrastructure.cerebro_port": {
        "section": "Advanced", "subsection": "Infrastructure", "label": "Cerebro Port", "type": "integer", "default": 7000, "read_only": True
    },
    "infrastructure.opend_host": {
        "section": "Advanced", "subsection": "Infrastructure", "label": "OpenD Host", "type": "string", "default": "127.0.0.1", "read_only": True
    },
    "infrastructure.opend_port": {
        "section": "Advanced", "subsection": "Infrastructure", "label": "OpenD Port", "type": "integer", "default": 11111, "read_only": True
    },
}


class SettingsService:
    def __init__(self):
        self._init_db()

    def _connect(self):
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(DB_PATH, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS app_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)

    def definitions(self):
        return deepcopy(DEFINITIONS)

    def _stored(self, key):
        with self._connect() as conn:
            row = conn.execute(
                "SELECT value FROM app_settings WHERE key = ?",
                (key,),
            ).fetchone()
        if not row:
            return None, False
        try:
            return json.loads(row["value"]), True
        except Exception:
            return row["value"], True

    def get(self, key, default=None):
        definition = DEFINITIONS.get(key)
        if definition is None:
            return default

        stored, exists = self._stored(key)
        if exists:
            return stored

        env_name = definition.get("env")
        if env_name:
            raw = os.getenv(env_name)
            if raw not in (None, ""):
                try:
                    return self._coerce(definition, raw)
                except Exception:
                    if definition.get("type") in {"string", "secret"}:
                        return raw

        return deepcopy(definition.get("default"))

    def get_bool(self, key):
        return bool(self.get(key))

    def _coerce(self, definition, value):
        setting_type = definition.get("type")

        if setting_type == "boolean":
            if isinstance(value, bool):
                return value
            if str(value).strip().lower() in {"1", "true", "yes", "on"}:
                return True
            if str(value).strip().lower() in {"0", "false", "no", "off"}:
                return False
            raise ValueError("must be true or false")

        if setting_type == "integer":
            if isinstance(value, bool):
                raise ValueError("must be an integer")
            result = int(value)
        elif setting_type == "number":
            if isinstance(value, bool):
                raise ValueError("must be a number")
            result = float(value)
        elif setting_type == "secret":
            if not isinstance(value, str):
                raise ValueError("must be text")
            result = value.strip()
            if any(ord(character) < 33 or ord(character) > 126 for character in result):
                raise ValueError("must contain printable ASCII characters without spaces")
        elif setting_type in {"string", "enum"}:
            result = str(value).strip()
        else:
            result = value

        minimum = definition.get("min")
        maximum = definition.get("max")
        if minimum is not None and result < minimum:
            raise ValueError(f"must be >= {minimum}")
        if maximum is not None and result > maximum:
            raise ValueError(f"must be <= {maximum}")

        options = definition.get("options")
        if options and result not in options:
            raise ValueError(f"must be one of: {', '.join(map(str, options))}")

        return result

    def _validate_weight_groups(self, pending):
        groups = {}
        for key, definition in DEFINITIONS.items():
            group = definition.get("weight_group")
            if group:
                groups.setdefault(group, []).append(key)

        for group, keys in groups.items():
            values = []
            for key in keys:
                values.append(float(pending.get(key, self.get(key))))
            total = sum(values)
            if abs(total - 1.0) > 0.0001:
                raise ValueError(
                    f"{group} must total 1.0 (100%); current total is {round(total, 6)}"
                )

    def update_many(self, values):
        if not isinstance(values, dict):
            raise ValueError("values must be an object")

        cleaned = {}
        for key, raw in values.items():
            definition = DEFINITIONS.get(key)
            if definition is None:
                raise ValueError(f"unknown setting: {key}")
            if definition.get("read_only"):
                raise ValueError(f"setting is read-only: {key}")
            if definition.get("type") == "secret" and raw in (None, ""):
                continue
            try:
                cleaned[key] = self._coerce(definition, raw)
                if definition.get("type") == "secret" and not cleaned[key]:
                    cleaned.pop(key)
            except Exception as exc:
                raise ValueError(f"{key}: {exc}") from exc

        self._validate_weight_groups(cleaned)

        now = datetime.now(timezone.utc).isoformat()
        with _lock:
            with self._connect() as conn:
                for key, value in cleaned.items():
                    conn.execute(
                        """
                        INSERT INTO app_settings (key, value, updated_at)
                        VALUES (?, ?, ?)
                        ON CONFLICT(key) DO UPDATE SET
                            value = excluded.value,
                            updated_at = excluded.updated_at
                        """,
                        (key, json.dumps(value), now),
                    )

        return self.public_snapshot()

    def reset(self, section=None):
        keys = [
            key for key, definition in DEFINITIONS.items()
            if section is None or definition.get("section") == section
        ]
        with _lock:
            with self._connect() as conn:
                conn.executemany(
                    "DELETE FROM app_settings WHERE key = ?",
                    [(key,) for key in keys],
                )
        return self.public_snapshot()

    def public_snapshot(self):
        items = []
        for key, definition in DEFINITIONS.items():
            item = deepcopy(definition)
            item["key"] = key
            if definition.get("type") == "secret":
                configured = bool(self.get(key))
                item["configured"] = configured
                item["value"] = None
            else:
                item["value"] = self.get(key)
            items.append(item)

        sections = []
        for item in items:
            if item["section"] not in sections:
                sections.append(item["section"])

        return {
            "schema_version": 1,
            "sections": sections,
            "settings": items,
        }


settings = SettingsService()
