"""Collect at most once per completed Beijing slot; retry missing/incomplete slots."""
import datetime as dt
import json
import os
from pathlib import Path
from refresh_tariffs import TARGETS,ROOT

TZ=dt.timezone(dt.timedelta(hours=8))


def parse_time(value):
    try:
        value=dt.datetime.fromisoformat(str(value).replace('Z','+00:00'))
        return value.replace(tzinfo=TZ) if value.tzinfo is None else value.astimezone(TZ)
    except (TypeError,ValueError):return None


def decide(status,moment=None,force=False):
    moment=moment or dt.datetime.now(TZ)
    moment=moment.astimezone(TZ)
    hour=next(h for h in [18,12,0] if moment.hour>=h)
    slot=moment.replace(hour=hour,minute=0,second=0,microsecond=0)
    result={'collect':True,'target_slot':slot.isoformat(),'reason':'当期尚未完整采集'}
    if force:
        return dict(result,reason='手动强制重新采集')
    latest=(status or {}).get('latest') or {}
    expected={c+':'+r for c,regions in TARGETS.items() for r in regions}
    rows=latest.get('sources') or []
    if latest.get('baseline') or len(rows)!=len(expected) or {r.get('id') for r in rows}!=expected:
        return result
    for row in rows:
        start=parse_time(row.get('started'))
        snapshot=parse_time(row.get('snapshotTimestamp') or row.get('timestamp'))
        if row.get('status')!='updated' or start is None or snapshot is None or start<slot or snapshot<slot:
            return result
    return dict(result,collect=False,reason='当期全部范围已完整更新，跳过重复采集')


def main():
    try:status=json.loads((ROOT/'data/refresh-status.json').read_text())
    except (OSError,ValueError):status={}
    result=decide(status,force=os.environ.get('FORCE_COLLECTION')=='true')
    print(json.dumps(result,ensure_ascii=False))
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'],'a') as f:
            f.write('collect='+str(result['collect']).lower()+'\n')
            f.write('target_slot='+result['target_slot']+'\n')
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'],'a') as f:
            f.write('## 采集时段检查\n\n目标时段：'+result['target_slot']+'\n\n'+result['reason']+'\n')


if __name__=='__main__':main()
