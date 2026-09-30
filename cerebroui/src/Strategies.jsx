import React, { useEffect, useMemo, useState } from "react";
import {
  BrainCircuit,
  CheckCircle2,
  Clock3,
  Play,
  RefreshCw,
  ShieldCheck,
  Trash2,
  XCircle
} from "lucide-react";

import "./AIEngine.css";


function fmtScore(value) {
  const n = Number(value);
  return Number.isFinite(n) ? n.toFixed(1) : "—";
}

function unwrapLatest(payload) {
  const stored = payload?.result;
  if (!stored) return null;
  return stored.result || stored;
}

export default function Strategies() {
  const [runId, setRunId] = useState(null);
  const [progress, setProgress] = useState(null);
  const [bundle, setBundle] = useState(null);
  const [latestQuant, setLatestQuant] = useState(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState(null);

  const decisions = bundle?.ai?.decision?.decisions || [];
  const proposals = bundle?.execution?.proposals || [];
  const quantCandidates = latestQuant?.candidates || [];
  const approvalMode = bundle?.execution?.approval_mode;
  const pendingCount = proposals.filter(item => item.status === "PENDING_APPROVAL").length;
  const autoExecuted = approvalMode === "AUTO";
  const running = progress?.status === "RUNNING" || progress?.status === "QUEUED";

  const proposalBySymbol = useMemo(() => {
    const map = new Map();
    for (const item of proposals) map.set(item.symbol, item);
    return map;
  }, [proposals]);

  async function loadLatest() {
    try {
      const [aiRes, quantRes] = await Promise.all([
        fetch("/api/ai/decision/latest", { cache: "no-store" }),
        fetch("/api/quant/latest", { cache: "no-store" })
      ]);

      if (aiRes.ok) {
        const data = await aiRes.json();
        const next = unwrapLatest(data);
        setBundle(next);
        if (next) setRunId(next.run_id || data?.result?.run_id || null);
      }

      if (quantRes.ok) {
        const data = await quantRes.json();
        setLatestQuant(data?.result?.result || null);
      }
    } catch (_) {}
  }

  async function refreshResult(id = runId) {
    if (!id) return;
    const response = await fetch(`/api/ai/decision/result/${encodeURIComponent(id)}`, {
      cache: "no-store"
    });
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
    try {
      const response = await fetch("/api/ai/decision/run?run_type=MANUAL", {
        method: "POST"
      });
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

  async function act(action) {
    if (!runId) return;
    setBusy(true);
    setMessage(null);
    try {
      const response = await fetch(
        `/api/ai/decision/${encodeURIComponent(runId)}/${action}`,
        { method: "POST" }
      );
      const data = await response.json();
      if (!response.ok) {
        throw new Error(typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail));
      }
      setBundle(data);
      setProgress(previous => previous ? {
        ...previous,
        status: "COMPLETE",
        stage: "COMPLETE",
        message: action === "approve"
          ? "Decision approved and execution attempt complete"
          : "Decision rejected — no pending AI orders executed"
      } : previous);
      setMessage({
        kind: "ok",
        text: action === "approve"
          ? "AI decision approved. Eligible paper orders were submitted."
          : "AI decision rejected. No pending AI orders were submitted."
      });
    } catch (error) {
      setMessage({ kind: "error", text: error.message });
    } finally {
      setBusy(false);
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

  useEffect(() => {
    loadLatest();
  }, []);

  useEffect(() => {
    if (!runId) return;
    let cancelled = false;
    let timer = null;

    async function poll() {
      try {
        const response = await fetch(
          `/api/ai/decision/progress/${encodeURIComponent(runId)}`,
          { cache: "no-store" }
        );
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
        timer = setTimeout(poll, 1200);
      } catch (_) {
        if (!cancelled) timer = setTimeout(poll, 1800);
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
      : progress?.status
        ? "running"
        : "";

  return (
    <div className="aiEnginePage">
      <section className="aiHero">
        <div>
          <h2>AI Decision Engine</h2>
          <p>Run the complete quant → research → AI → deterministic risk → approval workflow.</p>
        </div>
        <div className="aiHeroActions">
          <button className="aiPrimary" onClick={startManualRun} disabled={busy || running}>
            <Play size={15}/>
            {running ? "Running…" : "Run AI Decision"}
          </button>
          <button className="aiSecondary" onClick={loadLatest} disabled={busy || running}>
            <RefreshCw size={15}/>
            Refresh
          </button>
          <button className="aiDanger" onClick={() => clearStored("quant")} disabled={busy || running}>
            <Trash2 size={14}/>
            Clear Quant
          </button>
          <button className="aiDanger" onClick={() => clearStored("ai")} disabled={busy || running}>
            <Trash2 size={14}/>
            Clear AI Result
          </button>
        </div>
      </section>

      {message && <div className={`aiMessage ${message.kind === "error" ? "error" : ""}`}>{message.text}</div>}

      <section className="aiPanel">
        <div className="aiPanelHeader">
          <div>
            <h3>Workflow Progress</h3>
            <p>{progress?.message || "Ready for a manual decision run."}</p>
          </div>
          <span className={`aiStatusBadge ${statusClass}`}>
            {progress?.status === "RUNNING" ? <Clock3 size={13}/> : progress?.status === "COMPLETE" ? <CheckCircle2 size={13}/> : progress?.status === "FAILED" ? <XCircle size={13}/> : <BrainCircuit size={13}/>} 
            {progress?.stage || "IDLE"}
          </span>
        </div>

        <div className="aiProgressTrack">
          <div className="aiProgressFill" style={{ width: `${Number(progress?.percent || 0)}%` }}/>
        </div>

        <div className="aiProgressMeta">
          <div className="aiMetric"><span>Overall</span><strong>{Number(progress?.percent || 0).toFixed(1)}%</strong></div>
          <div className="aiMetric"><span>Quant Stage</span><strong>{progress?.quant?.stage || "—"}</strong></div>
          <div className="aiMetric"><span>Quant Progress</span><strong>{Number(progress?.quant?.percent || 0).toFixed(1)}%</strong></div>
          <div className="aiMetric"><span>Current Symbol</span><strong>{progress?.quant?.current_symbol || "—"}</strong></div>
          <div className="aiMetric"><span>AI Stage</span><strong>{progress?.ai?.stage || "—"}</strong></div>
          <div className="aiMetric"><span>AI Candidates</span><strong>{progress?.ai?.candidate_count ?? "—"}</strong></div>
          <div className="aiMetric"><span>Research Ready</span><strong>{progress?.ai ? `${progress.ai.research_ready || 0}/${progress.ai.research_request_count || 0}` : "—"}</strong></div>
          <div className="aiMetric"><span>Research Errors</span><strong>{progress?.ai?.research_errors ?? "—"}</strong></div>
        </div>
      </section>

      {bundle?.ai?.decision && (
        <section className="aiPanel">
          <div className="aiPanelHeader">
            <div>
              <h3>Decision Summary</h3>
              <p>Generated by {bundle.ai.model} with {bundle.ai.reasoning_effort} reasoning.</p>
            </div>
            <span className="aiStatusBadge complete"><ShieldCheck size={13}/> {approvalMode || "READY"}</span>
          </div>

          <div className="aiSummaryGrid">
            <div className="aiSummaryCard"><span>Portfolio</span><strong>{bundle.ai.decision.portfolio_summary || "—"}</strong></div>
            <div className="aiSummaryCard"><span>Market</span><strong>{bundle.ai.decision.market_summary || "—"}</strong></div>
            <div className="aiSummaryCard"><span>Decisions</span><strong>{decisions.length}</strong></div>
          </div>
        </section>
      )}

      <section className="aiPanel">
        <div className="aiPanelHeader">
          <div>
            <h3>Stored Quant Results</h3>
            <p>{quantCandidates.length ? `${quantCandidates.length} ranked candidates in the latest quant artifact.` : "No stored quant result."}</p>
          </div>
        </div>

        {quantCandidates.length === 0 ? (
          <div className="aiEmpty">Run the AI decision workflow to generate a fresh quant ranking.</div>
        ) : (
          <div className="aiQuantTableWrap">
            <table className="aiQuantTable">
              <thead>
                <tr><th>Rank</th><th>Symbol</th><th>Name</th><th>Composite</th><th>Confidence</th><th>Agreement</th></tr>
              </thead>
              <tbody>
                {quantCandidates.map(item => (
                  <tr key={item.symbol}>
                    <td>{item.rank ?? "—"}</td>
                    <td><strong>{item.symbol}</strong></td>
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
      </section>

      <section className="aiPanel">
        <div className="aiPanelHeader">
          <div>
            <h3>AI Decisions & Reasoning</h3>
            <p>AI proposes portfolio intent. Cerebro sizes and risk-checks orders deterministically.</p>
          </div>
        </div>

        {decisions.length === 0 ? (
          <div className="aiEmpty">No AI decision result yet.</div>
        ) : (
          <div className="aiDecisionList">
            {decisions.map(item => {
              const proposal = proposalBySymbol.get(item.symbol);
              return (
                <article className="aiDecisionCard" key={item.symbol}>
                  <div className="aiDecisionTop">
                    <div className="aiDecisionIdentity">
                      <strong>{item.symbol}</strong>
                      <span className={`aiAction ${item.action}`}>{item.action}</span>
                    </div>
                    <span className="aiConfidence">Confidence {(Number(item.confidence || 0) * 100).toFixed(0)}%</span>
                  </div>

                  <div className="aiReasoning">{item.reasoning}</div>

                  <div className="aiDetailGrid">
                    <div className="aiDetail"><span>What changed</span><p>{item.what_changed || "No material change noted."}</p></div>
                    <div className="aiDetail"><span>Target exposure</span><strong>{item.desired_exposure_pct == null ? "—" : `${Number(item.desired_exposure_pct).toFixed(2)}%`}</strong></div>
                    <div className="aiDetail"><span>Thesis</span><p>{item.thesis_update || "No thesis update."}</p></div>
                    <div className="aiDetail"><span>Invalidation</span><p>{item.thesis_invalidation || "No invalidation update."}</p></div>
                  </div>

                  {proposal && (
                    <div className="aiProposal">
                      <div className="aiProposalHead">
                        <strong>Deterministic proposal</strong>
                        <span className="aiProposalStatus">{proposal.status}</span>
                      </div>
                      <p>{proposal.message}</p>
                      {proposal.order && (
                        <p><strong>{proposal.order.side}</strong> {proposal.order.quantity} shares · estimated ${Number(proposal.order.estimated_price || 0).toFixed(2)}</p>
                      )}
                      {proposal.risk?.risk_checks?.length > 0 && (
                        <div className="aiRiskChecks">
                          {proposal.risk.risk_checks.map(check => (
                            <div key={check.name} className={`aiRiskCheck ${check.passed ? "pass" : "fail"}`}>
                              {check.message}
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  )}
                </article>
              );
            })}
          </div>
        )}

        {decisions.length > 0 && !autoExecuted && approvalMode === "MANUAL" && (
          <div className="aiDecisionActions">
            <button className="aiDanger" disabled={busy} onClick={() => act("reject")}>
              <XCircle size={15}/> Reject
            </button>
            <button className="aiPrimary" disabled={busy || pendingCount === 0} onClick={() => act("approve")}>
              <CheckCircle2 size={15}/> Approve & Execute ({pendingCount})
            </button>
          </div>
        )}
      </section>
    </div>
  );
}
