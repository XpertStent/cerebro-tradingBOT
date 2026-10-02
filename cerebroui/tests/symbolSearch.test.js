import assert from 'node:assert/strict';
import test from 'node:test';
import { createSymbolSearch } from '../src/symbolSearch.js';
const options = { markets:['US'], limit:8 };
const response = results => ({ ok:true, json:async () => ({ results }) });

test('stale responses and clearing cannot repopulate the suggestions', async () => {
  const states = [], pending = [];
  const worker = createSymbolSearch({ publish:s => states.push(s), fetcher:(_, args) => new Promise(resolve => pending.push({ resolve, signal:args.signal })) });
  const old = worker.run('old-symbol', options);
  const current = worker.run('new-symbol', options);
  assert.equal(pending[0].signal.aborted, true);
  pending[1].resolve(response([{ symbol:'US.NEW' }])); await current;
  pending[0].resolve(response([{ symbol:'US.OLD' }])); await old;
  assert.deepEqual(states.at(-1).results, [{ symbol:'US.NEW' }]);
  const next = worker.run('clear-me', options);worker.cancel();
  pending[2].resolve(response([{ symbol:'US.CLEAR' }]));await next;
  assert.deepEqual(states.at(-1).results, []);
});

test('typing uses one field timer, explicit search cancels debounce, and cache is scoped to market', async () => {
  const states=[], timers=new Map();let timerId=0,calls=0;
  const worker=createSymbolSearch({publish:s=>states.push(s),setTimer:f=>{timers.set(++timerId,f);return timerId;},clearTimer:id=>timers.delete(id),
    fetcher:async()=>{calls+=1;return response([{symbol:'US.TEST'}]);}});
  worker.schedule('t',options);assert.equal(timers.size,0);
  worker.schedule('te',options);worker.schedule('test-cache',options);assert.equal(timers.size,1);
  await worker.run('test-cache',options);assert.equal(timers.size,0);assert.equal(calls,1);
  await worker.run('test-cache',options);assert.equal(calls,1);
  await worker.run('test-cache',{...options,markets:['HK']});assert.equal(calls,2);
  assert.equal(states.at(-1).searching,false);
});
