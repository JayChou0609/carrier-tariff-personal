#!/usr/bin/env python3
"""Permanent, content-addressed tariff history in the separate tariff-history branch."""
import argparse
import copy
import datetime as dt
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import sys

from refresh_tariffs import (ROOT, TARGETS, FOLDERS, CN, CARRIER_CN, now, read, write,
                             changes, merge_reports, update_recent_history, rebuild_indexes)


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')


def put_object(archive, value):
    payload = canonical(value)
    digest = hashlib.sha256(payload).hexdigest()
    path = Path('objects') / digest[:2] / (digest + '.json.gz')
    target = archive / path
    if target.exists():
        if gzip.decompress(target.read_bytes()) != payload:
            raise ValueError('Archive object hash collision or corruption')
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(gzip.compress(payload, mtime=0))
    return path.as_posix()


def snapshot_object(data):
    # Preserve every business field, but move capture timestamps into the run manifest
    # so unchanged tariff content shares one object across arbitrary future runs.
    value = {k: v for k, v in data.items() if k not in ['timestamp', 'error']}
    value['items'] = sorted(value.get('items', []), key=lambda x: canonical(x))
    return value


def capture(archive, root, reports, stamp, run_id, previous=None, baseline=False):
    if not re.fullmatch(r'[A-Za-z0-9_-]+', run_id):
        raise ValueError('Invalid run ID')
    previous = previous or {}
    year = stamp[:4]
    run_path = archive / 'runs' / year / (run_id + '.json')
    if run_path.exists():
        # A rerun is a separate run_attempt, never rewrite the earlier audit record.
        raise ValueError('Archive run already exists: ' + run_id)
    rows = []
    for original in reports:
        row = copy.deepcopy(original)
        data = read(root / row['path'])
        if data and isinstance(data.get('items'), list):
            row['snapshot'] = put_object(archive, snapshot_object(data))
            row['snapshotTimestamp'] = data.get('timestamp', '')
            row['count'] = len(data['items'])
        else:
            row['snapshot'] = None
            row['count'] = None  # missing is never a fake zero-tariff snapshot
        old = previous.get(row['id'])
        row.update(added=0, modified=0, removed=0)
        if old and data and row['status'] == 'updated' and not baseline:
            delta = changes(old['items'], data['items'])
            for key in ['added', 'removed', 'modified']:
                row[key] = len(delta[key + '_items'])
            if any(row[k] for k in ['added', 'modified', 'removed']):
                row['changes'] = put_object(archive, delta)
                row['previousSnapshot'] = put_object(archive, snapshot_object(old))
        row['baseline'] = baseline or old is None
        rows.append(row)
    record = {'version': 1, 'id': run_id, 'timestamp': stamp, 'timezone': 'Asia/Shanghai',
              'baseline': baseline, 'sources': rows}
    write(run_path, record)
    return record


def seed_legacy(archive, root):
    """Once only: retain pre-existing full timelines before any recent-view trimming."""
    for carrier, folder in FOLDERS.items():
        dest = archive / 'legacy' / (carrier + '-history.json.gz')
        if dest.exists():
            continue
        history = root / folder / 'history.json'
        if history.exists():
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(gzip.compress(history.read_bytes(), mtime=0))


def publish_indexes(archive, root, repository):
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repository):
        raise ValueError('Invalid GitHub repository')
    years = []
    runs_dir = archive / 'runs'
    for folder in sorted(runs_dir.iterdir(), reverse=True) if runs_dir.exists() else []:
        if not folder.is_dir() or not re.fullmatch(r'\d{4}', folder.name):
            continue
        runs = [read(f) for f in folder.glob('*.json')]
        runs.sort(key=lambda r: (r['timestamp'], not r.get('baseline', False), r['id']), reverse=True)
        write(root / 'history/data' / (folder.name + '.json'), {'year': folder.name, 'runs': runs})
        years.append({'year': folder.name, 'runs': len(runs)})
    base = 'https://raw.githubusercontent.com/' + repository + '/tariff-history/'
    write(root / 'history/data/index.json', {
        'version': 1, 'updated': now(), 'timezone': 'Asia/Shanghai',
        'schedule': ['00:00', '12:00'], 'retention': '不自动清理，完整历史存储在 tariff-history 分支',
        'archiveBase': base, 'repository': 'https://github.com/' + repository + '/tree/tariff-history',
        'years': years, 'legacy': [{'carrier': c, 'name': CARRIER_CN[c],
                                  'path': 'legacy/' + c + '-history.json.gz'}
                                 for c in FOLDERS if (archive / 'legacy' / (c + '-history.json.gz')).exists()]})
    write(root / 'data/refresh-status.json', {
        'updated': now(), 'schedule': ['00:00', '12:00'], 'timezone': 'Asia/Shanghai',
        'history': '../history/', 'latest': read(root / 'history/data' / (years[0]['year'] + '.json'))['runs'][0]
        if years else None})


def initial_reports(root):
    rows = []
    for carrier, scopes in TARGETS.items():
        for scope in scopes:
            path = Path(FOLDERS[carrier]) / (scope + '.json')
            data = read(root / path)
            rows.append({'id': carrier + ':' + scope, 'name': CN[scope] + CARRIER_CN[carrier],
                         'carrier': carrier, 'region': scope, 'path': path.as_posix(),
                         'status': 'baseline' if data else 'not_connected',
                         'message': '已保存现有快照基线，本次未重新采集' if data else '省级接口尚未接入'})
    return rows


def run(root, archive, incoming, repository, run_id, archive_only=False):
    archive.mkdir(parents=True, exist_ok=True)
    seed_legacy(archive, root)
    previous = {c + ':' + s: read(root / FOLDERS[c] / (s + '.json'))
                for c, scopes in TARGETS.items() for s in scopes}
    # Preserve the entire original state before the first scheduled replacement.
    if not (archive / 'runs').exists() and not archive_only:
        capture(archive, root, initial_reports(root), now(), 'initial-' + run_id, baseline=True)
    reports = initial_reports(root) if archive_only else merge_reports(root, incoming)
    stamp = now()
    capture(archive, root, reports, stamp, run_id, previous, baseline=archive_only)
    if not archive_only:
        update_recent_history(root, previous, reports, stamp)
        rebuild_indexes(root)
    publish_indexes(archive, root, repository)
    return reports


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--archive', type=Path, required=True)
    ap.add_argument('--incoming', type=Path, default=ROOT / '_refresh')
    ap.add_argument('--repository', required=True)
    ap.add_argument('--run-id', required=True)
    ap.add_argument('--archive-only', action='store_true')
    args = ap.parse_args()
    rows = run(ROOT, args.archive, args.incoming, args.repository, args.run_id, args.archive_only)
    summary = {'updated': sum(x['status'] == 'updated' for x in rows),
               'not_connected': sum(x['status'] == 'not_connected' for x in rows),
               'retained_or_failed': sum(x['status'] in ['retained', 'failed'] for x in rows)}
    print(json.dumps(summary, ensure_ascii=False))
    # Do not call a wholly unsuccessful collection a success. Artifacts/history are still saved
    # and the workflow publishes the latest reliable data before this result is reported.
    if not args.archive_only and not summary['updated']:
        sys.exit(2)
