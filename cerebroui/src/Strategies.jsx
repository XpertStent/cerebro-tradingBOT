import React, { useEffect, useMemo, useState } from "react";
import {
  Activity,
  AlertTriangle,
  BrainCircuit,
  CheckCircle2,
  Clock3,
  DatabaseZap,
  Eraser,
  Play,
  RefreshCw,
  SearchCheck,
  ShieldCheck,
  Trash2,
  XCircle
} from "lucide-react";

import "./AIEngine.css";
import CollapsibleSection from "./CollapsibleSection";

function fmtScore(value) {
  const n = Number(value);
  return Number.isFinite(n) ? n.toFixed(1) : "—";
}

function fmtExposure(value) {
  const n = Number(value);
  if (!Number.isFinite(n)) return "—";
  if (n !== 0 && Math.abs(n) < 0.01) return `${n.toFixed(4)}%`;
  return `${n.toFixed(2)}%`;
}

function unwrapLatest(payload) {
  const stored = payload?.result;
  if (!stored) return null;
  return stored.result || stored;
}

function fmtElapsed(value) {
  const seconds = Number(value || 0);
  if (seconds < 60) return `${seconds.toFixed(0)}s`;
  const mins = Math.floor(seconds / 60);
  const secs = Math.floor(seconds % 60);
  return `${mins}m ${secs}s`;
}

function openMarket(symbol, name = "") {
  window.dispatchEvent(new CustomEvent("cerebro-open-market", { detail: { symbol, name } }));
}

function pretty(value) {
  if (value == null) return "No additional detail available yet.";
  try {
    return JSON.stringify(value, null, 2);
  } catch (_) {
    return String(value);
  }
}

export default function Strategies() {
  const [runId, setRunId] = useState(null);
  const [progress, setProgress] = useState(null);
  const [bundle, setBundle] = useState(null);
  const [latestQuant, setLatestQuant] = useState(null);
  const [busy, setBusy] = useState(false);
  const [decisionBusyId, setDecisionBusyId] = useState(null);
  const [batchBusy, setBatchBusy] = useState(false);
  const [message, setMessage] = useState(null);
  const [selectedResearchSymbol, setSelectedResearchSymbol] = useState(null);

  const decisions = bundle?.ai?.decision?.decisions || [];
  const proposals = bundle?.execution?.proposals || [];
  const quantCandidates = latestQuant?.candidates || [];
  const approvalMode = bundle?.execution?.approval_mode;
  const pendingProposals = proposals.filter(item => item.status === "PENDING_APPROVAL");
  const pendingCount = pendingProposals.length;
  const pendingWatchCount = pendingProposals.filter(item => item.action === "WATCH").length;
  const pendingOrderCount = pendingCount - pendingWatchCount;
  const autoExecuted = approvalMode === "AUTO";
  const running = progress?.status === "RUNNING" || progress?.status === "QUEUED";
  const researchSymbols = progress?.ai?.research_symbols || {};
  const liveResearchDetails = progress?.ai?.research_details || {};
  const events = progress?.events || [];
  const decisionContext = bundle?.ai?.context || {};
  const researchBatchCount = decisionContext?.run?.research_parallel_batches;
  const decisionWebResearch = progress?.ai?.decision_web_research || bundle?.ai?.decision_web_research;

  const proposalBySymbol = useMemo(() => {
    const map = new Map();
    for (const item of proposals) map.set(item.symbol, item);
    return map;
  }, [proposals]);

  const candidateBySymbol = useMemo(() => {
    const map = new Map();
    for (const item of decisionContext?.candidates || []) {
      if (item?.symbol) map.set(item.symbol, item);
    }
    return map;
  }, [decisionContext]);

  const researchErrors = useMemo(() => (
    (decisionContext?.candidates || [])
      .filter(item => item?.research_context?.status === "ERROR")
      .map(item => ({
        symbol: item.symbol,
        name: item.market_snapshot?.name || "",
        error: item.research_context?.error || "Unknown research error",
        payload: item.research_context
      }))
  ), [decisionContext]);

  const selectedResearch = useMemo(() => {
    if (!selectedResearchSymbol) return null;
    const candidate = candidateBySymbol.get(selectedResearchSymbol);
    if (candidate?.research_context) return candidate.research_context;
    return liveResearchDetails[selectedResearchSymbol] || {
      symbol: selectedResearchSymbol,
      status: researchSymbols[selectedResearchSymbol] || "PENDING"
    };
  }, [selectedResearchSymbol, candidateBySymbol, liveResearchDetails, researchSymbols]);

  async function loadLatest() {
    try {
      const [aiRes, quantRes] = await Promise.all([
        fetch("/api/ai/decision/latest", { cache: "no-store" }),
        fetch("/api/quant/latest", { cache: "no-store" })
      ]);

      if (aiRes.ok) {
        const data = await aiRes.json();
        const next = unwrapLatest(data);
        if (next?.status && !next?.ai && !next?.execution) {
          setProgress(next);
          setRunId(next.run_id || null);
        } else {
          setBundle(next);
          if (next) setRunId(next.run_id || data?.result?.run_id || null);
        }
      }

      if (quantRes.ok) {
        const data = await quantRes.json();
        setLatestQuant(data?.result?.result || null);
      }
    } catch (_) {}
  }

  async function refreshResult(id = runId) {
    if (!id) return;
    const response = await fetch(`/api/ai/decision/result/${encodeURIComponent(id)}`, { cache: "no-store" });
    const data = await response.json();
    if (response.ok && data.result) {
      setBundle(data.result);
      if (data.result?.quant?.result) setLatestQuant(data.result.quant.result);
    }
  }

  async function startManualRun() {
    setBusy(true);
    setMessage(null);
    setBundle(null);
    setProgress(null);
    setSelectedResearchSymbol(null);
    try {
      const response = await fetch("/api/ai/decision/run?run_type=MANUAL", { method: "POST" });
      const data = await response.json();
      if (!response.ok) {
        throw new Error(typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail));
      }
      setRunId(data.run_id);
      setProgress(data);
      setMessage({ kind: "ok", text: "Manual AI workflow started." });
    } catch (error) {
      setMessage({ kind: "error", text: error.message });
    } finally {
      setBusy(false);
    }
  }

  async function actOne(proposal, action) {
    if (!runId || !proposal?.decision_id) return;
    const isWatch = proposal.action === "WATCH";
    if (action === "approve") {
      const ok = window.confirm(
        isWatch
          ? `Approve ${proposal.symbol} as a WATCH? It will be added to Monitored Securities and included in future AI decision runs.`
          : `Approve only ${proposal.symbol} and submit its PAPER order? No other AI decision will be approved.`
      );
      if (!ok) return;
    }

    setDecisionBusyId(proposal.decision_id);
    setMessage(null);
    try {
      const response = await fetch(
        `/api/ai/decision/${encodeURIComponent(runId)}/proposal/${encodeURIComponent(proposal.decision_id)}/${action}`,
        { method: "POST" }
      );
      const data = await response.json();
      if (!response.ok) {
        throw new Error(typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail));
      }
      setBundle(data);
      setMessage({
        kind: "ok",
        text: action === "approve"
          ? (isWatch
              ? `${proposal.symbol} approved for monitoring and added to Monitored Securities.`
              : `${proposal.symbol} approved and execution attempted. Other decisions were unchanged.`)
          : (isWatch
              ? `${proposal.symbol} WATCH rejected; the watchlist was unchanged.`
              : `${proposal.symbol} rejected. Other decisions were unchanged.`)
      });
      await refreshResult(runId);
    } catch (error) {
      setMessage({ kind: "error", text: error.message });
    } finally {
      setDecisionBusyId(null);
    }
  }

  async function actAll(action) {
    if (!runId || pendingProposals.length === 0) return;
    const mix = [
      pendingOrderCount ? `${pendingOrderCount} broker action${pendingOrderCount === 1 ? "" : "s"}` : null,
      pendingWatchCount ? `${pendingWatchCount} watch action${pendingWatchCount === 1 ? "" : "s"}` : null
    ].filter(Boolean).join(" and ");
    const ok = window.confirm(
      action === "approve"
        ? `Approve ALL ${pendingProposals.length} remaining AI decisions (${mix})? Broker actions are revalidated individually; WATCH actions are added to Monitored Securities.`
        : `Reject ALL ${pendingProposals.length} remaining AI decisions (${mix})? No broker orders or watchlist additions will be made for them.`
    );
    if (!ok) return;

    setBatchBusy(true);
    setMessage(null);
    const failures = [];
    let completed = 0;

    try {
      for (const proposal of pendingProposals) {
        if (!proposal?.decision_id) {
          failures.push(`${proposal?.symbol || "Unknown"}: missing decision id`);
          continue;
        }
        try {
          const response = await fetch(
            `/api/ai/decision/${encodeURIComponent(runId)}/proposal/${encodeURIComponent(proposal.decision_id)}/${action}`,
            { method: "POST" }
          );
          const data = await response.json();
          if (!response.ok) {
            throw new Error(typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail));
          }
          completed += 1;
          setBundle(data);
        } catch (error) {
          failures.push(`${proposal.symbol}: ${error.message}`);
        }
      }
      await refreshResult(runId);
      setMessage(failures.length ? {
        kind: "error",
        text: `${completed}/${pendingProposals.length} completed. ${failures.length} failed: ${failures.join(" | ")}`
      } : {
        kind: "ok",
        text: action === "approve"
          ? `All ${completed} remaining decisions were approved. Broker actions passed through final PAPER checks and WATCH actions were added to Monitored Securities.`
          : `All ${completed} remaining decisions were rejected. No orders or watchlist additions were made.`
      });
    } finally {
      setBatchBusy(false);
    }
  }

  async function clearStored(kind) {
    const label = kind === "ai" ? "latest AI decision result" : "latest quant result";
    if (!window.confirm(`Delete the ${label}? Long-term AI memory is retained.`)) return;
    setBusy(true);
    setMessage(null);
    try {
      const endpoint = kind === "ai" ? "/api/ai/decision/latest" : "/api/quant/latest";
      const response = await fetch(endpoint, { method: "DELETE" });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || `Delete failed (${response.status})`);
      if (kind === "ai") {
        setBundle(null);
        setRunId(null);
        setProgress(null);
        setSelectedResearchSymbol(null);
      } else {
        setLatestQuant(null);
      }
      setMessage({ kind: "ok", text: `${label} deleted.` });
    } catch (error) {
      setMessage({ kind: "error", text: error.message });
    } finally {
      setBusy(false);
    }
  }

  async function clearAllHistory() {
    if (!window.confirm(
      "TEST RESET ONLY: delete ALL stored AI decision history, theses, outcomes and run history? Broker orders, settings, quant history and market data are not deleted."
    )) return;
    if (!window.confirm("This cannot be undone. Clear all AI decision memory now?")) return;

    setBusy(true);
    setMessage(null);
    try {
      const response = await fetch("/api/ai/decision/history", { method: "DELETE" });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || `Delete failed (${response.status})`);
      setBundle(null);
      setRunId(null);
      setProgress(null);
      setSelectedResearchSymbol(null);
      setMessage({ kind: "ok", text: "All AI decision history and theses cleared for testing." });
    } catch (error) {
      setMessage({ kind: "error", text: error.message });
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => { loadLatest(); }, []);

  useEffect(() => {
    if (!runId) return;
    let cancelled = false;
    let timer = null;

    async function poll() {
      try {
        const response = await fetch(`/api/ai/decision/progress/${encodeURIComponent(runId)}`, { cache: "no-store" });
        const data = await response.json();
        if (cancelled || !response.ok) return;
        setProgress(data);
        if (data.status === "COMPLETE") {
          await refreshResult(runId);
          return;
        }
        if (data.status === "FAILED") {
          setMessage({ kind: "error", text: data.error || "AI workflow failed." });
          return;
        }
        timer = setTimeout(poll, 800);
      } catch (_) {
        if (!cancelled) timer = setTimeout(poll, 1400);
      }
    }

    poll();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [runId]);

  const statusClass = progress?.status === "FAILED"
    ? "failed"
    : progress?.status === "COMPLETE"
      ? "complete"
      : progress?.status ? "running" : "";

  return (
    <div className="aiEnginePage">
      <section className="aiHero">
        <div>
          <h2>AI Decision Engine</h2>
          <p>Quant → clustered research → independent decision-model web verification → deterministic risk → approval.</p>
        </div>
        <div className="aiHeroActions">
          <button className="aiPrimary" onClick={startManualRun} disabled={busy || running}>
            <Play size={15}/>{running ? "Running…" : "Run AI Decision"}
          </button>
          <button className="aiSecondary" onClick={loadLatest} disabled={busy || running}>
            <RefreshCw size={15}/>Refresh
          </button>
          <button className="aiDanger" onClick={() => clearStored("quant")} disabled={busy || running}>
            <Trash2 size={14}/>Clear Quant
          </button>
          <button className="aiDanger" onClick={() => clearStored("ai")} disabled={busy || running}>
            <Trash2 size={14}/>Clear AI Result
          </button>
          <button className="aiDanger strongDanger" onClick={clearAllHistory} disabled={busy || running}>
            <Eraser size={14}/>Clear All AI History
          </button>
        </div>
      </section>

      {message && <div className={`aiMessage ${message.kind === "error" ? "error" : ""}`}>{message.text}</div>}

      <CollapsibleSection
        title="Workflow Progress"
        subtitle={progress?.message || "Ready for a manual decision run."}
        actions={
          <span className={`aiStatusBadge ${statusClass}`}>
            {progress?.status === "RUNNING" ? <Clock3 size={13}/> : progress?.status === "COMPLETE" ? <CheckCircle2 size={13}/> : progress?.status === "FAILED" ? <XCircle size={13}/> : <BrainCircuit size={13}/>} 
            {progress?.stage || "IDLE"}
          </span>
        }
      >
        <div className="aiProgressTrack"><div className="aiProgressFill" style={{ width: `${Number(progress?.percent || 0)}%` }}/></div>
        <div className="aiProgressMeta">
          <div className="aiMetric"><span>Overall</span><strong>{Number(progress?.percent || 0).toFixed(1)}%</strong></div>
          <div className="aiMetric"><span>Elapsed</span><strong>{fmtElapsed(progress?.elapsed_seconds)}</strong></div>
          <div className="aiMetric"><span>Quant Stage</span><strong>{progress?.quant?.stage || "—"}</strong></div>
          <div className="aiMetric"><span>Quant Progress</span><strong>{Number(progress?.quant?.percent || 0).toFixed(1)}%</strong></div>
          <div className="aiMetric"><span>AI Stage</span><strong>{progress?.ai?.stage || "—"}</strong></div>
          <div className="aiMetric"><span>AI Candidates</span><strong>{progress?.ai?.candidate_count ?? "—"}</strong></div>
          <div className="aiMetric"><span>Research</span><strong>{progress?.ai ? `${progress.ai.research_complete || 0}/${progress.ai.research_request_count || 0}` : "—"}</strong></div>
          <div className="aiMetric"><span>Parallel Clusters</span><strong>{researchBatchCount ?? "Configured in Settings"}</strong></div>
          <div className="aiMetric"><span>In Flight</span><strong>{progress?.ai?.research_in_flight ?? "—"}</strong></div>
          <div className="aiMetric"><span>Research Ready</span><strong>{progress?.ai?.research_ready ?? "—"}</strong></div>
          <div className={`aiMetric ${Number(progress?.ai?.research_errors || 0) > 0 ? "metricError" : ""}`}><span>Research Errors</span><strong>{progress?.ai?.research_errors ?? "—"}</strong></div>
          <div className="aiMetric"><span>Decision Web Research</span><strong>{decisionWebResearch?.enabled ? (decisionWebResearch.status || `${decisionWebResearch.calls || 0} calls`) : "Disabled"}</strong></div>
          <div className="aiMetric"><span>Model Active</span><strong>{["DECISION_MODEL", "DECISION_RETRY"].includes(progress?.ai?.stage) ? `Yes · ${fmtElapsed(progress?.ai?.model_elapsed_seconds)}` : "No"}</strong></div>
        </div>

        {["DECISION_MODEL", "DECISION_RETRY"].includes(progress?.ai?.stage) && (
          <div className="aiThinkingBanner">
            <BrainCircuit size={18}/>
            <div>
              <strong>Decision model is analysing the portfolio and can independently use live web search</strong>
              <span>It receives the clustered research plus risk/portfolio context, and may verify current evidence itself before returning the final structured decisions.</span>
            </div>
          </div>
        )}
      </CollapsibleSection>

      <CollapsibleSection
        title="Live Workflow Activity"
        subtitle="Operational events from quant, research, model and risk stages."
        defaultOpen={running}
        bodyClassName="scrollRegion compact"
      >
        {events.length === 0 ? <div className="aiEmpty">No live workflow events yet.</div> : (
          <div className="aiEventList">
            {events.slice().reverse().map((event, index) => (
              <div className={`aiEvent ${event.kind === "ERROR" ? "error" : event.kind === "SUCCESS" ? "success" : ""}`} key={`${event.at}-${index}`}>
                <Activity size={14}/>
                <div><strong>{event.stage}</strong><span>{event.message}</span></div>
                <time>{new Date(event.at).toLocaleTimeString()}</time>
              </div>
            ))}
          </div>
        )}
      </CollapsibleSection>

      <CollapsibleSection
        title="Live Research Status"
        subtitle="Click a symbol here to inspect its research result, retry state, or exact error inside Strategies."
        defaultOpen={running && progress?.stage === "RESEARCH_AND_CONTEXT"}
      >
        {Object.keys(researchSymbols).length === 0 ? <div className="aiEmpty">Research has not returned any symbol results yet.</div> : (
          <>
            <div className="researchSymbolGrid">
              {Object.entries(researchSymbols).map(([symbol, status]) => (
                <button
                  key={symbol}
                  className={`researchSymbol ${selectedResearchSymbol === symbol ? "selected" : ""}`}
                  onClick={() => setSelectedResearchSymbol(symbol)}
                >
                  <SearchCheck size={14}/>
                  <strong>{symbol}</strong>
                  <span className={status === "ERROR" ? "bad" : status === "RETRY" ? "retry" : "good"}>{status}</span>
                </button>
              ))}
            </div>

            {selectedResearchSymbol && (
              <div className={`researchInspector ${selectedResearch?.status === "ERROR" ? "error" : ""}`}>
                <div className="researchInspectorHead">
                  <div>
                    <strong>{selectedResearchSymbol}</strong>
                    <span>{selectedResearch?.status || "PENDING"}</span>
                  </div>
                  <button className="aiSecondary" onClick={() => setSelectedResearchSymbol(null)}>Close detail</button>
                </div>
                <pre>{pretty(selectedResearch)}</pre>
              </div>
            )}
          </>
        )}
      </CollapsibleSection>

      {researchErrors.length > 0 && (
        <CollapsibleSection
          title={`Research Errors (${researchErrors.length})`}
          subtitle="Expand an errored symbol to see the exact returned error and stored research payload."
          defaultOpen={true}
          actions={<AlertTriangle size={18}/>} 
        >
          <div className="researchErrorList">
            {researchErrors.map(item => (
              <details className="researchErrorCard" key={item.symbol}>
                <summary>
                  <div><strong>{item.symbol}</strong><span>{item.name || "Research request failed"}</span></div>
                  <span>View error</span>
                </summary>
                <div className="researchErrorBody"><pre>{pretty(item.payload || item.error)}</pre></div>
              </details>
            ))}
          </div>
        </CollapsibleSection>
      )}

      {bundle?.ai?.decision && (
        <CollapsibleSection
          title="Decision Summary"
          subtitle={`Generated by ${bundle.ai.model} with ${bundle.ai.reasoning_effort} reasoning.`}
          actions={<span className="aiStatusBadge complete"><ShieldCheck size={13}/> {approvalMode || "READY"}</span>}
        >
          <div className="aiSummaryGrid">
            <div className="aiSummaryCard"><span>Portfolio</span><strong>{bundle.ai.decision.portfolio_summary || "—"}</strong></div>
            <div className="aiSummaryCard"><span>Market</span><strong>{bundle.ai.decision.market_summary || "—"}</strong></div>
            <div className="aiSummaryCard"><span>Decisions</span><strong>{decisions.length} · {pendingCount} awaiting approval ({pendingOrderCount} broker · {pendingWatchCount} watch)</strong></div>
            <div className="aiSummaryCard"><span>Decision web verification</span><strong>{bundle.ai.decision_web_research?.enabled ? `${bundle.ai.decision_web_research.calls || 0} search calls · ${bundle.ai.decision_web_research.source_count || 0} unique sources observed` : "Disabled"}</strong></div>
          </div>
        </CollapsibleSection>
      )}

      <CollapsibleSection
        title="Stored Quant Results"
        subtitle={quantCandidates.length ? `${quantCandidates.length} ranked candidates in the latest quant artifact.` : "No stored quant result."}
        defaultOpen={false}
        bodyClassName="scrollRegion"
      >
        {quantCandidates.length === 0 ? <div className="aiEmpty">Run the AI decision workflow to generate a fresh quant ranking.</div> : (
          <div className="aiQuantTableWrap">
            <table className="aiQuantTable">
              <thead><tr><th>Rank</th><th>Symbol</th><th>Name</th><th>Composite</th><th>Confidence</th><th>Agreement</th></tr></thead>
              <tbody>
                {quantCandidates.map(item => (
                  <tr key={item.symbol}>
                    <td>{item.rank ?? "—"}</td>
                    <td><button className="symbolLinkButton" onClick={() => openMarket(item.symbol, item.name)}>{item.symbol}</button></td>
                    <td>{item.name || "—"}</td>
                    <td>{fmtScore(item.quant?.composite_score)}</td>
                    <td>{fmtScore(item.quant?.signal_confidence)}</td>
                    <td>{fmtScore(item.quant?.agreement)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </CollapsibleSection>

      <CollapsibleSection
        title="AI Decisions & Reasoning"
        subtitle="Approve trades or monitoring actions individually, or resolve all remaining decisions together below."
        actions={<DatabaseZap size={18}/>} 
        bodyClassName="scrollRegion"
      >
        {decisions.length === 0 ? <div className="aiEmpty">No AI decision result yet.</div> : (
          <>
            <div className="aiDecisionList">
              {decisions.map(item => {
                const proposal = proposalBySymbol.get(item.symbol);
                const candidate = candidateBySymbol.get(item.symbol);
                const research = candidate?.research_context;
                const researchStatus = research?.status || (candidate ? "NOT_AVAILABLE" : null);
                const proposalBusy = decisionBusyId === proposal?.decision_id;
                const canDecide = !autoExecuted && ["MANUAL", "MANUAL_PARTIAL"].includes(approvalMode) && proposal?.status === "PENDING_APPROVAL";
                const isWatch = item.action === "WATCH";
                const effectiveExposure = proposal?.desired_exposure_pct ?? item.desired_exposure_pct;

                return (
                  <details className="aiDecisionCard" key={item.symbol}>
                    <summary className="aiDecisionTop">
                      <div className="aiDecisionIdentity">
                        <button type="button" className="symbolLinkButton" onClick={event => { event.preventDefault(); openMarket(item.symbol); }}>{item.symbol}</button>
                        <span className={`aiAction ${item.action}`}>{item.action}</span>
                        {researchStatus && <span className={`aiResearchBadge ${researchStatus === "READY" ? "ready" : researchStatus === "ERROR" ? "error" : "neutral"}`}>Research {researchStatus}</span>}
                      </div>
                      <span className="aiConfidence">Confidence {(Number(item.confidence || 0) * 100).toFixed(0)}%</span>
                    </summary>

                    <div className="aiDecisionBody">
                      <div className="aiReasoning">{item.reasoning}</div>
                      {research && (
                        <div className={`aiResearchDiagnostic ${research.status === "ERROR" ? "error" : ""}`}>
                          <strong>Research diagnostic</strong>
                          <span>{research.status === "READY" ? `READY · ${research.source_count ?? 0} retained sources · ${research.cache || "LIVE"}` : (research.error || "No structured research was returned for this symbol.")}</span>
                        </div>
                      )}

                      <div className="aiDetailGrid">
                        <div className="aiDetail"><span>What changed</span><p>{item.what_changed || "No material change noted."}</p></div>
                        <div className="aiDetail"><span>Target exposure</span><strong>{fmtExposure(effectiveExposure)}</strong></div>
                        <div className="aiDetail"><span>Thesis</span><p>{item.thesis_update || "No thesis update."}</p></div>
                        <div className="aiDetail"><span>Invalidation</span><p>{item.thesis_invalidation || "No invalidation update."}</p></div>
                      </div>

                      {proposal && (
                        <div className="aiProposal">
                          <div className="aiProposalHead"><strong>{isWatch ? "Monitoring proposal" : "Deterministic proposal"}</strong><span className="aiProposalStatus">{proposal.status}</span></div>
                          <p>{proposal.message}</p>
                          {proposal.sizing_adjustment && <div className="aiResearchDiagnostic"><strong>Whole-share sizing adjustment</strong><span>{proposal.sizing_adjustment} Effective target: {fmtExposure(proposal.desired_exposure_pct)}.</span></div>}
                          {proposal.order && <p><strong>{proposal.order.side}</strong> {proposal.order.quantity} shares · estimated ${Number(proposal.order.estimated_price || 0).toFixed(2)}</p>}
                          {proposal.risk?.risk_checks?.length > 0 && (
                            <div className="aiRiskChecks">
                              {proposal.risk.risk_checks.map(check => <div key={check.name} className={`aiRiskCheck ${check.passed ? "pass" : "fail"}`}>{check.message}</div>)}
                            </div>
                          )}

                          {canDecide && (
                            <div className="aiPerDecisionActions">
                              <button className="aiDanger" disabled={proposalBusy || batchBusy} onClick={() => actOne(proposal, "reject")}>
                                <XCircle size={15}/>{proposalBusy ? "Working…" : (isWatch ? "Reject Watch" : "Reject this decision")}
                              </button>
                              <button className="aiPrimary" disabled={proposalBusy || batchBusy} onClick={() => actOne(proposal, "approve")}>
                                <CheckCircle2 size={15}/>{proposalBusy ? "Working…" : (isWatch ? "Approve & Monitor" : "Approve & Execute this order")}
                              </button>
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                  </details>
                );
              })}
            </div>

            {!autoExecuted && pendingCount > 0 && ["MANUAL", "MANUAL_PARTIAL"].includes(approvalMode) && (
              <div className="aiPerDecisionActions">
                <button className="aiDanger" disabled={batchBusy || decisionBusyId != null} onClick={() => actAll("reject")}>
                  <XCircle size={15}/>{batchBusy ? "Working…" : `Reject All Remaining (${pendingCount})`}
                </button>
                <button className="aiPrimary" disabled={batchBusy || decisionBusyId != null} onClick={() => actAll("approve")}>
                  <CheckCircle2 size={15}/>{batchBusy ? "Working…" : `Approve All Remaining (${pendingCount})`}
                </button>
              </div>
            )}
          </>
        )}
      </CollapsibleSection>
    </div>
  );
}
