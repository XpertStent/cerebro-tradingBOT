import React, { useEffect, useState } from "react";
import {
  RefreshCw,
  Search,
  Activity as ActivityIcon
} from "lucide-react";
import CollapsibleSection from "./CollapsibleSection";

const CATEGORIES = ["", "ORDER", "RISK", "BROKER", "MARKET", "SYSTEM", "STRATEGY", "AI"];

export default function Activity() {
  const [events, setEvents] = useState([]);
  const [category, setCategory] = useState("");
  const [level, setLevel] = useState("");
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(false);

  async function loadActivity() {
    setLoading(true);
    try {
      const params = new URLSearchParams({ limit: "250" });
      if (category) params.set("category", category);
      if (level) params.set("level", level);
      if (search.trim()) params.set("search", search.trim());
      const r = await fetch(`/api/activity/?${params}`, { cache: "no-store" });
      const d = await r.json();
      if (r.ok) setEvents(d.events || []);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadActivity();
    const timer = setInterval(loadActivity, 5000);
    return () => clearInterval(timer);
  }, [category, level]);

  function localTime(value) {
    return value ? new Date(value).toLocaleString() : "—";
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
            placeholder="Search activity"
          />
        </div>

        <select value={category} onChange={e => setCategory(e.target.value)}>
          {CATEGORIES.map(item => (
            <option key={item || "ALL"} value={item}>{item || "All categories"}</option>
          ))}
        </select>

        <select value={level} onChange={e => setLevel(e.target.value)}>
          <option value="">All levels</option>
          <option value="INFO">Info</option>
          <option value="WARN">Warning</option>
          <option value="ERROR">Error</option>
        </select>
      </div>

      <CollapsibleSection
        title="Activity Timeline"
        subtitle="Persistent Cerebro audit trail."
        actions={
          <>
            <span>{events.length} events</span>
            <button onClick={loadActivity} className="activityRefresh">
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
              <p>No activity recorded yet.</p>
            </div>
          ) : (
            events.map(event => (
              <div className="activityEvent" key={event.id}>
                <div className={`activityDot ${event.level.toLowerCase()}`}/>
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
                    {event.symbol && <span>{event.symbol}</span>}
                    {event.order_id && <span>Order {event.order_id}</span>}
                  </div>
                </div>
              </div>
            ))
          )}
        </div>
      </CollapsibleSection>
    </div>
  );
}
