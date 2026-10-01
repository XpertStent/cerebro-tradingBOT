import React, { useEffect, useState } from "react";
import {
  RefreshCw,
  Wallet,
  CircleDollarSign,
  TrendingUp,
  Landmark,
  ExternalLink
} from "lucide-react";
import CollapsibleSection from "./CollapsibleSection";
import "./OrdersEnhancements.css";
import "./LiveTrading.css";

function money(value) {
  if (value === null || value === undefined) return "—";
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD"
  }).format(Number(value));
}

function percent(value) {
  if (value === null || value === undefined) return "—";
  return `${Number(value).toFixed(2)}%`;
}

function openMarket(position) {
  window.dispatchEvent(
    new CustomEvent("cerebro-open-market", {
      detail: { symbol: position.symbol, name: position.name }
    })
  );
}

export default function Portfolio() {
  const [portfolio, setPortfolio] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  async function loadPortfolio(force = false) {
    try {
      setError(null);
      const r = await fetch(
        force ? "/api/portfolio/?refresh=true" : "/api/portfolio/",
        { cache: "no-store" }
      );
      const d = await r.json();
      if (!r.ok) throw new Error(d.detail || "Unable to load portfolio");
      setPortfolio(d);
    } catch (e) {
      setPortfolio(null);
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadPortfolio();
    const timer = setInterval(loadPortfolio, 10000);
    return () => clearInterval(timer);
  }, []);

  const account = portfolio?.account;
  const positions = portfolio?.positions || [];
  const unrealized = account?.unrealized_pnl;
  const realized = account?.realized_pnl;
  const mode = String(account?.mode || "PAPER").toUpperCase();
  const live = mode === "LIVE";

  return (
    <div className="portfolioPage">
      {error && <div className="portfolioError">{error}</div>}

      <CollapsibleSection
        title="Portfolio Overview"
        subtitle={`Current ${mode.toLowerCase()} account state reported directly through OpenD.`}
        actions={
          <div className="portfolioActions">
            <span className={live ? "liveBadge" : "portfolioMode"}>{mode}</span>
            <button className="portfolioRefresh" onClick={() => loadPortfolio(true)}>
              <RefreshCw size={16}/>Refresh
            </button>
          </div>
        }
      >
        {account && (
          <div className="previewAccountGrid">
            <div className="previewAccountCard"><span>Account</span><strong>{account.account_id_masked || `••••${String(account.account_id || "").slice(-4)}`}</strong></div>
            <div className="previewAccountCard"><span>Broker</span><strong>{account.security_firm || "—"}</strong></div>
            <div className="previewAccountCard"><span>Available funds</span><strong>{money(account.available_cash)}</strong></div>
          </div>
        )}

        <section className="portfolioMetrics">
          <MetricCard icon={<Landmark size={20}/>} label="Total Value" value={money(account?.total_value)}/>
          <MetricCard icon={<Wallet size={20}/>} label="Cash" value={money(account?.cash)}/>
          <MetricCard icon={<CircleDollarSign size={20}/>} label="Market Value" value={money(account?.market_value)}/>
          <MetricCard icon={<TrendingUp size={20}/>} label="Open Positions" value={positions.length}/>
        </section>

        <section className="pnlGrid">
          <div className="pnlCard">
            <span>Unrealized P&L</span>
            <strong className={unrealized > 0 ? "positive" : unrealized < 0 ? "negative" : ""}>{money(unrealized)}</strong>
          </div>
          <div className="pnlCard">
            <span>Realized P&L</span>
            <strong className={realized > 0 ? "positive" : realized < 0 ? "negative" : ""}>{money(realized)}</strong>
          </div>
        </section>
      </CollapsibleSection>

      <CollapsibleSection
        title="Positions"
        subtitle={`Current ${mode.toLowerCase()} holdings. Use View to open full market details and charts.`}
        actions={<span className="positionCount">{positions.length}</span>}
        bodyClassName="scrollRegion"
      >
        <div className="positionsTableWrap">
          <table className="positionsTable">
            <thead>
              <tr>
                <th>Security</th><th>Qty</th><th>Available</th><th>Avg Cost</th><th>Current</th><th>Market Value</th><th>P&L</th><th>P&L %</th><th>Action</th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr><td colSpan="9" className="positionsEmpty">Loading portfolio…</td></tr>
              ) : positions.length === 0 ? (
                <tr><td colSpan="9" className="positionsEmpty">No open positions</td></tr>
              ) : (
                positions.map(position => (
                  <tr key={position.symbol}>
                    <td><strong>{position.symbol}</strong><span>{position.name}</span></td>
                    <td>{position.quantity}</td>
                    <td>{position.available_quantity}</td>
                    <td>{money(position.average_cost)}</td>
                    <td>{money(position.current_price)}</td>
                    <td>{money(position.market_value)}</td>
                    <td className={position.profit_loss > 0 ? "positive" : position.profit_loss < 0 ? "negative" : ""}>{money(position.profit_loss)}</td>
                    <td className={position.profit_loss_percent > 0 ? "positive" : position.profit_loss_percent < 0 ? "negative" : ""}>{percent(position.profit_loss_percent)}</td>
                    <td>
                      <button className="openSecurityButton" onClick={() => openMarket(position)}><ExternalLink size={14}/>View</button>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </CollapsibleSection>
    </div>
  );
}

function MetricCard({ icon, label, value }) {
  return (
    <div className="portfolioMetric">
      <div className="portfolioMetricIcon">{icon}</div>
      <div><span>{label}</span><strong>{value}</strong></div>
    </div>
  );
}
