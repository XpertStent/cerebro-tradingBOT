import React, { useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  ChevronDown,
  RotateCcw,
  Save,
  ShieldCheck,
} from "lucide-react";

import "./Settings.css";


function displayValue(item, value) {
  if (item.type === "number" && item.weight_group) {
    return Number(value ?? 0) * 100;
  }
  return value ?? "";
}

function payloadValue(item, value) {
  if (item.type === "integer") return Number.parseInt(value, 10);
  if (item.type === "number") return Number(value);
  return value;
}

function SettingControl({ item, value, onChange, disabled }) {
  const id = `setting-${item.key.replaceAll(".", "-")}`;

  if (item.type === "boolean") {
    return (
      <label className="settingToggle" htmlFor={id}>
        <input
          id={id}
          type="checkbox"
          checked={Boolean(value)}
          disabled={disabled || item.read_only}
          onChange={e => onChange(e.target.checked)}
        />
        <span className="toggleTrack"><span /></span>
        <b>{value ? "On" : "Off"}</b>
      </label>
    );
  }

  if (item.type === "enum") {
    return (
      <select
        id={id}
        value={value ?? ""}
        disabled={disabled || item.read_only}
        onChange={e => onChange(e.target.value)}
      >
        {(item.options || []).map(option => (
          <option key={option} value={option}>{option}</option>
        ))}
      </select>
    );
  }

  if (item.type === "secret") {
    return (
      <div className="secretControl">
        <input
          id={id}
          type="password"
          value={value ?? ""}
          placeholder={item.configured ? "Configured — enter to replace" : `Enter ${item.label}`}
          autoComplete="new-password"
          autoCapitalize="none"
          spellCheck={false}
          disabled={disabled || item.read_only}
          onChange={e => onChange(e.target.value)}
        />
        <span className={item.configured ? "configured" : "notConfigured"}>
          {item.configured ? "Configured" : "Not configured"}
        </span>
      </div>
    );
  }

  const numeric = item.type === "integer" || item.type === "number";
  const min = item.weight_group ? Number(item.min ?? 0) * 100 : item.min;
  const max = item.weight_group ? Number(item.max ?? 1) * 100 : item.max;

  return (
    <div className="inputWithUnit">
      <input
        id={id}
        type={numeric ? "number" : "text"}
        value={displayValue(item, value)}
        min={numeric ? min : undefined}
        max={numeric ? max : undefined}
        step={item.type === "integer" ? 1 : item.weight_group ? 1 : "any"}
        disabled={disabled || item.read_only}
        onChange={e => onChange(
          item.weight_group
            ? Number(e.target.value) / 100
            : e.target.value
        )}
      />
      {item.weight_group ? <span>%</span> : item.unit ? <span>{item.unit}</span> : null}
    </div>
  );
}

function SettingRow({ item, value, onChange, disabled }) {
  return (
    <div className={`settingRow ${item.future ? "futureSetting" : ""}`}>
      <div className="settingCopy">
        <div className="settingLabelLine">
          <label htmlFor={`setting-${item.key.replaceAll(".", "-")}`}>{item.label}</label>
          {item.future && <span className="futurePill">Next phase</span>}
          {item.read_only && <span className="readonlyPill">Read only</span>}
        </div>
        {item.description && <p>{item.description}</p>}
        <code>{item.key}</code>
      </div>
      <div className="settingControlWrap">
        <SettingControl item={item} value={value} onChange={onChange} disabled={disabled} />
      </div>
    </div>
  );
}

export default function Settings() {
  const [snapshot, setSnapshot] = useState(null);
  const [values, setValues] = useState({});
  const [dirty, setDirty] = useState(new Set());
  const [activeSection, setActiveSection] = useState("General");
  const [openGroups, setOpenGroups] = useState(new Set());
  const [status, setStatus] = useState(null);
  const [saving, setSaving] = useState(false);

  async function load() {
    const response = await fetch("/api/settings", { cache: "no-store" });
    if (!response.ok) throw new Error(`Settings request failed (${response.status})`);
    const data = await response.json();
    const next = {};
    for (const item of data.settings || []) next[item.key] = item.value;
    setSnapshot(data);
    setValues(next);
    setDirty(new Set());
    setStatus(null);
    if (data.sections?.length && !data.sections.includes(activeSection)) {
      setActiveSection(data.sections[0]);
    }
  }

  useEffect(() => {
    load().catch(error => setStatus({ kind: "error", text: error.message }));
  }, []);

  const currentItems = useMemo(
    () => (snapshot?.settings || []).filter(item => item.section === activeSection),
    [snapshot, activeSection]
  );

  const subsections = useMemo(() => {
    const groups = [];
    for (const item of currentItems) {
      const name = item.subsection || "General";
      if (!groups.includes(name)) groups.push(name);
    }
    return groups;
  }, [currentItems]);

  const weightTotals = useMemo(() => {
    const totals = {};
    for (const item of snapshot?.settings || []) {
      if (!item.weight_group) continue;
      totals[item.weight_group] = (totals[item.weight_group] || 0) + Number(values[item.key] ?? item.value ?? 0);
    }
    return totals;
  }, [snapshot, values]);

  function change(item, value) {
    setValues(previous => ({ ...previous, [item.key]: value }));
    setDirty(previous => new Set([...previous, item.key]));
    setStatus(null);
  }

  async function save() {
    const outgoing = {};
    for (const key of dirty) {
      const item = snapshot.settings.find(entry => entry.key === key);
      if (!item || item.read_only) continue;
      if (item.type === "secret" && !values[key]) continue;
      outgoing[key] = payloadValue(item, values[key]);
    }

    if (!Object.keys(outgoing).length) {
      setStatus({ kind: "ok", text: "No unsaved changes." });
      return;
    }

    setSaving(true);
    try {
      const response = await fetch("/api/settings", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ values: outgoing }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || `Save failed (${response.status})`);
      const next = {};
      for (const item of data.settings || []) next[item.key] = item.value;
      setSnapshot(data);
      setValues(next);
      setDirty(new Set());
      setStatus({ kind: "ok", text: "Settings saved." });
    } catch (error) {
      setStatus({ kind: "error", text: error.message });
    } finally {
      setSaving(false);
    }
  }

  async function resetSection() {
    const prompt = activeSection === "API KEYS"
      ? "Clear all saved API keys? Environment-configured credentials, if any, will still be used."
      : `Reset all ${activeSection} settings to defaults?`;
    if (!window.confirm(prompt)) return;
    setSaving(true);
    try {
      const response = await fetch("/api/settings/reset", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ section: activeSection }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || `Reset failed (${response.status})`);
      const next = {};
      for (const item of data.settings || []) next[item.key] = item.value;
      setSnapshot(data);
      setValues(next);
      setDirty(new Set());
      setStatus({ kind: "ok", text: `${activeSection} reset to defaults.` });
    } catch (error) {
      setStatus({ kind: "error", text: error.message });
    } finally {
      setSaving(false);
    }
  }

  function toggleGroup(name) {
    setOpenGroups(previous => {
      const next = new Set(previous);
      next.has(name) ? next.delete(name) : next.add(name);
      return next;
    });
  }

  if (!snapshot) {
    return <div className="settingsLoading">Loading settings…</div>;
  }

  return (
    <div className="settingsShell">
      <aside className="settingsNav">
        <div className="settingsNavTitle">Configuration</div>
        {snapshot.sections.map(section => (
          <button
            key={section}
            className={activeSection === section ? "active" : ""}
            onClick={() => setActiveSection(section)}
          >
            {section}
          </button>
        ))}
      </aside>

      <section className="settingsContent">
        <div className="settingsToolbar">
          <div>
            <h2>{activeSection}</h2>
            <p>{dirty.size ? `${dirty.size} unsaved change${dirty.size === 1 ? "" : "s"}` : "All changes saved"}</p>
          </div>
          <div className="settingsActions">
            <button className="secondaryButton" onClick={resetSection} disabled={saving}>
              <RotateCcw size={16} /> {activeSection === "API KEYS" ? "Clear saved keys" : "Reset section"}
            </button>
            <button className="primaryButton" onClick={save} disabled={saving || dirty.size === 0}>
              <Save size={16} /> {saving ? "Saving…" : "Save changes"}
            </button>
          </div>
        </div>

        {status && (
          <div className={`settingsMessage ${status.kind}`}>
            {status.kind === "ok" ? <CheckCircle2 size={17} /> : <AlertTriangle size={17} />}
            {status.text}
          </div>
        )}

        {activeSection === "API KEYS" && (
          <div className="settingsNotice">
            <ShieldCheck size={19} />
            <div>
              <strong>Credentials stay masked.</strong>
              <span>Saved credentials are never returned to the browser. Enter a new value to replace a key, or leave its field blank to keep the existing value.</span>
            </div>
          </div>
        )}

        {subsections.map(subsection => {
          const items = currentItems.filter(item => (item.subsection || "General") === subsection);
          const advanced = activeSection === "Advanced Quant Model";
          const collapsed = advanced && !openGroups.has(subsection);
          const weightGroup = items.find(item => item.weight_group)?.weight_group;
          const total = weightGroup ? (weightTotals[weightGroup] || 0) * 100 : null;
          const weightOk = total === null || Math.abs(total - 100) < 0.01;

          return (
            <div className="settingsGroup" key={subsection}>
              <button
                className={`settingsGroupHeader ${advanced ? "clickable" : ""}`}
                onClick={() => advanced && toggleGroup(subsection)}
              >
                <div>
                  <h3>{subsection}</h3>
                  {total !== null && (
                    <span className={weightOk ? "weightOk" : "weightBad"}>
                      Total {total.toFixed(0)}% {weightOk ? "✓" : "— must equal 100%"}
                    </span>
                  )}
                </div>
                {advanced && <ChevronDown size={18} className={collapsed ? "" : "expanded"} />}
              </button>

              {!collapsed && (
                <div className="settingsRows">
                  {items.map(item => (
                    <SettingRow
                      key={item.key}
                      item={item}
                      value={values[item.key]}
                      onChange={value => change(item, value)}
                      disabled={saving}
                    />
                  ))}
                </div>
              )}
            </div>
          );
        })}
      </section>
    </div>
  );
}
