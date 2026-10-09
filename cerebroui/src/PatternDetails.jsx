import React from "react";
import { patternName } from "./patternPresentation";
import "./PatternDetails.css";

const number = value => value == null ? "—" : Number(value).toLocaleString(undefined, { maximumFractionDigits: 4 });

export default function PatternDetails({ analysis, onSelect, selectedId }) {
  if (!analysis) return <p className="patternNote">Loading daily pattern analysis…</p>;
  if (!analysis.available) return <p className="patternNote">Pattern analysis: {String(analysis.reason || "Unavailable").replaceAll("_", " ").toLowerCase()}. No pattern evidence is being used.</p>;
  const events = analysis.events || [];
  return <details className="patternPanel">
    <summary>Daily technical patterns · {analysis.bars_analyzed} candles · {analysis.event_count} records · {analysis.mode === "advisory" ? "AI advisory" : "Observation only"}</summary>
    <div className="patternBody">
      <p className="patternNote">Latest completed candle: {analysis.latest_candle_date} · {analysis.provenance?.provider} / {analysis.provenance?.feed} · {analysis.provenance?.adjustment} · {analysis.source === "ANALYSIS_CACHE" ? "Cached analysis" : "Calculated"} · {analysis.version}</p>
      <p className="patternNote">{analysis.mode === "observe" ? "These records are visible here and stored, but are excluded from AI prompts and quant scores." : "Compact evidence is included in new AI decision requests. Quant scores remain unchanged."} Pattern conditions describe completed daily closes; they do not arm broker orders. Adjusted levels require conversion and fresh risk checks before any trade.</p>
      {!events.length && <p>No validated chart formations in this window.</p>}
      {events.slice(0, 30).map(event => <details className="patternEvent" key={event.id}>
        <summary><strong>{patternName(event.pattern)}</strong><span>{event.status.replaceAll("_", " ")} · {event.direction} · recognized {event.recognition_date}</span></summary>
        <div className="patternBody">
          {onSelect && <button className="patternOverlayButton" onClick={() => onSelect(event.id)}>{selectedId === event.id ? "Shown on chart" : "Show on chart"}</button>}
          <p>{event.explanation}</p>
          <dl className="patternGrid">
            <div><dt>Formation starts</dt><dd>{event.formation_start}</dd></div>
            <div><dt>Last swing</dt><dd>{event.last_swing_date}</dd></div>
            <div><dt>Recognized</dt><dd>{event.recognition_date}</dd></div>
            <div><dt>Breakout confirmed</dt><dd>{event.confirmation_date || "Not confirmed"}</dd></div>
            <div><dt>Failed / invalidated</dt><dd>{event.invalidation_date || "—"}</dd></div>
            <div><dt>Expired</dt><dd>{event.expiry_date || "—"}</dd></div>
            <div><dt>Pivot confirmation delay</dt><dd>{event.pivot_delay_bars} completed candles</dd></div>
            <div><dt>Last evaluated</dt><dd>{event.last_evaluated_date}</dd></div>
            <div><dt>Upper / lower at last evaluation</dt><dd>{number(event.trigger?.above)} / {number(event.trigger?.below)}</dd></div>
            <div><dt>Breakout buffer</dt><dd>{number(event.trigger?.buffer)}</dd></div>
            <div><dt>Required volume ratio</dt><dd>{event.trigger?.volume_ratio_required || "Disabled"}</dd></div>
            <div><dt>First observed by Cerebro</dt><dd>{event.first_observed_at ? new Date(event.first_observed_at).toLocaleString() : "—"}</dd></div>
          </dl>
          <details><summary>Geometry evidence and actual swing points</summary>
            <pre>{JSON.stringify({ checks: event.checks, points: event.points }, null, 2)}</pre>
          </details>
        </div>
      </details>)}
      {events.length > 30 && <p>Showing the latest 30 records. The server retains up to 200 records per analysis and durable event observations.</p>}
      <details className="patternEvent"><summary>TA-Lib candle evidence ({analysis.candle_evidence?.length || 0})</summary>
        <p className="patternNote">Signed detector values describe candle shapes, not probabilities of a successful trade. Neutral candles need trend context.</p>
        <div className="patternTableWrap"><table><thead><tr><th>Date</th><th>Pattern</th><th>Direction</th><th>Value</th></tr></thead>
          <tbody>{(analysis.candle_evidence || []).map(item => <tr key={`${item.date}:${item.name}`}><td>{item.date}</td><td>{item.name.replace(/^CDL/, "")}</td><td>{item.direction}</td><td>{item.value}</td></tr>)}</tbody>
        </table></div>
      </details>
    </div>
  </details>;
}
