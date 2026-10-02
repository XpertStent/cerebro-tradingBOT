import assert from 'node:assert/strict';
import test from 'node:test';
import { confirmationMatches, RESOLVED_STATUSES, batchTotals } from '../src/decisionActions.js';

test('confirmation is bound to action, decision, reviewed ticket and rejection reason', () => {
  const p = { decision_id:1, review_key:'old' };
  const armed = { decisionId:1, action:'reject', reviewKey:'old', reason:'Wait for earnings' };
  assert.equal(confirmationMatches(null, p, 'reject'), false);
  assert.equal(confirmationMatches(armed, p, 'reject', 'Wait for earnings'), true);
  assert.equal(confirmationMatches(armed, p, 'approve'), false);
  assert.equal(confirmationMatches(armed, { ...p, review_key:'changed' }, 'reject', 'Wait for earnings'), false);
  assert.equal(confirmationMatches(armed, p, 'reject', 'Changed my reason'), false);
  assert.equal(confirmationMatches(armed, { ...p, decision_id:2 }, 'reject', 'Wait for earnings'), false);
});

test('resolved decisions leave pending cards and batch totals exclude WATCH', () => {
  const proposals = [{status:'REJECTED'},{status:'EXECUTED'},{status:'WATCHLIST_ADDED'},{status:'PENDING_APPROVAL'}];
  assert.deepEqual(proposals.filter(p => !RESOLVED_STATUSES.has(p.status)), [{status:'PENDING_APPROVAL'}]);
  assert.deepEqual(batchTotals([
    {order:{side:'BUY',quantity:2,estimated_price:100}},
    {order:{side:'SELL',quantity:1,price:200,estimated_price:199}},
    {action:'WATCH'}
  ]), {BUY:200,SELL:200});
});
