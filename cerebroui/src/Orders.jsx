import React, { useEffect, useState } from "react";
import {
  Search,
  ShieldCheck,
  ShieldAlert,
  RefreshCw,
  Trash2,
  ExternalLink
} from "lucide-react";

import CollapsibleSection from "./CollapsibleSection";
import "./OrdersEnhancements.css";

const TERMINAL_ORDER_STATES = new Set([
  "FILLED_ALL",
  "CANCELLED_ALL",
  "CANCELED_ALL",
  "FAILED",
  "DISABLED",
  "DELETED"
]);

function openMarket(symbol, name = "") {
  window.dispatchEvent(
    new CustomEvent("cerebro-open-market", {
      detail: { symbol, name }
    })
  );
}

export default function Orders() {
  const [symbolSearch, setSymbolSearch] = useState("");
  const [suggestions, setSuggestions] = useState([]);
  const [symbol, setSymbol] = useState(null);
  const [side, setSide] = useState("BUY");
  const [quantity, setQuantity] = useState("");
  const [orderType, setOrderType] = useState("MARKET");
  const [limitPrice, setLimitPrice] = useState("");
  const [preview, setPreview] = useState(null);
  const [orders, setOrders] = useState([]);
  const [loading, setLoading] = useState(false);
  const [executing, setExecuting] = useState(false);
  const [cancellingId, setCancellingId] = useState(null);
  const [message, setMessage] = useState(null);

  async function loadOrders() {
    try {
      const r = await fetch("/api/orders/", { cache: "no-store" });
      const d = await r.json();
      if (r.ok) setOrders(d.orders || []);
    } catch (_) {}
  }

  async function cancelOrder(order) {
    if (!order?.order_id) return;
    const ok = window.confirm(
      `Cancel pending order ${order.order_id} for ${order.symbol}?`
    );
    if (!ok) return;

    setCancellingId(String(order.order_id));
    setMessage(null);
    try {
      const r = await fetch(
        `/api/orders/${encodeURIComponent(order.order_id)}`,
        { method: "DELETE" }
      );
      const d = await r.json();
      if (!r.ok) {
        throw new Error(
          typeof d.detail === "string" ? d.detail : JSON.stringify(d.detail)
        );
      }
      setMessage({
        type: "success",
        text: `Order ${order.order_id} cancellation submitted.`
      });
      await loadOrders();
    } catch (e) {
      setMessage({ type: "error", text: e.message });
    } finally {
      setCancellingId(null);
    }
  }

  async function searchSymbols(value) {
    const q = value.trim();
    if (!q) {
      setSuggestions([]);
      return;
    }
    try {
      const r = await fetch(
        `/api/market/search?q=${encodeURIComponent(q)}&markets=US,HK,SH,SZ,SG,MY,JP&limit=8`,
        { cache: "no-store" }
      );
      const d = await r.json();
      if (r.ok) setSuggestions(d.results || []);
    } catch (_) {
      setSuggestions([]);
    }
  }

  function chooseSymbol(item) {
    setSymbol(item.symbol);
    setSymbolSearch(`${item.ticker} — ${item.name}`);
    setSuggestions([]);
    setPreview(null);
    setMessage(null);
  }

  function orderPayload() {
    const payload = {
      symbol,
      side,
      quantity: Number(quantity),
      order_type: orderType
    };
    if (orderType === "LIMIT") payload.price = Number(limitPrice);
    return payload;
  }

  async function previewOrder() {
    setLoading(true);
    setMessage(null);
    try {
      const r = await fetch("/api/orders/preview", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(orderPayload())
      });
      const d = await r.json();
      if (!r.ok) {
        throw new Error(
          typeof d.detail === "string" ? d.detail : JSON.stringify(d.detail)
        );
      }
      setPreview(d);
    } catch (e) {
      setPreview(null);
      setMessage({ type: "error", text: e.message });
    } finally {
      setLoading(false);
    }
  }

  async function executeOrder() {
    if (!preview?.approved) return;
    setExecuting(true);
    setMessage(null);
    try {
      const r = await fetch("/api/orders/execute", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(orderPayload())
      });
      const d = await r.json();
      if (!r.ok) {
        throw new Error(
          typeof d.detail === "string" ? d.detail : JSON.stringify(d.detail)
        );
      }
      setMessage({
        type: "success",
        text: `Paper order submitted successfully — Order ${d.order?.order_id ?? ""}`
      });
      setPreview(null);
      await loadOrders();
    } catch (e) {
      setMessage({ type: "error", text: e.message });
    } finally {
      setExecuting(false);
    }
  }

  useEffect(() => {
    loadOrders();
    const timer = setInterval(loadOrders, 10000);
    return () => clearInterval(timer);
  }, []);

  const entryPanel = (
    <>
      <div className="orderField">
        <label>Security</label>
        <div className="orderSymbolSearch">
          <Search size={17}/>
          <input
            value={symbolSearch}
            onChange={e => {
              const value = e.target.value;
              setSymbolSearch(value);
              setSymbol(null);
              setPreview(null);
              setMessage(null);
              if (!value.trim()) {
                setSuggestions([]);
                return;
              }
              clearTimeout(window.__orderSearchTimer);
              window.__orderSearchTimer = setTimeout(
                () => searchSymbols(value),
                200
              );
            }}
            onFocus={() => {
              if (symbolSearch.trim()) searchSymbols(symbolSearch);
            }}
            placeholder="Search ticker or company"
          />
        </div>

        {suggestions.length > 0 && (
          <div className="orderSuggestions">
            {suggestions.map(item => (
              <button key={item.symbol} onClick={() => chooseSymbol(item)}>
                <div>
                  <strong>{item.ticker}</strong>
                  <span>{item.name}</span>
                </div>
                <small>{item.symbol}</small>
              </button>
            ))}
          </div>
        )}

        {symbol && (
          <div className="selectedSymbol">
            Selected: <strong>{symbol}</strong>
          </div>
        )}
      </div>

      <div className="orderField">
        <label>Side</label>
        <div className="sideSelector">
          <button
            className={side === "BUY" ? "buy selected" : "buy"}
            onClick={() => { setSide("BUY"); setPreview(null); }}
          >
            BUY
          </button>
          <button
            className={side === "SELL" ? "sell selected" : "sell"}
            onClick={() => { setSide("SELL"); setPreview(null); }}
          >
            SELL
          </button>
        </div>
      </div>

      <div className="orderFormGrid">
        <div className="orderField">
          <label>Quantity</label>
          <input
            type="number"
            min="0"
            step="1"
            value={quantity}
            onChange={e => { setQuantity(e.target.value); setPreview(null); }}
          />
        </div>
        <div className="orderField">
          <label>Order Type</label>
          <select
            value={orderType}
            onChange={e => { setOrderType(e.target.value); setPreview(null); }}
          >
            <option value="MARKET">Market</option>
            <option value="LIMIT">Limit</option>
          </select>
        </div>
      </div>

      {orderType === "LIMIT" && (
        <div className="orderField">
          <label>Limit Price</label>
          <input
            type="number"
            step="0.01"
            value={limitPrice}
            onChange={e => { setLimitPrice(e.target.value); setPreview(null); }}
            placeholder="Enter limit price"
          />
        </div>
      )}

      <button
        className="previewButton"
        onClick={previewOrder}
        disabled={loading || !symbol || !quantity || (orderType === "LIMIT" && !limitPrice)}
      >
        {loading ? "Checking..." : "Preview Order"}
      </button>

      {message && (
        <div className={`orderMessage ${message.type}`}>{message.text}</div>
      )}
    </>
  );

  const riskPanel = !preview ? (
    <div className="riskEmpty">Preview an order to run the risk engine.</div>
  ) : (
    <>
      <div className={preview.approved ? "riskDecision approved" : "riskDecision blocked"}>
        {preview.approved ? <ShieldCheck size={25}/> : <ShieldAlert size={25}/>} 
        <div>
          <strong>{preview.approved ? "APPROVED" : "BLOCKED"}</strong>
          <span>{preview.mode} execution</span>
        </div>
      </div>

      <div className="previewSummary">
        <PreviewRow label="Security" value={preview.symbol}/>
        <PreviewRow label="Side" value={preview.side}/>
        <PreviewRow label="Quantity" value={preview.quantity}/>
        <PreviewRow label="Estimated Price" value={`$${Number(preview.estimated_price).toFixed(2)}`}/>
        <PreviewRow label="Estimated Value" value={`$${Number(preview.estimated_value).toFixed(2)}`}/>
      </div>

      <div className="riskChecks">
        {preview.risk_checks?.map(check => (
          <div key={check.name} className={check.passed ? "riskCheck pass" : "riskCheck fail"}>
            <span className="riskCheckDot"></span>
            <div>
              <strong>{check.name.replaceAll("_", " ")}</strong>
              <p>{check.message}</p>
            </div>
          </div>
        ))}
      </div>

      <button
        className="executeButton"
        disabled={!preview.approved || executing}
        onClick={executeOrder}
      >
        {executing ? "Submitting..." : preview.approved ? "Execute Paper Order" : "Execution Blocked"}
      </button>
    </>
  );

  return (
    <div className="ordersPage">
      <div className="ordersTwoColumn">
        <CollapsibleSection
          title="New Order"
          subtitle="Preview through Cerebro risk controls before execution."
          actions={<span className="paperBadge">PAPER</span>}
        >
          {entryPanel}
        </CollapsibleSection>

        <CollapsibleSection
          title="Risk Preview"
          subtitle="Cerebro makes the final execution decision."
        >
          {riskPanel}
        </CollapsibleSection>
      </div>

      <CollapsibleSection
        title="Order History"
        subtitle="Paper account orders reported by OpenD. Open any security in Markets or cancel a pending order."
        actions={
          <button className="refreshOrders" onClick={loadOrders}>
            <RefreshCw size={16}/>
            Refresh
          </button>
        }
        bodyClassName="ordersScrollable"
      >
        <div className="ordersTableWrap">
          <table className="ordersTable">
            <thead>
              <tr>
                <th>Symbol</th>
                <th>Side</th>
                <th>Type</th>
                <th>Qty</th>
                <th>Filled</th>
                <th>Avg Fill</th>
                <th>Status</th>
                <th>Order ID</th>
                <th>Action</th>
              </tr>
            </thead>
            <tbody>
              {orders.length === 0 ? (
                <tr>
                  <td colSpan="9" className="ordersEmpty">No orders yet</td>
                </tr>
              ) : (
                orders.slice().reverse().map(order => {
                  const terminal = TERMINAL_ORDER_STATES.has(
                    String(order.status || "").toUpperCase()
                  );
                  const cancelling = cancellingId === String(order.order_id);
                  return (
                    <tr key={order.order_id}>
                      <td>
                        <strong>{order.symbol}</strong>
                        <span>{order.name}</span>
                      </td>
                      <td>
                        <span className={order.side === "BUY" ? "sideBuy" : "sideSell"}>
                          {order.side}
                        </span>
                      </td>
                      <td>{order.order_type}</td>
                      <td>{order.quantity}</td>
                      <td>{order.filled_quantity}</td>
                      <td>{Number(order.filled_average_price || 0).toFixed(2)}</td>
                      <td><span className="orderStatusBadge">{order.status}</span></td>
                      <td>{order.order_id}</td>
                      <td>
                        <div className="orderActionGroup">
                          <button
                            className="openSecurityButton"
                            onClick={() => openMarket(order.symbol, order.name)}
                            title={`Open ${order.symbol} in Markets`}
                          >
                            <ExternalLink size={14}/>
                            View
                          </button>
                          {!terminal ? (
                            <button
                              className="cancelOrderButton"
                              disabled={cancelling}
                              onClick={() => cancelOrder(order)}
                              title="Cancel pending order"
                            >
                              <Trash2 size={14}/>
                              {cancelling ? "Cancelling..." : "Cancel"}
                            </button>
                          ) : null}
                        </div>
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      </CollapsibleSection>
    </div>
  );
}

function PreviewRow({ label, value }) {
  return (
    <div className="previewRow">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}
