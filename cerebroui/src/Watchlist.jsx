import React, { useEffect, useState } from "react";
import { Eye, Plus, RefreshCw, Search, Sparkles, Trash2 } from "lucide-react";
import CollapsibleSection from "./CollapsibleSection";
import useSymbolSearch from "./useSymbolSearch";

const ALL_MARKETS = ["US", "HK", "SH", "SZ", "SG", "MY", "JP"];

function money(value) {
  const n = Number(value);
  if (!Number.isFinite(n)) return "—";
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 2,
    maximumFractionDigits: n < 1 ? 4 : 2
  }).format(n);
}

function moveClass(value) {
  const n = Number(value);
  if (!Number.isFinite(n) || n === 0) return "flat";
  return n > 0 ? "positive" : "negative";
}

function moveText(change, pct) {
  const c = Number(change);
  const p = Number(pct);
  if (!Number.isFinite(c) || !Number.isFinite(p)) return "Change unavailable";
  const sign = c > 0 ? "+" : "";
  return `${sign}${c.toFixed(2)} (${sign}${p.toFixed(2)}%)`;
}

export default function Watchlist() {
  const [items, setItems] = useState([]);
  const [search, setSearch] = useState("");
  const [searchMarket, setSearchMarket] = useState("US");
  const symbolSearch = useSymbolSearch(searchMarket === "ALL" ? ALL_MARKETS : [searchMarket]);
  const { results, searching } = symbolSearch;
  const [loading, setLoading] = useState(false);

  const [addingSymbol, setAddingSymbol] = useState(null);
  const [error, setError] = useState(null);
  const [quoteError, setQuoteError] = useState(null);


  async function loadWatchlist({ silent = false } = {}) {
    if (!silent) setLoading(true);
    try {
      const r = await fetch("/api/watchlist/", { cache: "no-store" });
      const d = await r.json();
      if (!r.ok) throw new Error(d.detail || `Watchlist failed (${r.status})`);
      setItems(d.items || []);
      setQuoteError(d.quote_error || null);
      setError(null);
    } catch (e) {
      setError(e.message || "Could not load the watchlist.");
    } finally {
      if (!silent) setLoading(false);
    }
  }

  function onSearchChange(value) {
    setSearch(value);
    symbolSearch.schedule(value);
  }

  async function addItem(item) {
    const symbol = item.symbol || item.code;
    if (!symbol) return;
    setAddingSymbol(symbol);
    try {
      const r = await fetch("/api/watchlist/", {
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
      const d = await r.json();
      if (!r.ok) throw new Error(d.detail || `Add failed (${r.status})`);
      setSearch("");
      symbolSearch.clear();
      setError(null);
      await loadWatchlist({ silent: true });
    } catch (e) {
      setError(e.message || `Could not add ${symbol}.`);
    } finally {
      setAddingSymbol(null);
    }
  }

  async function removeItem(symbol) {
    if (!window.confirm(`Remove ${symbol} from the watchlist?`)) return;
    try {
      const r = await fetch(`/api/watchlist/${encodeURIComponent(symbol)}`, { method: "DELETE" });
      const d = await r.json();
      if (!r.ok) throw new Error(d.detail || `Remove failed (${r.status})`);
      await loadWatchlist({ silent: true });
    } catch (e) {
      setError(e.message || `Could not remove ${symbol}.`);
    }
  }

  function openMarket(item) {
    window.dispatchEvent(new CustomEvent("cerebro-open-market", {
      detail: { symbol: item.symbol || item.code, name: item.name || item.stock_name || "" }
    }));
  }

  useEffect(() => {
    loadWatchlist();
    const timer = setInterval(() => loadWatchlist({ silent: true }), 15000);
    return () => clearInterval(timer);
  }, []);

  return (
    <div className="watchlistPage">
      <CollapsibleSection
        title="Find & Add Securities"
        subtitle="Live suggestions appear as you type. Search explicitly or add a verified market result to your watchlist."
        actions={
          <button className="watchlistRefresh" onClick={() => loadWatchlist()} disabled={loading}>
            <RefreshCw size={15}/>
            {loading ? "Loading…" : "Refresh Quotes"}
          </button>
        }
      >
        <label className="watchlistMarketFilter">Search market
          <select value={searchMarket} onChange={event => { setSearchMarket(event.target.value); setSearch(""); symbolSearch.clear(); }}>
            {ALL_MARKETS.map(market => <option key={market} value={market}>{market}</option>)}
            <option value="ALL">All markets</option>
          </select>
        </label>
        <div className="watchlistSearchBar">
          <div className="watchlistSearchShell">
            <div className="watchlistSearchInput">
              <Search size={16}/>
              <input
                placeholder="Search ticker or company, e.g. AAPL or Nvidia"
                value={search}
                onChange={e => onSearchChange(e.target.value)}
                onKeyDown={e => {
                  if (e.key === "Enter") {
                    e.preventDefault();
                    symbolSearch.run(search);
                  }
                }}
              />
            </div>


          </div>

          <button className="watchlistSearchButton" onClick={() => symbolSearch.run(search)} disabled={searching || !search.trim()}>
            <Search size={15}/>
            {searching ? "Searching…" : "Search"}
          </button>
        </div>

            {results.length > 0 && (
              <div className="watchlistResults">
                {results.map((item, index) => {
                  const symbol = item.symbol || item.code;
                  const name = item.name || item.stock_name || "";
                  return (
                    <div className="watchlistResultRow" key={symbol || index}>
                      <div className="watchlistResultIdentity" role="button" tabIndex={0} onClick={() => openMarket(item)} onKeyDown={e => { if (e.key === "Enter") openMarket(item); }}>
                        <strong>{symbol}</strong>
                        <span>{name || "Security"}</span>
                      </div>
                      <button className="watchlistResultAction" disabled={addingSymbol === symbol} onClick={() => addItem(item)}>
                        <Plus size={14}/>
                        {addingSymbol === symbol ? "Adding…" : "Add"}
                      </button>
                    </div>
                  );
                })}
              </div>
            )}
        <div className="watchlistSearchHint">
          Suggestions start after 2 characters. Selecting a symbol name opens Markets; Add keeps it monitored here.
        </div>
        {(error || symbolSearch.error) && <div className="watchlistError">{error || symbolSearch.error}</div>}
        {searching && <div className="watchlistSearchHint" role="status">Searching {searchMarket === "ALL" ? "all markets" : searchMarket}…</div>}
        {!searching && search.trim().length >= 2 && !results.length && !symbolSearch.error && <div className="watchlistSearchHint" role="status">No matching securities in {searchMarket === "ALL" ? "the selected markets" : searchMarket}.</div>}
        {quoteError && <div className="watchlistError">Watchlist saved, but live quotes are temporarily unavailable: {quoteError}</div>}
      </CollapsibleSection>

      <CollapsibleSection
        title="Monitored Securities"
        subtitle={`${items.length} securities · live quotes refresh every 15 seconds`}
        actions={
          <div className="watchlistAIState">
            <Sparkles size={14}/>
            Watchlist context can be supplied to the AI engine
          </div>
        }
        bodyClassName="scrollRegion"
      >
        {items.length === 0 ? (
          <div className="watchlistEmpty">No securities in watchlist. Search above to add one.</div>
        ) : (
          items.map(item => {
            const quote = item.quote;
            const pct = quote?.change_pct;
            return (
              <div className="watchlistRow" key={item.symbol}>
                <button className="watchlistSecurity symbolCellButton" onClick={() => openMarket(item)}>
                  <strong>{item.symbol}</strong>
                  <span>{item.name || quote?.name || "—"}</span>
                </button>

                <div className="watchlistQuote">
                  <strong>{money(quote?.price)}</strong>
                  <span className={`marketMove ${moveClass(pct)}`}>{moveText(quote?.change, pct)}</span>
                  {quote?.updated_at && <small className="watchlistUpdated">Updated {quote.updated_at}</small>}
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
                  <button title="Open in Markets" onClick={() => openMarket(item)}><Eye size={14}/></button>
                  <button title="Remove" onClick={() => removeItem(item.symbol)}><Trash2 size={14}/></button>
                </div>
              </div>
            );
          })
        )}
      </CollapsibleSection>
    </div>
  );
}
