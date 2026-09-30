import React, { useEffect, useState } from "react";
import { RefreshCw, Trash2, Eye, Sparkles } from "lucide-react";
import CollapsibleSection from "./CollapsibleSection";

export default function Watchlist() {
  const [items, setItems] = useState([]);
  const [search, setSearch] = useState("");
  const [results, setResults] = useState([]);
  const [loading, setLoading] = useState(false);

  async function loadWatchlist() {
    setLoading(true);
    try {
      const r = await fetch("/api/watchlist/", { cache: "no-store" });
      const d = await r.json();
      if (r.ok) setItems(d.items || []);
    } finally {
      setLoading(false);
    }
  }

  async function searchSymbols(value) {
    setSearch(value);
    if (value.trim().length < 2) {
      setResults([]);
      return;
    }
    try {
      const r = await fetch(
        `/api/market/search?q=${encodeURIComponent(value.trim())}&markets=US,HK,SH,SZ,SG,MY,JP&limit=10`,
        { cache: "no-store" }
      );
      const d = await r.json();
      if (r.ok) setResults(d.results || d.items || []);
    } catch {
      setResults([]);
    }
  }

  async function addItem(item) {
    const symbol = item.symbol || item.code;
    if (!symbol) return;
    await fetch("/api/watchlist/", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        symbol,
        name: item.name || item.stock_name || null,
        market: symbol.includes(".") ? symbol.split(".")[0] : null,
        source: "MANUAL",
        status: "WATCH",
        reason: "Added manually to watchlist."
      })
    });
    setSearch("");
    setResults([]);
    await loadWatchlist();
  }

  async function removeItem(symbol) {
    await fetch(`/api/watchlist/${encodeURIComponent(symbol)}`, { method: "DELETE" });
    await loadWatchlist();
  }

  function openMarket(item) {
    window.dispatchEvent(
      new CustomEvent("cerebro-open-market", {
        detail: { symbol: item.symbol, name: item.name }
      })
    );
  }

  useEffect(() => { loadWatchlist(); }, []);

  return (
    <div className="watchlistPage">
      <CollapsibleSection
        title="Add Security"
        subtitle="Search for a ticker or company and add it to the AI watchlist."
        actions={
          <button className="watchlistRefresh" onClick={loadWatchlist}>
            <RefreshCw size={15}/>
            {loading ? "Loading…" : "Refresh"}
          </button>
        }
      >
        <div className="watchlistSearch">
          <input
            placeholder="Search ticker or company..."
            value={search}
            onChange={e => searchSymbols(e.target.value)}
          />
          {results.length > 0 && (
            <div className="watchlistResults">
              {results.map((item, index) => {
                const symbol = item.symbol || item.code;
                const name = item.name || item.stock_name || "";
                return (
                  <button key={symbol || index} onClick={() => addItem(item)}>
                    <strong>{symbol}</strong>
                    <span>{name}</span>
                  </button>
                );
              })}
            </div>
          )}
        </div>
      </CollapsibleSection>

      <CollapsibleSection
        title="Candidate Securities"
        subtitle={`${items.length} securities monitored`}
        actions={
          <div className="watchlistAIState">
            <Sparkles size={14}/>
            AI discovery candidates also appear in decision context
          </div>
        }
        bodyClassName="scrollRegion"
      >
        {items.length === 0 ? (
          <div className="watchlistEmpty">No securities in watchlist.</div>
        ) : (
          items.map(item => (
            <div className="watchlistRow" key={item.symbol}>
              <div className="watchlistSecurity" onClick={() => openMarket(item)}>
                <strong>{item.symbol}</strong>
                <span>{item.name || "—"}</span>
              </div>

              <div className="watchlistTags">
                <span>{item.status}</span>
                <span>{item.source}</span>
                {item.score != null && <span>Score {item.score}</span>}
              </div>

              <div className="watchlistReason">
                {item.reason || "No reason recorded."}
                {item.strategy_hint && <small>Strategy: {item.strategy_hint}</small>}
              </div>

              <div className="watchlistActions">
                <button title="Open in Markets" onClick={() => openMarket(item)}>
                  <Eye size={14}/>
                </button>
                <button title="Remove" onClick={() => removeItem(item.symbol)}>
                  <Trash2 size={14}/>
                </button>
              </div>
            </div>
          ))
        )}
      </CollapsibleSection>
    </div>
  );
}
