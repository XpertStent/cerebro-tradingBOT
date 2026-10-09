export function securityLabel(item) {
  const ticker = item.ticker || String(item.symbol).split('.').slice(1).join('.');
  return item.name ? `${ticker} — ${item.name}` : ticker;
}

export function selectedSecurityForQuery(selection, query) {
  return selection && query.trim() === securityLabel(selection) ? selection : null;
}
