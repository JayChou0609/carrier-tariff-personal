const REPO = 'JayChou0609/carrier-tariff-personal';
const WORKFLOW = 'recovery-watchdog.yml';
const SOURCES = ['mobile:quanguo','mobile:jiangsu','mobile:shanghai','mobile:gansu',
  'telecom:quanguo','telecom:jiangsu','telecom:shanghai','telecom:zhejiang',
  'unicom:quanguo','unicom:jiangsu','unicom:shanghai','unicom:hebei','unicom:henan','unicom:sichuan','unicom:guangdong',
  'gb:quanguo','gb:jiangsu'];
const PATHS = ['.github/workflows/scheduled-refresh.yml','.github/workflows/wecom-notify.yml','.github/workflows/recovery-watchdog.yml'];
const batch = value => String(value || '').replace(/^(\d+)-\d+$/, '$1');
export function slotAt(moment) {
  const beijing = new Date(moment.getTime()+8*3600000);
  const hour = beijing.getUTCHours();
  const slot = hour>=18 ? 18 : hour>=12 ? 12 : 0;
  return beijing.toISOString().slice(0,10)+`T${String(slot).padStart(2,'0')}:00:00+08:00`;
}
export function collected(status, slot) {
  const latest = status?.latest || {}, rows = latest.sources || [];
  const ids = new Set(rows.map(row=>row.id));
  return !latest.baseline && rows.length===SOURCES.length && ids.size===SOURCES.length && SOURCES.every(id=>ids.has(id)) &&
    rows.every(row=>row.status==='updated' && Date.parse(row.started)>=Date.parse(slot) &&
      Date.parse(row.snapshotTimestamp || row.timestamp)>=Date.parse(slot));
}
export function notified(health, latest, slot) {
  return health?.version===1 && health.status==='complete' && health.cards===true && health.target_slot===slot &&
    batch(health.collection_run)===batch(latest.id) && JSON.stringify([...(health.buckets || [])].sort())===JSON.stringify(['new','today_off','tomorrow_off']);
}
export async function check(env, request=fetch, moment=new Date()) {
  if (!env.GITHUB_ACTIONS_TOKEN) throw new Error('GITHUB_ACTIONS_TOKEN is not configured');
  const slot=slotAt(moment), stamp=moment.getTime();
  const headers={Authorization:`Bearer ${env.GITHUB_ACTIONS_TOKEN}`, Accept:'application/vnd.github+json',
    'Content-Type':'application/json','User-Agent':'TariffIndependentWatchdog/1.0','X-GitHub-Api-Version':'2022-11-28'};
  async function publicJSON(branch,path,missing=false) {
    const response=await request(`https://raw.githubusercontent.com/${REPO}/${branch}/${path}?watchdog=${stamp}`,
      {redirect:'manual',headers:{'Cache-Control':'no-cache'},signal:AbortSignal.timeout(20000)});
    if (missing && response.status===404) return {};
    if (response.status!==200) throw new Error(`Public completion check HTTP ${response.status}`);
    return response.json();
  }
  let status,health,reason='completion_unknown';
  try {
    [status,health]=await Promise.all([publicJSON('main','data/refresh-status.json'),publicJSON('wecom-notify-state','health.json',true)]);
    if (collected(status,slot) && notified(health,status.latest,slot)) return {status:'complete',target_slot:slot,dispatched:false};
    reason=collected(status,slot)?'notification_incomplete':'collection_missing_or_incomplete';
  } catch {
    // A raw/CDN outage must not dispatch a collector blindly. The GitHub recovery
    // workflow rechecks the checked-out main data before dispatching any child.
    reason='public_completion_check_unavailable';
  }
  const runsResponse=await request(`https://api.github.com/repos/${REPO}/actions/runs?branch=main&per_page=100`,
    {headers,redirect:'manual',signal:AbortSignal.timeout(20000)});
  if (runsResponse.status!==200) throw new Error(`GitHub run check HTTP ${runsResponse.status}`);
  const runs=(await runsResponse.json()).workflow_runs || [];
  if (runs.some(run=>PATHS.includes(run.path) && run.status!=='completed')) return {status:'waiting_for_active_run',target_slot:slot,dispatched:false};
  if (runs.some(run=>run.path===PATHS[2] && stamp-Date.parse(run.created_at)>=0 && stamp-Date.parse(run.created_at)<600000)) {
    return {status:'retry_cooldown',target_slot:slot,dispatched:false};
  }
  const response=await request(`https://api.github.com/repos/${REPO}/actions/workflows/${WORKFLOW}/dispatches`, {
    method:'POST',redirect:'manual',headers,body:JSON.stringify({ref:'main'}),signal:AbortSignal.timeout(20000)
  });
  if (![200,204].includes(response.status)) throw new Error(`GitHub recovery dispatch HTTP ${response.status}`);
  return {status:'recovery_check_dispatched',target_slot:slot,reason,dispatched:true};
}
export default {
  async scheduled(controller,env,ctx) {
    const result=await check(env);
    console.log(JSON.stringify({...result,scheduledAt:new Date(controller.scheduledTime).toISOString()}));
  },
  async fetch() {
    return Response.json({service:'tariff-independent-watchdog',mode:'scheduled-only',
      schedule:'Every 10 minutes; check Beijing 00:00, 12:00 and 18:00 collection and image/text delivery.'});
  }
};
