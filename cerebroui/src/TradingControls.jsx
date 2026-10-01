import React, { useEffect, useState } from "react";
import { LockKeyhole, RefreshCw, ShieldAlert, Unlock, X } from "lucide-react";
import "./LiveTrading.css";


const nativeFetch = window.fetch.bind(window);

async function isUnlockRequired(response) {
  if (response.status === 423) return true;
  if (![403, 409, 500].includes(response.status)) return false;
  try {
    const data = await response.clone().json();
    return JSON.stringify(data?.detail ?? data).includes("TRADE_UNLOCK_REQUIRED");
  } catch (_) {
    return false;
  }
}

if (!window.__cerebroUnlockInterceptorInstalled) {
  window.__cerebroUnlockInterceptorInstalled = true;
  window.fetch = async (...args) => {
    const response = await nativeFetch(...args);
    if (!(await isUnlockRequired(response))) return response;

    return new Promise(resolve => {
      window.dispatchEvent(new CustomEvent("cerebro-unlock-required", {
        detail: {
          retry: async () => resolve(await nativeFetch(...args)),
          cancel: () => resolve(response),
        },
      }));
    });
  };
}


export async function brokerAction(url, options = {}) {
  return window.fetch(url, options);
}


export default function TradingControls({ onStatus }) {
  const [status, setStatus] = useState(null);
  const [modal, setModal] = useState(false);
  const [pending, setPending] = useState(null);
  const [accounts, setAccounts] = useState([]);
  const [selected, setSelected] = useState("");
  const [message, setMessage] = useState(null);
  const [busy, setBusy] = useState(false);

  async function load(refresh = false) {
    try {
      const response = await nativeFetch(refresh ? "/api/trading/accounts" : "/api/trading/status", { cache: "no-store" });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || `Trading status failed (${response.status})`);

      if (refresh) {
        setAccounts(data.accounts || []);
        const accountId = data.selected_account?.account_id;
        setSelected(String(accountId || (data.accounts?.length === 1 ? data.accounts[0].account_id : "")));
        setStatus(previous => ({ ...(previous || {}), ...data, account: data.selected_account }));
      } else {
        setStatus(data);
      }
      onStatus?.(data);
    } catch (error) {
      setMessage({ kind: "error", text: error.message });
    }
  }

  useEffect(() => {
    load(false);
    const timer = setInterval(() => load(false), 10000);
    const unlockRequired = event => {
      setPending(event.detail || null);
      setModal(true);
      setMessage({ kind: "warn", text: "The broker action is paused until LIVE trading is unlocked." });
      load(true);
    };
    window.addEventListener("cerebro-unlock-required", unlockRequired);
    return () => {
      clearInterval(timer);
      window.removeEventListener("cerebro-unlock-required", unlockRequired);
    };
  }, []);

  const live = String(status?.mode || "").toUpperCase() === "LIVE";
  const unlocked = Boolean(status?.unlocked);

  async function selectAccount() {
    if (!selected) throw new Error("Select the REAL account Cerebro should use.");
    const response = await nativeFetch("/api/trading/account", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ account_id: selected }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "Unable to select LIVE account");
  }

  async function unlock() {
    setBusy(true);
    setMessage(null);
    try {
      await selectAccount();
      const response = await nativeFetch("/api/trading/unlock", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail));
      setStatus(data.status || { ...status, unlocked: true });
      onStatus?.(data.status);
      setModal(false);
      setMessage(null);
      const action = pending;
      setPending(null);
      if (action?.retry) await action.retry();
    } catch (error) {
      setMessage({ kind: "error", text: error.message });
    } finally {
      setBusy(false);
    }
  }

  async function lock() {
    setBusy(true);
    try {
      const response = await nativeFetch("/api/trading/lock", { method: "POST" });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "Unable to lock trading");
      setStatus(data.status || { ...status, unlocked: false });
      onStatus?.(data.status);
    } catch (error) {
      setMessage({ kind: "error", text: error.message });
    } finally {
      setBusy(false);
    }
  }

  function closeModal() {
    pending?.cancel?.();
    setPending(null);
    setModal(false);
    setMessage(null);
  }

  if (!status) return <span className="environmentBadge paper">TRADING…</span>;

  return (
    <>
      <div className="headerTradingControls">
        <span className={`environmentBadge ${live ? "live" : "paper"}`}>
          {live ? "LIVE TRADING" : "PAPER"}
        </span>
        {live && (
          unlocked ? (
            <button className="tradingLockButton unlocked" onClick={lock} disabled={busy} title="Lock live broker actions">
              <Unlock size={16}/>Unlocked
            </button>
          ) : (
            <button className="tradingLockButton locked" onClick={() => { setModal(true); load(true); }} disabled={busy}>
              <LockKeyhole size={16}/>Unlock Trading
            </button>
          )
        )}
      </div>

      {modal && live && (
        <div className="unlockModalBackdrop">
          <section className="unlockModal" role="dialog" aria-modal="true">
            <div className="unlockModalHeader">
              <div>
                <span className="liveMiniBadge">LIVE</span>
                <h2>Unlock Moomoo Trading</h2>
                <p>Choose the REAL account, then unlock OpenD using the server-side hashed credential configured in Portainer.</p>
              </div>
              <button className="unlockClose" onClick={closeModal}><X size={18}/></button>
            </div>

            <div className="unlockWarning">
              <ShieldAlert size={19}/>
              <span>No trading credential is collected by the browser. Cerebro uses MOOMOO_TRADING_PASSWORD_MD5 from the backend container environment.</span>
            </div>

            <label className="unlockField">
              <span>REAL trading account</span>
              <select value={selected} onChange={event => setSelected(event.target.value)}>
                <option value="">Select account</option>
                {accounts.map(account => (
                  <option key={`${account.security_firm}-${account.account_id}`} value={account.account_id}>
                    {account.security_firm} · ••••{String(account.account_id || "").slice(-4)} · {account.account_type}
                  </option>
                ))}
              </select>
            </label>

            {accounts.length === 0 && <div className="unlockStatus error">No ACTIVE REAL account with US trading permission was discovered.</div>}
            {message && <div className={`unlockStatus ${message.kind}`}>{message.text}</div>}

            <div className="unlockActions">
              <button className="unlockCancel" onClick={() => load(true)} disabled={busy}><RefreshCw size={15}/>Refresh accounts</button>
              <button className="unlockCancel" onClick={closeModal} disabled={busy}>Cancel</button>
              <button className="unlockConfirm" onClick={unlock} disabled={busy || !selected}>
                <Unlock size={16}/>{busy ? "Unlocking…" : pending ? "Unlock & Continue" : "Unlock Trading"}
              </button>
            </div>
          </section>
        </div>
      )}
    </>
  );
}
