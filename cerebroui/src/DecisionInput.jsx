import React, { useEffect, useState } from "react";
import { ChevronDown, Copy, RefreshCw } from "lucide-react";
import CollapsibleSection from "./CollapsibleSection";
import { fetchJson } from "./fetchJson";
import { copyDecisionText, inputGroups, requestText } from "./decisionInput";

const labels = {
  schema_version: "Context version", run: "Run information", market_context: "Market context",
  deterministic_risk_policy: "Current risk policy", portfolio: "Portfolio, positions and pending orders",
  quant_context: "Quant context and data quality", market_snapshot: "Market snapshot",
  quant: "Quant signals and indicators", research_context: "Company research",
  event_review: "Price anomaly review", account_sizing_snapshot: "Account sizing snapshot",
  watchlist: "Monitored security", active_thesis: "Active thesis", recent_decisions: "Recent decisions",
  rejection_summary: "Rejection history", symbol: "Symbol", relationship: "Primary relationship",
  relationships: "Portfolio relationships",
};

function JsonDetails({ name, value }) {
  return <details className="decisionInputField">
    <summary><span>{labels[name] || name}</span><ChevronDown size={14}/></summary>
    <pre>{JSON.stringify(value, null, 2)}</pre>
  </details>;
}

export function DecisionInputInspector({ runId, available, snapshot: storedSnapshot, status }) {
  const [loaded, setLoaded] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);
  const [retry, setRetry] = useState(0);
  const [tab, setTab] = useState("symbols");
  const [copyMessage, setCopyMessage] = useState(null);
  const snapshot = storedSnapshot || loaded;

  useEffect(() => {
    if (storedSnapshot || !available || !runId) return;
    const controller = new AbortController();
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetchJson(`/api/ai/decision/input/${encodeURIComponent(runId)}`, { cache: "no-store", controller })
      .then(data => {
        if (cancelled) return;
        if (data.run_id !== runId || typeof data.snapshot?.request?.input !== "string") {
          throw new Error("The captured input does not match this decision run.");
        }
        setLoaded(data.snapshot);
      })
      .catch(failure => { if (!cancelled) setError(failure.message.replace("OpenD request timed out", "Decision input request timed out")); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; controller.abort(); };
  }, [runId, available, storedSnapshot, retry]);

  async function copy(text, label) {
    try { await copyDecisionText(text); setCopyMessage(`${label} copied.`); }
    catch (failure) { setCopyMessage(failure.message); }
  }

  if (!snapshot) return <div className="decisionInputEmpty">
    {loading ? "Loading the captured request…" : error || (
      available ? "Captured input is ready to load." : ["COMPLETE", "FAILED", "INPUT_CAPTURED"].includes(status)
        ? "No exact request was captured for this run. Older runs require a new run to capture the input."
        : "Input will be available once research and portfolio context are ready and the decision request is prepared."
    )}
    {error && <button className="aiSecondary" onClick={() => setRetry(value => value + 1)}><RefreshCw size={14}/>Retry</button>}
  </div>;

  const groups = inputGroups(snapshot);
  const tabs = [["symbols", `Symbols (${groups.candidates.length})`], ["shared", "Shared context"], ["instructions", "Instructions"], ["request", "Full request"]];
  return <div className="decisionInputInspector">
    <div className="decisionInputMeta">
      <strong>{snapshot.request.model} · {snapshot.request.reasoning?.effort || "Default"} reasoning</strong>
      <span>Run {runId} · Captured {new Date(snapshot.captured_at).toLocaleString()}</span>
      <span>Web search {snapshot.request.tools?.some(tool => tool.type === "web_search") ? "enabled" : "disabled"} · Initial input only; later search results are separate.</span>
    </div>
    <div className="decisionInputToolbar">
      <div className="decisionInputTabs" role="tablist" aria-label="Decision model input views">
        {tabs.map(([key, label]) => <button key={key} id={`input-tab-${key}`} role="tab" aria-selected={tab === key} aria-controls="decision-input-panel" onClick={() => { setTab(key); setCopyMessage(null); }}>{label}</button>)}
      </div>
      <button className="aiSecondary" onClick={() => copy(requestText(snapshot), "Full request")}><Copy size={14}/>Copy full request</button>
    </div>
    {copyMessage && <p className="decisionInputCopyStatus" role="status">{copyMessage}</p>}
    <div id="decision-input-panel" role="tabpanel" aria-labelledby={`input-tab-${tab}`}>
      {tab === "symbols" && <>
        <p className="decisionInputNote">These entries were sent together in one portfolio request. Expand a symbol to inspect its complete entry.</p>
        <div className="decisionInputSymbols">
          {groups.candidates.map((candidate, index) => <details className="decisionInputSymbol" key={`${candidate.symbol}-${index}`}>
            <summary><div><strong>{candidate.symbol || "Unnamed candidate"}</strong><span>{(candidate.relationships || [candidate.relationship]).filter(Boolean).join(" · ")}</span></div><ChevronDown size={16}/></summary>
            <div className="decisionInputSymbolBody">{Object.entries(candidate).map(([name, value]) => <JsonDetails key={name} name={name} value={value}/>)}</div>
          </details>)}
        </div>
      </>}
      {tab === "shared" && <div className="decisionInputShared">{Object.entries(groups.shared).map(([name, value]) => <JsonDetails key={name} name={name} value={value}/>)}</div>}
      {tab === "instructions" && <pre className="decisionInputRaw">{snapshot.instructions}</pre>}
      {tab === "request" && <>
        <div className="decisionInputPromptHead"><h3>Exact prompt</h3><button className="aiSecondary" onClick={() => copy(snapshot.request.input, "Prompt")}><Copy size={14}/>Copy prompt</button></div>
        <pre className="decisionInputRaw">{snapshot.request.input}</pre>
        <h3>Full request body</h3>
        <pre className="decisionInputRaw">{requestText(snapshot)}</pre>
      </>}
    </div>
  </div>;
}

export default function DecisionInput({ runId, available, snapshot, status }) {
  return <CollapsibleSection title="Decision Model Input" subtitle="Inspect the exact initial input sent to the decision model, by symbol or as the full request." defaultOpen={false}>
    <DecisionInputInspector key={runId || "no-run"} runId={runId} available={available} snapshot={snapshot} status={status}/>
  </CollapsibleSection>;
}
