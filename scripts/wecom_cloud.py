#!/usr/bin/env python3
"""GitHub Actions entry point. Webhook exists only in the step environment."""
import argparse
import base64
import datetime as dt
import json
import os
from pathlib import Path
import re
import tempfile
import urllib.error
import urllib.parse
import urllib.request

import wecom_tariffs as core

REPOSITORY = 'JayChou0609/carrier-tariff-personal'
BRANCH = 'wecom-notify-state'
STATE_FILE = 'state.json'
ROOT = Path(__file__).resolve().parents[1]


class StateError(RuntimeError):
    pass


def assert_no_credentials(value, forbidden):
    text = json.dumps(value,ensure_ascii=False,sort_keys=True)
    if any(token and token in text for token in forbidden):
        raise StateError('Checkpoint contains a credential; refusing to publish')
    return text


class GitHubState:
    def __init__(self, token, repo=REPOSITORY, branch=BRANCH, forbidden=()):
        if repo != REPOSITORY or branch != BRANCH or not token:
            raise StateError('Repository, checkpoint branch or GITHUB_TOKEN is invalid')
        self.token,self.repo,self.branch = token,repo,branch
        self.forbidden = tuple(forbidden)+(token,)
        self.sha = None
        self.data = {'version':1,'delivery':{},'outbox':{},'blocked':None,'verified_scope':''}

    def api(self, method, path, body=None, missing=False):
        url = 'https://api.github.com/repos/'+self.repo+'/'+path
        payload = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(url,data=payload,method=method,headers={
            'Authorization':'Bearer '+self.token,'Accept':'application/vnd.github+json',
            'X-GitHub-Api-Version':'2022-11-28','Content-Type':'application/json',
            'User-Agent':'TariffWeComActions/1.0'})
        try:
            with urllib.request.urlopen(request,timeout=35) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            if missing and exc.code == 404:
                return None
            raise StateError('GitHub checkpoint API failed: HTTP '+str(exc.code)) from None
        except Exception as exc:
            raise StateError('GitHub checkpoint connection failed: '+type(exc).__name__) from None

    def load(self):
        branch = self.api('GET','git/ref/heads/'+self.branch,missing=True)
        if branch is None:
            base = self.api('GET','git/ref/heads/main')
            self.api('POST','git/refs',{'ref':'refs/heads/'+self.branch,'sha':base['object']['sha']})
        value = self.api('GET','contents/'+STATE_FILE+'?ref='+self.branch,missing=True)
        if value is not None:
            self.sha = value['sha']
            if value.get('encoding') != 'base64' or not value.get('content'):
                value = self.api('GET','git/blobs/'+self.sha)
            if value.get('encoding') != 'base64':
                raise StateError('Unsupported checkpoint encoding')
            self.data = json.loads(base64.b64decode(value['content']))
        if (self.data.get('version') != 1 or not isinstance(self.data.get('delivery'),dict)
                or not isinstance(self.data.get('outbox'),dict)):
            raise StateError('Invalid checkpoint; refusing to reset delivery history')
        assert_no_credentials(self.data,self.forbidden)
        return self.data

    def restore(self, directory):
        directory = Path(directory)
        core.write_json(directory/'delivery.json',self.data['delivery'])
        for name,value in self.data['outbox'].items():
            if not re.fullmatch(r'[0-9a-f]{64}\.json',name):
                raise StateError('Invalid outbox checkpoint name')
            core.write_json(directory/'outbox'/name,value)
        if self.data.get('blocked'):
            core.write_json(directory/'blocked.json',self.data['blocked'])

    def put(self, data, backup=None):
        text = assert_no_credentials(data,self.forbidden)
        if backup is not None:
            core.write_json(backup,data)
        body = {'branch':self.branch,'message':'state: WeCom tariff delivery checkpoint',
                'content':base64.b64encode(text.encode()).decode()}
        if self.sha:
            body['sha'] = self.sha
        value = self.api('PUT','contents/'+STATE_FILE,body)
        self.sha = value['content']['sha']
        self.data = data

    def begin(self, run):
        if self.data.get('in_progress'):
            raise StateError('An earlier send has an unfinished checkpoint. Restore its backup before retrying.')
        value = dict(self.data)
        value['in_progress'] = {'run':run,'at':core.now().isoformat()}
        self.put(value)

    def checkpoint(self, directory, backup, release=False):
        directory = Path(directory)
        value = dict(self.data)
        if release:
            value.pop('in_progress',None)
        value['delivery'] = core.read_json(directory/'delivery.json',{})
        value['outbox'] = {p.name:core.read_json(p) for p in (directory/'outbox').glob('*.json')}
        value['blocked'] = core.read_json(directory/'blocked.json')
        value['updated_at'] = core.now().isoformat()
        # Forty-five active days keep the current file bounded; Git preserves prior versions.
        cutoff = (core.now().date()-dt.timedelta(days=45)).isoformat()
        if any(len(k.split('|')) != 3 for k in value['delivery']):
            raise StateError('Invalid delivery checkpoint key')
        value['delivery'] = {k:v for k,v in value['delivery'].items() if k.split('|')[1] >= cutoff}
        if release:
            value['outbox'] = {k:v for k,v in value['outbox'].items()
                               if not (v.get('summary_sent') and
                                       (v.get('file_sent') or v.get('file_required') is False) and
                                       all(p.get('image') and p.get('text') for p in v.get('cards',{}).values()))}
        self.put(value,backup)


    def finish(self, directory, backup):
        self.checkpoint(directory, backup, release=True)

    def recover(self):
        """Only resume after the GitHub run holding the durable lease has ended."""
        lease = self.data.get('in_progress') or {}
        if lease:
            match = re.fullmatch(r'(\d+)-\d+', str(lease.get('run', '')))
            if not match:
                raise StateError('Invalid notification lease; manual review is required')
            run = self.api('GET', 'actions/runs/'+match.group(1))
            if (run.get('status') != 'completed' or run.get('head_branch') != 'main'
                    or run.get('path') != '.github/workflows/wecom-notify.yml'):
                raise StateError('The previous notification run is still active or cannot be verified')
        value = dict(self.data)
        value.pop('in_progress', None)
        value.pop('blocked', None)
        value['recovered_at'] = core.now().isoformat()
        self.put(value)

    def mark_success(self, report):
        health = {'version':1, 'status':'complete', 'collection_run':report['collection_run'],
                  'target_slot':report.get('target_slot',''), 'day':report['day'],
                  'buckets':sorted(core.BUCKETS), 'cards':True,
                  'completed_at':core.now().isoformat()}
        current = self.api('GET','contents/health.json?ref='+self.branch,missing=True)
        body = {'branch':self.branch, 'message':'state: completed tariff image and text delivery',
                'content':base64.b64encode(assert_no_credentials(health,self.forbidden).encode()).decode()}
        if current:
            body['sha'] = current['sha']
        self.api('PUT','contents/health.json',body)


def report_from_checkout(root=ROOT):
    report = core.collect(snapshot_root=root)
    status = core.read_json(Path(root)/'data/refresh-status.json',{})
    collection = {x['id']:x for x in ((status.get('latest') or {}).get('sources') or [])}
    for source in report['sources']:
        if source['status'] == 'local_preview':
            source['status'] = 'repository_snapshot'
        previous = collection.get(source['id'],{})
        if previous.get('status') in ['retained','failed','not_connected']:
            source['status'] = 'cached' if source['status'] != 'failed' else 'failed'
            source['collection_status'] = previous['status']
    return report


def require_complete_collection(report, root=ROOT, expected_run=''):
    latest = (core.read_json(Path(root)/'data/refresh-status.json',{}) or {}).get('latest') or {}
    run_id = str(latest.get('id') or '')
    if (latest.get('baseline') or not re.fullmatch(r'\d+-\d+',run_id)
            or (expected_run and not run_id.startswith(str(expected_run)+'-'))
            or core.date_day(latest.get('timestamp')) != report['day']):
        raise StateError('未找到与本次触发匹配的当日采集归档；不发送旧快照摘要')
    rows = latest.get('sources') or []
    collection = {x['id']:x for x in rows}
    expected = {c+':'+r for c,regions in core.SCOPES.items() for r in regions}
    incomplete = sorted(sid for sid in expected if collection.get(sid,{}).get('status') != 'updated')
    if len(rows) != len(expected) or set(collection) != expected or incomplete:
        raise StateError('本轮采集不完整，停止正式推送：'+', '.join(incomplete or ['来源清单不匹配']))
    for source in report['sources']:
        row = collection[source['id']]
        stamp = row.get('snapshotTimestamp') or row.get('timestamp')
        if source['status'] != 'repository_snapshot' or not stamp or stamp != source.get('snapshot'):
            raise StateError('资费文件与本轮归档不一致，停止正式推送：'+source['id'])
    report['collection_run'] = run_id
    report['collection_time'] = latest['timestamp']
    target = str(latest.get('targetSlot') or '')
    if target:
        try:
            slot = dt.datetime.fromisoformat(target).astimezone(core.TZ)
            if slot.hour not in [0,12,18] or slot.minute or slot.second:
                raise ValueError('Invalid collection slot')
        except ValueError:
            raise StateError('归档的目标时段无效') from None
        report['target_slot'] = target
        report['collection_slot'] = slot.hour
    return report


def upstream_archived(root=ROOT,expected_run=''):
    latest=(core.read_json(Path(root)/'data/refresh-status.json',{}) or {}).get('latest') or {}
    return bool(not latest.get('baseline') and str(latest.get('id','')).startswith(str(expected_run)+'-'))


def cloud_test(config, run_url):
    client = core.Client(config)
    client.send('text',{'content':'【运营商资费提醒】GitHub Actions 云端连接验证\n发送端已迁至GitHub；三类提醒：今日上线、明日下线、今日下线。\n'+run_url})
    content = '\ufeff用途,结果\r\nGitHub Actions文件推送验证,此文件不是正式资费数据\r\n'.encode('utf-8')
    media = client.upload_csv('github-actions-connection-test.csv',content)
    client.send('file',{'media_id':media})
    return 2


def write_summary(result, report=None):
    path = os.environ.get('GITHUB_STEP_SUMMARY')
    if not path:
        return
    lines = ['## 企业微信资费推送','', '状态：'+str(result.get('status','')), '']
    if result.get('error'):
        lines.extend(['说明：'+str(result['error']),''])
    if report:
        lines.extend(['| 类型 | 当前条数 |','|---|---:|'])
        lines.extend('| '+core.BUCKETS[key]+' | '+str(len(rows))+' |' for key,rows in report['buckets'].items())
        lines.extend(['','统计日期：'+report['day']+'（北京时间）',
                      '正式推送要求本轮全部关注范围更新并与归档一致；不完整时不推送。'])
        if report.get('collection_run'):
            lines.append('本轮采集批次：'+report['collection_run'])
    with open(path,'a',encoding='utf-8') as stream:
        stream.write('\n'.join(lines)+'\n')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--action',choices=['preview','verify','send','recover','gate'],default='send')
    args = parser.parse_args()
    report = None
    try:
        if os.environ.get('GITHUB_REPOSITORY') != REPOSITORY:
            raise StateError('This notification workflow is limited to its configured repository')
        expected_run=os.environ.get('COLLECTION_RUN_ID','')
        if expected_run and not upstream_archived(expected_run=expected_run):
            if os.environ.get('GITHUB_OUTPUT'):
                with open(os.environ['GITHUB_OUTPUT'],'a') as f:f.write('notify=false\n')
            result={'status':'no_collection_for_trigger','sent':0,
                    'message':'补偿检查未产生本轮归档，不推送既有快照'}
            print(json.dumps(result,ensure_ascii=False));write_summary(result)
            return 0
        if args.action=='gate':
            if os.environ.get('GITHUB_OUTPUT'):
                with open(os.environ['GITHUB_OUTPUT'],'a') as f:f.write('notify=true\n')
            return 0
        report = report_from_checkout()
        if args.action == 'preview':
            result = {'status':'preview','sent':0,'counts':{k:len(v) for k,v in report['buckets'].items()}}
            print(json.dumps(result,ensure_ascii=False));write_summary(result,report)
            return 0
        require_complete_collection(report,expected_run=expected_run)
        webhook = os.environ.get('WECOM_WEBHOOK','').strip()
        if not webhook:
            result = {'status':'not_configured','sent':0}
            print(json.dumps(result));write_summary(result,report)
            return 1
        config = core.validate_config({'wecom_webhook':webhook})
        key = urllib.parse.parse_qs(urllib.parse.urlsplit(webhook).query)['key'][0]
        if os.environ.get('GITHUB_ACTIONS') == 'true':
            print('::add-mask::'+webhook,flush=True)
            print('::add-mask::'+key,flush=True)
        store = GitHubState(os.environ.get('GITHUB_TOKEN',''),forbidden=(webhook,key))
        store.load()
        scope = core.config_hash(config)
        if args.action != 'verify' and store.data.get('verified_scope') != scope:
            result = {'status':'not_verified','sent':0,'message':'Run workflow with action=verify first'}
            print(json.dumps(result));write_summary(result,report)
            return 1
        if args.action == 'recover':
            store.recover()
        run = os.environ.get('GITHUB_RUN_ID','manual')+'-'+os.environ.get('GITHUB_RUN_ATTEMPT','1')
        backup = Path(os.environ.get('RUNNER_TEMP',tempfile.gettempdir()))/'wecom-checkpoint-backup.json'
        with tempfile.TemporaryDirectory(prefix='wecom-state-',dir=os.environ.get('RUNNER_TEMP')) as td:
            directory = Path(td)
            store.restore(directory)
            store.begin(run)  # Durable lease before the first external message.
            try:
                test_count = 0
                if args.action == 'verify':
                    url = 'https://github.com/'+REPOSITORY+'/actions/runs/'+os.environ.get('GITHUB_RUN_ID','')
                    test_count = cloud_test(config,url)
                    store.data['verified_scope'] = scope
                    store.data['verified_at'] = core.now().isoformat()
                    blocked = directory/'blocked.json'
                    if blocked.exists():blocked.unlink()
                core.write_json(directory/'ready.json',{'scope':scope})
                result = core.send_report(report,config,state_dir=directory,
                    checkpoint=lambda: store.checkpoint(directory,backup))
                result['cloud_test_messages'] = test_count
            finally:
                store.finish(directory,backup)
        if result.get('status') in ['sent','unchanged']:
            store.mark_success(report)
        print(json.dumps(result,ensure_ascii=False));write_summary(result,report)
        return 0
    except (ValueError,RuntimeError) as exc:
        result = {'status':'failed','error':str(exc)}
        print(json.dumps(result,ensure_ascii=False));write_summary(result,report)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
