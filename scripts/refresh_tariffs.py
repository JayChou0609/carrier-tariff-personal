#!/usr/bin/env python3
"""Twice-daily collectors and conservative snapshot acceptance, without notifications."""
import argparse
import collections
import copy
import datetime as dt
import hashlib
import importlib
import json
import os
from pathlib import Path
import re
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'pipelines'))
from pipeline_common import diff_items, filter_test_items, slim_change

TARGETS = {
    'mobile': ['quanguo', 'jiangsu', 'shanghai'],
    'telecom': ['quanguo', 'jiangsu', 'shanghai', 'zhejiang'],
    'unicom': ['quanguo', 'jiangsu', 'shanghai', 'hebei', 'henan', 'sichuan', 'guangdong'],
    'gb': ['quanguo', 'jiangsu'],
}
FOLDERS = {'mobile': 'data', **{c: c + '/data' for c in ['telecom', 'unicom', 'gb']}}
CN = {'quanguo': '全国', 'jiangsu': '江苏', 'shanghai': '上海', 'zhejiang': '浙江',
      'hebei': '河北', 'henan': '河南', 'sichuan': '四川', 'guangdong': '广东'}
CARRIER_CN = {'mobile': '移动', 'telecom': '电信', 'unicom': '联通', 'gb': '广电'}


def now():
    return dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).isoformat(timespec='seconds')


def read(path, default=None):
    if not path.exists():
        return copy.deepcopy(default)
    return json.loads(path.read_text(encoding='utf-8'))


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    temp.replace(path)


def normalized(item):
    if 'fields' not in item:
        return item
    f = item['fields']
    return {'id': item.get('id', ''), 'title': item.get('name', ''),
            'firstLevel': f.get('归属', ''), 'secondLevel': f.get('资费类型', ''), 'detail': f}


def changes(previous, current):
    # IDs and categories disambiguate same-name businesses; retain all detail fields.
    return diff_items([normalized(x) for x in previous], [normalized(x) for x in current],
                      detail_limit=max(len(previous), len(current), 1))


def acceptable(old, new, error=''):
    if error:
        raise ValueError('分类请求不完整：' + str(error)[:250])
    if not isinstance(new, list) or not new:
        raise ValueError('未取得有效资费，保留旧快照')
    if any(not isinstance(x, dict) or not (x.get('title') or x.get('name')) for x in new):
        raise ValueError('资费数据结构不完整')
    if old and len(new) < len(old) * .7:
        raise ValueError('条数下降超过 30%，保留旧快照等待核验')


def sample_key(item):
    # Prefer official identity and preserve distinct variants with the same title.
    return str(item.get('id') or hashlib.sha256(json.dumps(
        [item.get('title'), item.get('firstLevel'), item.get('secondLevel'),
         (item.get('detail') or {}).get('reportNo')], ensure_ascii=False).encode()).hexdigest())


def merge_sample(old, observed, counters, today):
    """A missing Unicom sample is not a delisting. Require six misses AND expiry."""
    pool = {sample_key(x): x for x in old}
    seen = {sample_key(x) for x in observed}
    for item in observed:
        key = sample_key(item)
        if not item.get('detail'):
            # Keep the prior full record when a detail request fails; incomplete new
            # records wait for the next run rather than replacing known good fields.
            continue
        pool[key] = item
        counters.pop(key, None)
    for key in list(pool):
        if key in seen:
            continue
        counters[key] = counters.get(key, 0) + 1
        raw = str((pool[key].get('detail') or {}).get('offDate') or '')
        digits = re.sub(r'\D', '', raw)[:8]
        try:
            expired = dt.datetime.strptime(digits, '%Y%m%d').date() < today
        except ValueError:
            expired = False
        if expired and counters[key] >= 6:
            pool.pop(key)
            counters.pop(key, None)
    return list(pool.values())


def collect(carrier, scope, context):
    if carrier == 'mobile':
        sys.path.insert(0, str(ROOT / 'pipelines/mobile'))
        f = importlib.import_module('fetcher')
        from province_table import SECTION_INFO
        d = f.fetch_section(scope, SECTION_INFO.get(scope, ('731', ''))[0])
        return d['items'], d.get('error')
    if carrier == 'telecom':
        t = importlib.import_module('telecom_pipeline')
        if scope not in t.SCOPES:
            raise NotImplementedError('省级资费接口尚未接入；官方入口可查询，不用全国数据代替')
        return t.fetch_scope(scope, t.SCOPES[scope]['prov']), ''
    if carrier == 'gb':
        g = importlib.import_module('gb_pipeline')
        area = {key: code for key, code, _ in g.AREAS}[scope]
        items, failed = g.fetch_scope(scope, area)
        return items, '%d 个分类失败' % failed if failed else ''
    u = importlib.import_module('unicom_pipeline')
    if 'jobs' not in context:
        context['jobs'] = u.build_jobs()
    if scope not in context['jobs']:
        raise ValueError('省份编码接口未返回该地区')
    d = u.build_scope(scope, *context['jobs'][scope])
    return d['items'], '列表请求不完整' if d.get('partial') else ''


def fetch_carrier(carrier, root=ROOT, output=None, collector=collect):
    output = output or root / '_refresh' / ('refresh-' + carrier)
    started = now()
    context, report = {}, []
    state_path = Path(FOLDERS[carrier]) / '_scheduled_sampling.json'
    sampling = read(root / state_path, {}) if carrier == 'unicom' else {}
    for scope in TARGETS[carrier]:
        path = Path(FOLDERS[carrier]) / (scope + '.json')
        old = read(root / path, {'items': []})
        row = {'id': carrier + ':' + scope, 'carrier': carrier, 'region': scope,
               'name': CN[scope] + CARRIER_CN[carrier], 'path': path.as_posix(),
               'started': now(), 'previousTimestamp': old.get('timestamp', '')}
        try:
            items, error = collector(carrier, scope, context)
            items = filter_test_items(items)
            acceptable([] if carrier == 'unicom' else old['items'], items, error)
            observed = len(items)
            if carrier == 'unicom':
                missing_details = sum(not x.get('detail') for x in items)
                if missing_details == len(items):
                    raise ValueError('联通详情全部不可用，保留旧快照')
                row['detailsUnavailable'] = missing_details
                if missing_details:
                    row['message'] = '%d 条详情暂不可用，保留旧字段或等待补齐' % missing_details
                # Commit counters only after the entire scope has passed validation.
                counters = dict(sampling.get(scope, {}))
                items = merge_sample(old['items'], items, counters,
                                     dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).date())
                sampling[scope] = counters
            stamp = now()
            write(output / 'files' / path, {'scope': scope, 'timestamp': stamp, 'items': items})
            row.update(status='updated', count=len(items), observed=observed, timestamp=stamp,
                       note='接口全量覆盖未经核实；保留公示原文')
        except NotImplementedError as e:
            row.update(status='not_connected', count=len(old['items']), message=str(e))
        except Exception as e:
            row.update(status='retained' if old['items'] else 'failed',
                       count=len(old['items']), message=str(e)[:300])
        row['finished'] = now()
        report.append(row)
        print(row['id'], row['status'], row['count'], flush=True)
    if carrier == 'unicom':
        write(output / 'files' / state_path, sampling)
    write(output / 'status.json', {'carrier': carrier, 'started': started, 'finished': now(), 'sources': report})
    return report


def merge_reports(root, incoming):
    """Only allow known scoped files from workflow artifacts, never code or secrets."""
    reports = []
    for carrier, scopes in TARGETS.items():
        base = incoming / ('refresh-' + carrier)
        result = read(base / 'status.json', {})
        rows = {r['region']: r for r in result.get('sources', []) if r.get('carrier') == carrier}
        for scope in scopes:
            path = Path(FOLDERS[carrier]) / (scope + '.json')
            row = rows.get(scope, {'id': carrier + ':' + scope, 'carrier': carrier,
                                  'region': scope, 'name': CN[scope] + CARRIER_CN[carrier],
                                  'path': path.as_posix(), 'status': 'failed', 'message': '采集任务未产出报告'})
            # Fixed identity/path; artifact-provided path strings never control writes.
            row.update(id=carrier + ':' + scope, path=path.as_posix(), carrier=carrier, region=scope)
            if row['status'] == 'updated':
                data = read(base / 'files' / path)
                old = read(root / path, {'items': []})
                try:
                    acceptable(old['items'], (data or {}).get('items'))
                    write(root / path, data)
                except Exception as e:
                    row.update(status='retained' if old['items'] else 'failed', message=str(e))
            reports.append(row)
        if carrier == 'unicom':
            state = base / 'files' / FOLDERS[carrier] / '_scheduled_sampling.json'
            if state.exists():
                write(root / FOLDERS[carrier] / state.name, read(state))
    return reports


def update_recent_history(root, previous, reports, stamp):
    """Keep the existing four site timelines; full snapshots live in the archive branch."""
    entries = {c: {'ts': stamp} for c in TARGETS}
    for row in reports:
        if row['status'] != 'updated':
            continue
        old = previous.get(row['id'])
        if not old:
            continue  # initial baseline is not a mass addition
        new = read(root / row['path'])
        delta = changes(old['items'], new['items'])
        block = {k: len(delta[k + '_items']) for k in ['added', 'removed', 'modified']}
        if not any(block.values()):
            continue
        for k in ['added', 'removed', 'modified']:
            block[k + '_names'] = [x.get('title', '') for x in delta[k + '_items']]
            block[k + '_list'] = delta[k + '_items'][:12]
        block['modified_details'] = delta['modified_details']
        entries[row['carrier']][row['region']] = slim_change(block)
    for carrier, entry in entries.items():
        if len(entry) <= 1:
            continue
        path = root / FOLDERS[carrier] / 'history.json'
        history = read(path, [])
        history.append(entry)
        write(path, history[-60:])


def rebuild_indexes(root):
    # All 31 existing province files remain indexed even when only focus scopes run.
    from build_coverage import build
    from rebuild_latest import main as rebuild_mobile
    rebuild_mobile()
    for carrier in ['telecom', 'unicom', 'gb']:
        module = importlib.import_module(carrier + '_pipeline')
        scopes = list(module.SCOPES) if carrier == 'telecom' else []
        module.build_latest(scopes, str(root / FOLDERS[carrier]))
    write(root / 'data/coverage.json', build(root))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--carrier', choices=list(TARGETS), required=True)
    args = ap.parse_args()
    fetch_carrier(args.carrier)


if __name__ == '__main__':
    main()
