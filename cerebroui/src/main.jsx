import React, { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  LayoutDashboard,
  LineChart,
  BrainCircuit,
  ClipboardList,
  Wallet,
  ScrollText,
  Settings as SettingsIcon,
  CircleDollarSign,
  Star
} from "lucide-react";

import "./style.css";
import "./AppPolish.css";
import Markets from "./Markets";
import Orders from "./Orders";
import Portfolio from "./Portfolio";
import Activity from "./Activity";
import Strategies from "./Strategies";
import Watchlist from "./Watchlist";
import Settings from "./Settings";
import CollapsibleSection from "./CollapsibleSection";

const nav = [
  ["Dashboard", LayoutDashboard, "dashboard"],
  ["Markets", LineChart, "markets"],
  ["Watchlist", Star, "watchlist"],
  ["Strategies", BrainCircuit, "strategies"],
  ["Orders", ClipboardList, "orders"],
  ["Portfolio", Wallet, "portfolio"],
  ["Activity / Logs", ScrollText, "activity"],
  ["Settings", SettingsIcon, "settings"]
];

const PAGE_BY_SLUG = Object.fromEntries(nav.map(([name, , slug]) => [slug, name]));
const SLUG_BY_PAGE = Object.fromEntries(nav.map(([name, , slug]) => [name, slug]));

function pageFromHash() {
  const slug = window.location.hash.replace(/^#\/?/, "").split("/")[0].toLowerCase();
  return PAGE_BY_SLUG[slug] || "Dashboard";
}

function money(value) {
  if (value === null || value === undefined) return "—";
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD"
  }).format(value);
}

function App() {
  const [system, setSystem] = useState(null);
  const [portfolio, setPortfolio] = useState(null);
  const [orders, setOrders] = useState(null);
  const [activePage, setActivePage] = useState(pageFromHash);

  function navigate(page, { replace = false } = {}) {
    const next = SLUG_BY_PAGE[page] ? page : "Dashboard";
    const hash = `#/${SLUG_BY_PAGE[next]}`;
    if (window.location.hash === hash) {
      setActivePage(next);
      return;
    }
    if (replace) {
      window.history.replaceState(null, "", hash);
      setActivePage(next);
    } else {
      window.location.hash = hash;
    }
  }

  async function refresh() {
    try {
      const [s, p, o] = await Promise.all([
        fetch("/api/system/status", { cache: "no-store" }),
        fetch("/api/portfolio/", { cache: "no-store" }),
        fetch("/api/orders/", { cache: "no-store" })
      ]);

      if (s.ok) setSystem(await s.json());
      if (p.ok) setPortfolio(await p.json());
      if (o.ok) setOrders(await o.json());
    } catch (e) {
      console.error(e);
    }
  }

  useEffect(() => {
    if (!window.location.hash) navigate("Dashboard", { replace: true });
    const onHashChange = () => setActivePage(pageFromHash());
    window.addEventListener("hashchange", onHashChange);
    refresh();
    const timer = setInterval(refresh, 10000);
    return () => {
      clearInterval(timer);
      window.removeEventListener("hashchange", onHashChange);
    };
  }, []);

  useEffect(() => {
    const openMarket = event => {
      if (event.detail?.symbol) {
        sessionStorage.setItem("cerebro.market.symbol", event.detail.symbol);
        sessionStorage.setItem("cerebro.market.name", event.detail.name || "");
        navigate("Markets");
      }
    };
    const navigateEvent = event => {
      const page = event.detail?.page;
      if (page) navigate(page);
    };

    window.addEventListener("cerebro-open-market", openMarket);
    window.addEventListener("cerebro-navigate", navigateEvent);
    return () => {
      window.removeEventListener("cerebro-open-market", openMarket);
      window.removeEventListener("cerebro-navigate", navigateEvent);
    };
  }, []);

  const ready = system?.status === "READY";
  const openOrders = orders?.orders?.filter(
    o => !["FILLED_ALL", "CANCELLED_ALL", "CANCELED_ALL", "FAILED", "DELETED"].includes(
      String(o.status || "").toUpperCase()
    )
  ).length ?? 0;

  return (
    <div className="app">
      <aside className="sidebar">
        <button className="brand brandButton" onClick={() => navigate("Dashboard")} aria-label="Open dashboard">
          <CircleDollarSign size={27}/>
          <div>
            <strong>Cerebro</strong>
            <span>CerebroUI</span>
          </div>
        </button>

        <nav>
          {nav.map(([name, Icon]) => (
            <button
              key={name}
              className={activePage === name ? "active" : ""}
              onClick={() => navigate(name)}
            >
              <Icon size={19}/>
              {name}
            </button>
          ))}
        </nav>

        <div className="sidebarStatus">
          <span className={`dot ${ready ? "green" : "red"}`}></span>
          {ready ? "System Ready" : "System Offline"}
        </div>
      </aside>

      <main>
        <header>
          <div>
            <h1>{activePage}</h1>
            <p>Cerebro simulated-trading control centre</p>
          </div>

          <div className={`statusPill ${ready ? "ready" : "bad"}`}>
            <span className="dot"></span>
            {ready ? "System Ready" : "System Unavailable"}
          </div>
        </header>

        {activePage === "Dashboard" ? (
          <Dashboard system={system} portfolio={portfolio} orders={orders} openOrders={openOrders}/>
        ) : activePage === "Markets" ? (
          <Markets />
        ) : activePage === "Orders" ? (
          <Orders />
        ) : activePage === "Portfolio" ? (
          <Portfolio />
        ) : activePage === "Watchlist" ? (
          <Watchlist />
        ) : activePage === "Strategies" ? (
          <Strategies />
        ) : activePage === "Activity / Logs" ? (
          <Activity />
        ) : activePage === "Settings" ? (
          <Settings />
        ) : null}
      </main>
    </div>
  );
}

function Dashboard({ system, portfolio, orders, openOrders }) {
  const account = portfolio?.account;
  const positions = portfolio?.positions ?? [];
  const latestOrder = orders?.orders?.length ? orders.orders[0] : null;

  return (
    <div className="dashboardSections">
      <CollapsibleSection title="System Overview" subtitle="Broker, market-data and account readiness.">
        <section className="statusGrid">
          <StatusCard label="System" value={system?.status ?? "Loading"} good={system?.status === "READY"}/>
          <StatusCard label="OpenD" value={system?.opend?.connected ? "Connected" : "Disconnected"} good={system?.opend?.connected}/>
          <StatusCard label="Market Data" value={system?.market_data?.status ?? "Loading"} good={system?.market_data?.status === "READY"}/>
          <StatusCard
            label="Trading"
            value={system ? `${system.trading.mode} · ${system.trading.enabled ? "Enabled" : "Disabled"}` : "Loading"}
            good={system?.trading?.enabled}
          />
        </section>
        <section className="metricGrid">
          <Metric label="Portfolio Value" value={money(account?.total_value)}/>
          <Metric label="Cash" value={money(account?.cash)}/>
          <Metric label="Open Positions" value={positions.length}/>
          <Metric label="Pending Orders" value={openOrders}/>
        </section>
      </CollapsibleSection>

      <div className="lowerGrid">
        <CollapsibleSection title="Portfolio" subtitle="Current paper-account summary." actions={<span className="paperBadge">{account?.mode ?? "—"}</span>}>
          <div className="rows">
            <Row label="Total value" value={money(account?.total_value)}/>
            <Row label="Cash" value={money(account?.cash)}/>
            <Row label="Market value" value={money(account?.market_value)}/>
            <Row label="Positions" value={positions.length}/>
          </div>
        </CollapsibleSection>

        <CollapsibleSection title="Recent Order" subtitle="Most recently reported broker order.">
          {latestOrder ? (
            <button className="order orderButton" onClick={() => window.dispatchEvent(new CustomEvent("cerebro-open-market", { detail: { symbol: latestOrder.symbol, name: latestOrder.name } }))}>
              <div>
                <strong>{latestOrder.side} {latestOrder.quantity} {latestOrder.symbol}</strong>
                <span>{latestOrder.name}</span>
              </div>
              <div className="orderStatus">{latestOrder.status}</div>
            </button>
          ) : (
            <div className="empty">No orders yet</div>
          )}
        </CollapsibleSection>
      </div>
    </div>
  );
}

function StatusCard({ label, value, good }) {
  return (
    <div className="statusCard">
      <div className="cardLabel">{label}</div>
      <div className="statusValue"><span className={`dot ${good ? "green" : "amber"}`}></span>{value}</div>
    </div>
  );
}

function Metric({ label, value }) {
  return <div className="metric"><span>{label}</span><strong>{value}</strong></div>;
}

function Row({ label, value }) {
  return <div className="row"><span>{label}</span><strong>{value}</strong></div>;
}

createRoot(document.getElementById("root")).render(<App />);
