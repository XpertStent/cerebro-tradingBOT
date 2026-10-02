export const RESOLVED_STATUSES = new Set(["REJECTED", "APPROVED", "EXECUTED", "WATCHLIST_ADDED"]);

export function confirmationMatches(armed, proposal, action, reason = "") {
  return armed?.decisionId === proposal.decision_id && armed?.action === action &&
    armed?.reviewKey === proposal.review_key && armed?.reason === reason;
}

export function batchTotals(proposals) {
  return proposals.reduce((totals, proposal) => {
    const order = proposal.order;
    if (order) {
      const amount = Number(order.quantity) * Number(order.price ?? order.estimated_price);
      if (Number.isFinite(amount) && ["BUY", "SELL"].includes(order.side)) totals[order.side] += amount;
    }
    return totals;
  }, { BUY: 0, SELL: 0 });
}
