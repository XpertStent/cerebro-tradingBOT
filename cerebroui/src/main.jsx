import React, { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  LayoutDashboard,
  LineChart,
  BrainCircuit,
  ClipboardList,
  Wallet,
  ScrollText,
  Settings,
  CircleDollarSign
} from "lucide-react";

import "./style.css";
import Markets from "./Markets";
import Orders from "./Orders";
import Portfolio from "./Portfolio";
import Activity from "./Activity";

const nav = [
  ["Dashboard", LayoutDashboard],
  ["Markets", LineChart],
  ["Strategies", BrainCircuit],
  ["Orders", ClipboardList],
  ["Portfolio", Wallet],
  ["Activity / Logs", ScrollText],
  ["Settings", Settings]
];

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
  const [activePage, setActivePage] = useState("Dashboard");

  async function refresh() {
    try {
      const [s, p, o] = await Promise.all([
        fetch("/api/system/status", { cache: "no-store" }),
        fetch("/api/portfolio/", { cache: "no-store" }),
        fetch("/api/orders/", { cache: "no-store" })
      ]);

      setSystem(await s.json());
      setPortfolio(await p.json());
      setOrders(await o.json());

    } catch (e) {
      console.error(e);
    }
  }

  useEffect(() => {
    refresh();
    const timer = setInterval(refresh, 10000);
    return () => clearInterval(timer);
  }, []);

  useEffect(() => {
    const openMarket = event => {
      if (event.detail?.symbol) {
        sessionStorage.setItem(
          "cerebro.market.symbol",
          event.detail.symbol
        );

        sessionStorage.setItem(
          "cerebro.market.name",
          event.detail.name || ""
        );

        setActivePage("Markets");
      }
    };

    window.addEventListener(
      "cerebro-open-market",
      openMarket
    );

    return () => {
      window.removeEventListener(
        "cerebro-open-market",
        openMarket
      );
    };
  }, []);

  const ready = system?.status === "READY";

  const openOrders =
    orders?.orders?.filter(
      o => !["FILLED_ALL", "CANCELLED_ALL", "FAILED"].includes(o.status)
    ).length ?? 0;

  return (
    <div className="app">

      <aside className="sidebar">
        <div className="brand">
          <CircleDollarSign size={27}/>
          <div>
            <strong>Cerebro</strong>
            <span>CerebroUI</span>
          </div>
        </div>

        <nav>
          {nav.map(([name, Icon]) => (
            <button
              key={name}
              className={activePage === name ? "active" : ""}
              onClick={() => setActivePage(name)}
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
            <p>Cerebro trading control centre</p>
          </div>

          <div className={`statusPill ${ready ? "ready" : "bad"}`}>
            <span className="dot"></span>
            {ready ? "System Ready" : "System Unavailable"}
          </div>
        </header>

        {activePage === "Dashboard" ? (
          <Dashboard
            system={system}
            portfolio={portfolio}
            orders={orders}
            openOrders={openOrders}
          />
        ) : activePage === "Markets" ? (
          <Markets />
        ) : activePage === "Orders" ? (
          <Orders />
        ) : activePage === "Portfolio" ? (
          <Portfolio />
        ) : activePage === "Activity / Logs" ? (
          <Activity />
        ) : (
          <div className="placeholder">
            <h2>{activePage}</h2>
            <p>This module will be added next.</p>
          </div>
        )}

      </main>
    </div>
  );
}

function Dashboard({ system, portfolio, orders, openOrders }) {
  const account = portfolio?.account;
  const positions = portfolio?.positions ?? [];

  const latestOrder =
    orders?.orders?.length
      ? orders.orders[orders.orders.length - 1]
      : null;

  return (
    <>
      <section className="statusGrid">

        <StatusCard
          label="System"
          value={system?.status ?? "Loading"}
          good={system?.status === "READY"}
        />

        <StatusCard
          label="OpenD"
          value={system?.opend?.connected ? "Connected" : "Disconnected"}
          good={system?.opend?.connected}
        />

        <StatusCard
          label="Market Data"
          value={system?.market_data?.status ?? "Loading"}
          good={system?.market_data?.status === "READY"}
        />

        <StatusCard
          label="Trading"
          value={
            system
              ? `${system.trading.mode} · ${
                  system.trading.enabled ? "Enabled" : "Disabled"
                }`
              : "Loading"
          }
          good={system?.trading?.enabled}
        />

      </section>

      <section className="metricGrid">

        <Metric
          label="Portfolio Value"
          value={money(account?.total_value)}
        />

        <Metric
          label="Cash"
          value={money(account?.cash)}
        />

        <Metric
          label="Open Positions"
          value={positions.length}
        />

        <Metric
          label="Pending Orders"
          value={openOrders}
        />

      </section>

      <section className="lowerGrid">

        <div className="panel">
          <div className="panelHeader">
            <h2>Portfolio</h2>
            <span>{account?.mode ?? "—"}</span>
          </div>

          <div className="rows">
            <Row label="Total value" value={money(account?.total_value)} />
            <Row label="Cash" value={money(account?.cash)} />
            <Row label="Market value" value={money(account?.market_value)} />
            <Row label="Positions" value={positions.length} />
          </div>
        </div>

        <div className="panel">
          <div className="panelHeader">
            <h2>Recent Order</h2>
          </div>

          {latestOrder ? (
            <div className="order">
              <div>
                <strong>
                  {latestOrder.side} {latestOrder.quantity} {latestOrder.symbol}
                </strong>
                <span>{latestOrder.name}</span>
              </div>

              <div className="orderStatus">
                {latestOrder.status}
              </div>
            </div>
          ) : (
            <div className="empty">
              No orders yet
            </div>
          )}
        </div>

      </section>
    </>
  );
}

function StatusCard({ label, value, good }) {
  return (
    <div className="statusCard">
      <div className="cardLabel">{label}</div>
      <div className="statusValue">
        <span className={`dot ${good ? "green" : "amber"}`}></span>
        {value}
      </div>
    </div>
  );
}

function Metric({ label, value }) {
  return (
    <div className="metric">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function Row({ label, value }) {
  return (
    <div className="row">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

createRoot(document.getElementById("root")).render(<App />);
