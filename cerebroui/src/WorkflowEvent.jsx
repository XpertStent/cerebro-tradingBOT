import React from "react";
import { Activity, ChevronDown } from "lucide-react";
import { historyDate, historyNumber, historyStatus, historySource } from "./workflowHistory";
import PatternDetails from "./PatternDetails";

const indicatorLabels = {
  return_20d_pct: "20-session return (%)",
  return_60d_pct: "60-session return (%)",
  return_120d_pct: "120-session return (%)",
  rsi_14: "RSI (14)",
  atr_pct: "ATR (%)",
  ema20: "EMA (20)",
  ema50: "EMA (50)",
  ema200: "EMA (200)",
  volume_ratio_20d: "Volume ratio (20 sessions)",
  median_turnover_60d: "Median turnover (60 sessions)",
  invalid_ohlc_bars: "Invalid OHLC candles",
  unchanged_sessions_20d: "Unchanged closes (20 sessions)",
};

function HistoryDetails({ detail }) {
  const pending = detail.status === "RUNNING";
  const count = value => pending && value == null ? "Pending" : historyNumber(value);
  const provider = { alpaca: "Alpaca", opend: "OpenD" }[detail.provider] || detail.provider || "—";
  const feed = { delayed_sip: "Delayed SIP", sip: "SIP", iex: "IEX", broker: "Broker feed" }[detail.feed] || detail.feed || "—";
  const adjustment = { all: "All corporate actions", qfq: "Forward adjusted", raw: "Unadjusted", none: "Unadjusted" }[detail.adjustment] || detail.adjustment || "—";
  const session = { PROVIDER_AGGREGATE: "Provider daily aggregate", REGULAR: "Regular session" }[detail.session] || detail.session || "Pending";
  const fields = [
    ["Downloaded this analysis", count(detail.fetched_count)],
    ["Saved to cache", count(detail.saved_count)],
    ["Returned from history", count(detail.returned_count)],
    ["Completed candles", count(detail.completed_count)],
    ["Candles checked", pending ? "Pending" : count(detail.checked_count)],
    ["Candles analysed", pending ? "Pending" : count(detail.analysed_count)],
    ["Latest candle received", historyDate(detail.latest_candle_time)],
    ["Latest completed candle", historyDate(detail.latest_completed_candle_time)],
    ["Expected completed date", historyDate(detail.expected_complete_date)],
    ["Completed history starts", historyDate(detail.oldest_completed_candle_time)],
    ["Provider / feed", `${provider} / ${feed}`],
    ["History source", historySource(detail)],
    ["Freshness", detail.fresh == null ? "Pending" : detail.fresh ? "Current" : "Stale / refresh failed"],
    ["Interval / timezone", `Daily / ${detail.timezone || "Pending"}`],
    ["Adjustment / session", `${adjustment} / ${session}`],
    ["Configured / requested / minimum", `${count(detail.configured_count)} / ${count(detail.requested_count)} / ${count(detail.minimum_bars)}`],
    ["Feed delay", detail.delay_minutes == null ? "—" : `${detail.delay_minutes} minutes`],
    ["Benchmark", detail.benchmark_symbol || "—"],
    ["Last cache sync", detail.last_sync_at ? new Date(detail.last_sync_at).toLocaleString() : "—"],
    ["Analysis duration", detail.elapsed_seconds == null ? "Pending" : `${historyNumber(detail.elapsed_seconds)}s`],
  ];
  const indicators = Object.entries(detail.indicators || {}).filter(([key]) => indicatorLabels[key]);
  const anomalies = detail.indicators?.discontinuity_events || [];
  return (
    <div className="aiHistoryDetails">
      <p className="aiHistoryExplanation">
        Only completed daily candles enter analysis. Downloads can exceed the requested window; a cache hit downloads zero candles. Saved counts include updates to existing cache rows.
      </p>
      {detail.reason && <p className="aiHistoryIssue">{detail.reason}</p>}
      {detail.refresh_error && <p className="aiHistoryIssue">Refresh: {detail.refresh_error.message || detail.refresh_error.code}</p>}
      <dl className="aiHistoryGrid">
        {fields.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}
      </dl>
      {indicators.length > 0 && <>
        <h4>Analysis results</h4>
        <dl className="aiHistoryGrid">
          {indicators.map(([key, value]) => <div key={key}><dt>{indicatorLabels[key]}</dt><dd>{historyNumber(value)}</dd></div>)}
        </dl>
      </>}
      {anomalies.length > 0 && <div className="aiHistoryAnomalies">
        <h4>Price moves requiring event review</h4>
        <ul>{anomalies.map((item, index) => <li key={index}>{historyDate(item.date)} · {historyNumber(item.return_pct ?? item.abs_return_pct)}% move</li>)}</ul>
      </div>}
      {detail.technical_analysis && <PatternDetails analysis={detail.technical_analysis}/>}
    </div>
  );
}

export default function WorkflowEvent({ event }) {
  if (event.pattern_details) return <details className="aiWorkflowEvent">
    <summary className="aiEvent aiEventExpandable"><Activity size={14}/><div className="aiEventText"><strong>{event.stage}</strong><span>{event.message}</span></div><ChevronDown size={16}/></summary>
    <PatternDetails analysis={event.pattern_details}/>
  </details>;
  const detail = event.details;
  const tone = event.kind === "ERROR" ? "error" : event.kind === "SUCCESS" ? "success" : "";
  const content = <>
    <Activity size={14}/>
    <div className="aiEventText">
      <strong>{event.stage}</strong>
      <span>{event.message}</span>
      {detail && <span className="aiHistorySummary">
        {historyStatus(detail.status)}
        {detail.status !== "RUNNING" && ` · ${historyNumber(detail.analysed_count)} candles analysed`}
        {detail.latest_completed_candle_time && ` · Latest completed: ${historyDate(detail.latest_completed_candle_time)}`}
      </span>}
    </div>
    <time dateTime={event.at}>{new Date(event.at).toLocaleTimeString()}</time>
    {detail && <ChevronDown className="aiEventChevron" size={16}/>}
  </>;
  if (!detail) return <div className={`aiEvent ${tone}`}>{content}</div>;
  return <details className={`aiWorkflowEvent ${tone}`}>
    <summary className="aiEvent aiEventExpandable">{content}</summary>
    <HistoryDetails detail={detail}/>
  </details>;
}
