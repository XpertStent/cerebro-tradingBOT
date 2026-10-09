import assert from 'node:assert/strict';
import test from 'node:test';
import { fetchJson } from '../src/fetchJson.js';
import { securityLabel, selectedSecurityForQuery } from '../src/marketSelection.js';

test('selected display label resolves to the existing security; edited query starts a new search', () => {
  const selected = { symbol:'US.VOOG', ticker:'VOOG', name:'Growth fund' };
  assert.equal(selectedSecurityForQuery(selected, 'VOOG — Growth fund'), selected);
  assert.equal(selectedSecurityForQuery(selected, 'different ticker'), null);
  assert.equal(securityLabel({symbol:'US.TEST.A',name:'Class A'}), 'TEST.A — Class A');
});

test('request deadline covers a hanging response body and a fetch that ignores abort', async () => {
  for (const fetcher of [() => new Promise(() => {}), async () => ({ok:true,json:() => new Promise(() => {})})]) {
    let expire; let cleared=false;
    const controller=new AbortController();
    const pending=fetchJson('/test',{controller,fetcher,setTimer:f=>{expire=f;return 1;},clearTimer:()=>{cleared=true;}});
    expire();
    await assert.rejects(pending,/timed out/);
    assert.equal(controller.signal.aborted,true);
    assert.equal(cleared,true);
  }
});

test('broker error and expired access session are actionable instead of silent failures', async () => {
  await assert.rejects(fetchJson('/test',{fetcher:async()=>({ok:false,status:504,json:async()=>({detail:'OpenD is still loading'})})}),/OpenD is still loading/);
  await assert.rejects(fetchJson('/test',{fetcher:async()=>({redirected:true,headers:{get:()=> 'text/html'}})}),/access session.*expired/);
});
