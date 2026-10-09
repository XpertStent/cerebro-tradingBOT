import React, { useEffect, useState } from "react";
import { fetchJson } from "./fetchJson";

// Mounted only for the selected symbol; keep full research out of progress polls.
export default function ResearchOutput({ runId, symbol, detail }) {
  const [output, setOutput] = useState(null);
  const [error, setError] = useState(null);
  const [attempt, setAttempt] = useState(0);
  const hasInlineOutput = detail && Object.hasOwn(detail, "research");
  const available = Boolean(detail?.output_available);

  useEffect(() => {
    if (hasInlineOutput || !available || !runId) return;
    const controller = new AbortController();
    let cancelled = false;
    setError(null);
    fetchJson(`/api/ai/decision/research/${encodeURIComponent(runId)}/${encodeURIComponent(symbol)}`,
      { cache: "no-store", controller })
      .then(data => {
        if (data.run_id !== runId || data.symbol !== symbol || !data.output) {
          throw new Error("The research response does not match this run and symbol.");
        }
        if (!cancelled) setOutput(data.output);
      })
      .catch(failure => { if (!cancelled) setError(failure.message); });
    return () => { cancelled = true; controller.abort(); };
  }, [runId, symbol, available, hasInlineOutput, attempt]);

  const payload = hasInlineOutput ? detail : output;
  return <>
    {!payload && <div className="aiEmpty">
      {error ? <>{error} <button type="button" onClick={() => setAttempt(value => value + 1)}>Retry</button></>
        : available ? "Loading research output…"
          : detail?.status === "READY"
            ? "Research is ready. This older backend provides its full output after the research stage finishes."
            : "Research output will appear here when this symbol finishes."}
    </div>}
    <pre>{JSON.stringify(payload || detail, null, 2)}</pre>
  </>;
}
