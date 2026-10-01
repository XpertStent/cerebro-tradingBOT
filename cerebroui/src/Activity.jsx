import React, { useEffect, useMemo, useState } from "react";
import {
  Activity as ActivityIcon,
  ExternalLink,
  RefreshCw,
  Search
} from "lucide-react";
import CollapsibleSection from "./CollapsibleSection";

const BASE_CATEGORIES = ["ORDER", "RISK", "BROKER", "MARKET", "SYSTEM", "STRATEGY", "AI"];

function localTime(value) {
  return value ? new Date(value).toLocaleString() : "—";
}

function formatDetails(value) {
  if (!value) return null;
  try {
    return JSON.stringify(JSON.parse(value), null, 2);
  } catch (_) {
    return value;
  }
}

export default function Activity() {
  const [events, setEvents] = useState([]);
  const [category, setCategory] = useState("");
  const [level, setLevel] = useState("");
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const categories = useMemo(() => {
    const dynamic = events.map(item => item.category).filter(Boolean);
    return Array.from(new Set([...BASE_CATEGORIES, ...dynamic])).sort();
  }, [events]);

  async function loadActivity({ silent = false } = {}) {
    if (!silent) setLoading(true);
    try {
      const params = new URLSearchParams({ limit: "500" });
      if (category) params.set("category", category);
      if (level) params.set("level", level);
      if (search.trim()) params.set("search", search.trim());
      const r = await fetch(`/api/activity/?${params}`, { cache: "no-store" });
      const d = await r.json();
      if (!r.ok) throw new Error(d.detail || `Activity failed (${r.status})`);
      setEvents(d.events || []);
      setError(null);
    } catch (e) {
      setError(e.message || "Could not load activity.");
    } finally {
      if (!silent) setLoading(false);
    }
  }

  useEffect(() => {
    loadActivity();
    const timer = setInterval(() => loadActivity({ silent: true }), 5000);
    return () => clearInterval(timer);
  }, [category, level]);

  function openSymbol(event) {
    if (!event.symbol) return;
    window.dispatchEvent(new CustomEvent("cerebro-open-market", {
      detail: { symbol: event.symbol, name: "" }
    }));
  }

  function openOrders(orderId) {
    if (orderId) sessionStorage.setItem("cerebro.orders.focus", String(orderId));
    window.dispatchEvent(new CustomEvent("cerebro-navigate", { detail: { page: "Orders" } }));
  }

  return (
    <div className="activityPage">
      <div className="activityToolbar">
        <div className="activitySearch">
          <Search size={16}/>
          <input
            value={search}
            onChange={e => setSearch(e.target.value)}
            onKeyDown={e => { if (e.key === "Enter") loadActivity(); }}
            placeholder="Search message, action, symbol, order or details"
          />
        </div>
        <button className="activitySearchButton" onClick={() => loadActivity()} disabled={loading}>
          <Search size={15}/>
          Search
        </button>

        <select value={category} onChange={e => setCategory(e.target.value)}>
          <option value="">All categories</option>
          {categories.map(item => <option key={item} value={item}>{item}</option>)}
        </select>

        <select value={level} onChange={e => setLevel(e.target.value)}>
          <option value="">All levels</option>
          <option value="INFO">Info</option>
          <option value="WARN">Warning</option>
          <option value="ERROR">Error</option>
        </select>
      </div>

      {error && <div className="activityError">{error}</div>}

      <CollapsibleSection
        title="Activity Timeline"
        subtitle="Persistent Cerebro audit trail. Click an event to inspect its full context."
        actions={
          <>
            <span>{events.length} events</span>
            <button onClick={() => loadActivity()} className="activityRefresh" disabled={loading}>
              <RefreshCw size={15}/>
              {loading ? "Loading…" : "Refresh"}
            </button>
          </>
        }
        bodyClassName="scrollRegion"
      >
        <div className="activityTimeline">
          {events.length === 0 ? (
            <div className="activityEmpty">
              <ActivityIcon size={28}/>
              <p>No activity matches the current filters.</p>
            </div>
          ) : (
            events.map(event => {
              const details = formatDetails(event.details);
              return (
                <details className="activityEvent activityEventClickable" key={event.id}>
                  <summary>
                    <div className={`activityDot ${String(event.level || "info").toLowerCase()}`}/>
                    <div className="activityEventBody">
                      <div className="activityEventTop">
                        <div>
                          <span className="activityCategory">{event.category}</span>
                          <strong>{event.message}</strong>
                        </div>
                        <time>{localTime(event.timestamp)}</time>
                      </div>
                      <div className="activityMeta">
                        <span>{event.action}</span>
                        <span>{event.level}</span>
                        {event.symbol && <span>{event.symbol}</span>}
                        {event.order_id && <span>Order {event.order_id}</span>}
                      </div>
                    </div>
                  </summary>

                  <div className="activityEventDetails">
                    <div className="activityEventDetailsGrid">
                      <div><span>Event ID</span><strong>{event.id}</strong></div>
                      <div><span>Category</span><strong>{event.category}</strong></div>
                      <div><span>Action</span><strong>{event.action}</strong></div>
                      <div><span>Level</span><strong>{event.level}</strong></div>
                      <div><span>Timestamp</span><strong>{localTime(event.timestamp)}</strong></div>
                      {event.symbol && <div><span>Symbol</span><strong>{event.symbol}</strong></div>}
                      {event.order_id && <div><span>Order ID</span><strong>{event.order_id}</strong></div>}
                    </div>

                    <div className="activityDeepLinks">
                      {event.symbol && (
                        <button className="activityLinkButton" onClick={() => openSymbol(event)}>
                          <ExternalLink size={13}/> Open {event.symbol} in Markets
                        </button>
                      )}
                      {event.order_id && (
                        <button className="activityLinkButton" onClick={() => openOrders(event.order_id)}>
                          <ExternalLink size={13}/> Open Orders
                        </button>
                      )}
                    </div>

                    {details && <pre className="activityDetailsPre">{details}</pre>}
                  </div>
                </details>
              );
            })
          )}
        </div>
      </CollapsibleSection>
    </div>
  );
}
