import assert from 'node:assert/strict';
import worker,{check,collected,notified,slotAt} from './worker.mjs';
const moment=new Date('2026-11-13T04:22:00Z'), slot='2026-11-13T12:00:00+08:00';
const ids=['mobile:quanguo','mobile:jiangsu','mobile:shanghai','mobile:gansu','telecom:quanguo','telecom:jiangsu','telecom:shanghai','telecom:zhejiang','unicom:quanguo','unicom:jiangsu','unicom:shanghai','unicom:hebei','unicom:henan','unicom:sichuan','unicom:guangdong','gb:quanguo','gb:jiangsu'];
const archive={latest:{id:'123-2',sources:ids.map(id=>({id,status:'updated',started:'2026-11-13T12:01:00+08:00',snapshotTimestamp:'2026-11-13T12:10:00+08:00'}))}};
const health={version:1,status:'complete',cards:true,target_slot:slot,collection_run:'123-1',buckets:['new','today_off','tomorrow_off']};
function transport({status=archive,receipt=health,runs=[],dispatchStatus=204}={}) {
  const calls=[];
  return {calls,async request(url,options={}) {
    calls.push({url,options});
    if (url.includes('/dispatches')) return {status:dispatchStatus};
    if (url.includes('/actions/runs?')) return {status:200,json:async()=>({workflow_runs:runs})};
    if (url.includes('/health.json?')) return receipt===null?{status:404}:{status:200,json:async()=>receipt};
    return {status:200,json:async()=>status};
  }};
}
export async function runChecks() {
  assert.equal(slotAt(moment),slot);
  assert.equal(slotAt(new Date('2026-11-12T16:02:00Z')),'2026-11-13T00:00:00+08:00');
  assert.equal(slotAt(new Date('2026-11-13T10:02:00Z')),'2026-11-13T18:00:00+08:00');
  assert(collected(archive,slot));assert(notified(health,archive.latest,slot));
  assert(!collected({latest:{sources:archive.latest.sources.slice(1)}},slot));
  assert(!notified({...health,cards:false},archive.latest,slot));
  await assert.rejects(check({},()=>{throw Error('must not send')},moment),/not configured/);
  let t=transport();assert.equal((await check({GITHUB_ACTIONS_TOKEN:'test-token'},t.request,moment)).status,'complete');
  assert.equal(t.calls.length,2);assert(t.calls.every(c=>!c.options.headers.Authorization));
  t=transport({receipt:null});assert.equal((await check({GITHUB_ACTIONS_TOKEN:'test-token'},t.request,moment)).status,'recovery_check_dispatched');
  let dispatch=t.calls.find(c=>c.options.method==='POST');assert(dispatch.url.endsWith('/recovery-watchdog.yml/dispatches'));
  assert.equal(JSON.parse(dispatch.options.body).ref,'main');assert.equal(dispatch.options.redirect,'error');
  for (const active of ['queued','in_progress','waiting']) {
    t=transport({receipt:null,runs:[{path:'.github/workflows/scheduled-refresh.yml',status:active}]});
    assert.equal((await check({GITHUB_ACTIONS_TOKEN:'test-token'},t.request,moment)).status,'waiting_for_active_run');
    assert(!t.calls.some(c=>c.options.method==='POST'));
  }
  t=transport({receipt:null,runs:[{path:'.github/workflows/recovery-watchdog.yml',status:'completed',created_at:'2026-11-13T04:20:00Z'}]});
  assert.equal((await check({GITHUB_ACTIONS_TOKEN:'test-token'},t.request,moment)).status,'retry_cooldown');
  t=transport({receipt:null,dispatchStatus:403});
  await assert.rejects(check({GITHUB_ACTIONS_TOKEN:'test-token'},t.request,moment),e=>e.message==='GitHub recovery dispatch HTTP 403');
  assert.equal((await worker.fetch()).status,200);
  return 'Worker preflight, slot dates, no-op, queue wait, cooldown, dispatch and secret isolation passed';
}
export const result=await runChecks();
