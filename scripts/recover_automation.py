#!/usr/bin/env python3
"""Idempotent recovery entry point called by the independent cloud scheduler."""
import base64
import datetime as dt
import json
import os
from pathlib import Path
import urllib.error
import urllib.request

from schedule_guard import decide, parse_time, TZ
from wecom_tariffs import collection_key

REPOSITORY = 'JayChou0609/carrier-tariff-personal'
COLLECTOR = 'scheduled-refresh.yml'
NOTIFIER = 'wecom-notify.yml'
ROOT = Path(__file__).resolve().parents[1]


class RecoveryError(RuntimeError):
    pass


class GitHub:
    def __init__(self, token):
        if not token:
            raise RecoveryError('Missing Actions token')
        self.token = token

    def api(self, method, path, data=None, missing=False):
        req = urllib.request.Request('https://api.github.com/repos/'+REPOSITORY+'/'+path,
            data=json.dumps(data).encode() if data is not None else None, method=method,
            headers={'Authorization':'Bearer '+self.token, 'Accept':'application/vnd.github+json',
                     'Content-Type':'application/json', 'User-Agent':'TariffRecovery/1.0',
                     'X-GitHub-Api-Version':'2022-11-28'})
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                raw = response.read()
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as exc:
            if missing and exc.code == 404:
                return None
            raise RecoveryError('GitHub recovery API HTTP '+str(exc.code)) from None
        except (OSError, ValueError):
            raise RecoveryError('GitHub recovery connection or response failed') from None

    def runs(self, workflow):
        return self.api('GET','actions/workflows/'+workflow+'/runs?branch=main&per_page=100')['workflow_runs']

    def health(self):
        data = self.api('GET','contents/health.json?ref=wecom-notify-state',missing=True)
        if data is None:
            return {}
        try:
            return json.loads(base64.b64decode(data['content'],validate=False))
        except (KeyError, ValueError):
            raise RecoveryError('Invalid notification completion receipt') from None

    def dispatch(self, workflow, inputs):
        self.api('POST','actions/workflows/'+workflow+'/dispatches',{'ref':'main','inputs':inputs})


def delivery_complete(health, latest, slot):
    return bool(isinstance(health,dict) and health.get('version') == 1
                and health.get('status') == 'complete' and health.get('cards') is True
                and health.get('target_slot') == slot
                and collection_key(health.get('collection_run','')) == collection_key(latest.get('id',''))
                and sorted(health.get('buckets') or []) == ['new','today_off','tomorrow_off'])


def pending(runs):
    return any(r.get('status') != 'completed' for r in runs)


def cooling_down(runs, moment):
    # Also covers an API dispatch accepted just before a run record becomes visible.
    starts = [parse_time(r.get('created_at')) for r in runs]
    return any(t and dt.timedelta(0) <= moment-t < dt.timedelta(minutes=10) for t in starts)


def recover(status, github, moment=None):
    moment = (moment or dt.datetime.now(TZ)).astimezone(TZ)
    plan = decide(status,moment)
    slot = plan['target_slot']
    latest = (status or {}).get('latest') or {}
    if plan['collect']:
        workflow, inputs, reason = COLLECTOR, {'catch_up':True}, 'collection_missing_or_incomplete'
    else:
        if delivery_complete(github.health(), latest, slot):
            return {'status':'complete','target_slot':slot,'dispatched':False}
        workflow, inputs, reason = NOTIFIER, {'action':'recover'}, 'notification_incomplete'
    runs = github.runs(workflow)
    if pending(runs):
        return {'status':'waiting_for_active_run','target_slot':slot,'workflow':workflow,'dispatched':False}
    if cooling_down(runs,moment):
        return {'status':'retry_cooldown','target_slot':slot,'workflow':workflow,'dispatched':False}
    github.dispatch(workflow,inputs)
    return {'status':'dispatched','reason':reason,'target_slot':slot,'workflow':workflow,'dispatched':True}


def main():
    if os.environ.get('GITHUB_REPOSITORY') != REPOSITORY:
        raise RecoveryError('Recovery is restricted to the configured repository')
    status = json.loads((ROOT/'data/refresh-status.json').read_text())
    result = recover(status,GitHub(os.environ.get('GITHUB_TOKEN','')))
    print(json.dumps(result,ensure_ascii=False))
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'],'a') as stream:
            stream.write('## 独立云端补偿检查\n\n```json\n'+json.dumps(result,ensure_ascii=False,indent=2)+'\n```\n')


if __name__ == '__main__':
    try:
        main()
    except (RecoveryError, OSError, ValueError) as exc:
        print(json.dumps({'status':'failed','error':str(exc)},ensure_ascii=False))
        raise SystemExit(1)
