export function inputGroups(snapshot) {
  const context = snapshot?.context || {};
  return {
    candidates: Array.isArray(context.candidates) ? context.candidates : [],
    shared: Object.fromEntries(Object.entries(context).filter(([key]) => key !== "candidates")),
  };
}

export function requestText(snapshot) {
  return JSON.stringify(snapshot.request, null, 2);
}

export async function copyDecisionText(text) {
  if (navigator.clipboard?.writeText) {
    try { await navigator.clipboard.writeText(text); return; } catch (_) { /* LAN HTTP fallback below. */ }
  }
  const field = document.createElement("textarea");
  const previousFocus = document.activeElement;
  field.value = text;
  field.readOnly = true;
  field.style.cssText = "position:fixed;left:0;top:0;opacity:0";
  document.body.appendChild(field);
  try {
    field.select();
    if (!document.execCommand("copy")) throw new Error("Copy failed. Select and copy the full request text below.");
  } finally {
    field.remove();
    previousFocus?.focus();
  }
}
