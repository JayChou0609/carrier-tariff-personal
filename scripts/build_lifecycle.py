#!/usr/bin/env python3
"""Rebuild confirmed reactivations from immutable official tariff snapshots."""
from collections import defaultdict
from functools import lru_cache
import datetime as dt
import gzip
import hashlib
import json
from pathlib import Path
import re

from build_additions import stamp_time
from refresh_tariffs import ROOT, normalized, read, write
from pipeline_common import _item_id, stable_business_key


@lru_cache(maxsize=8192)
def day(value):
    text = str(value or '').strip()
    if re.search(r'T.*(?:Z|[+-]\d{2}:?\d{2})$', text, re.I):
        try:
            return stamp_time(text).date().isoformat()
        except ValueError:
            return ''
    match = re.match(r'^(\d{4})[-/年.](\d{1,2})[-/月.](\d{1,2})(?:日|\b)', text) or re.fullmatch(r'(\d{4})(\d{2})(\d{2})', text)
    if not match:
        return ''
    try:
        return dt.date(*map(int, match.groups())).isoformat()
    except ValueError:
        return ''


def dates(raw):
    f = raw.get('fields') or raw.get('detail') or {}
    def value(keys):
        return next((day(data.get(key)) for key in keys for data in [f, raw] if day(data.get(key))), '')
    return value(['上线日期','onDate','onlineDay','startDate']), value(['下线日期','offDate','offineDay','offlineDay','endDate'])


def state(raw, today):
    f = raw.get('fields') or raw.get('detail') or {}
    types = [raw.get('firstLevel'), f.get('codeType'), f.get('资费类型')]
    explicit = str(f.get('销售状态') or f.get('停售状态') or f.get('state') or raw.get('state') or '').strip()
    on, off = dates(raw)
    if any(re.fullmatch(r'停售(?:套餐|业务|资费)?', str(x or '').strip()) for x in types) or re.fullmatch(r'(?:已)?停售|停止销售|(?:已)?下架', explicit):
        return 'stopped'
    if off and off < today:
        return 'stopped'
    if on and on > today:
        return 'upcoming'
    if explicit in ['在售','销售中','正常销售','已上架'] or off or (on and str(f.get('下线日期') or f.get('offDate') or '').strip() in ['长期','长期有效','永久','无期限']):
        return 'onsale'
    return 'unknown'


def entry_key(raw):
    x = normalized(raw)
    return json.dumps([str(x.get('id') or ''), str(x.get('title') or x.get('name') or ''), str(x.get('firstLevel') or ''), str(x.get('secondLevel') or '')], ensure_ascii=False, separators=(',', ':'))


class Registry:
    def __init__(self):
        self.records = []
        self.aliases = [defaultdict(set), defaultdict(set)]
        self.current = {}

    def observe(self, items, stamp, emit=True):
        today = stamp_time(stamp).date().isoformat()
        values = [normalized(x) for x in items]
        assigned, used = {}, set()
        functions = [_item_id, stable_business_key]
        for stage, key in enumerate(functions):
            buckets = defaultdict(list)
            for i, x in enumerate(values):
                if i not in assigned and key(x):
                    buckets[key(x)].append(i)
            for token, indices in buckets.items():
                known = self.aliases[stage].get(token, set()) - used
                if len(indices) == 1 and len(known) == 1:
                    i, record = indices[0], next(iter(known))
                    assigned[i] = record
                    used.add(record)
        current = defaultdict(list)
        for i, raw in enumerate(items):
            if i not in assigned:
                assigned[i] = len(self.records)
                self.records.append({'raw': None, 'stopped': '', 'events': []})
            record = self.records[assigned[i]]
            old, stopped = record['raw'], record['stopped']
            # Disappearance is never a stop signal. An elapsed official end date is.
            if old and state(old, today) == 'stopped':
                old_off = dates(old)[1]
                stopped = stopped or (old_off if old_off and old_off < today else record['day'])
            status = state(raw, today)
            on, off = dates(raw)
            if stopped and status == 'onsale' and emit:
                official = on if on and stopped < on <= today else ''
                record['events'].append({'date': official or today, 'confirmedAt': stamp,
                    'basis': '官方重新上线日期' if official else '历史停售后恢复在售的确认日期（官方未更新上线日期）',
                    'previousStopDate': stopped, 'onDate': on, 'offDate': off})
                stopped = ''
            elif status == 'onsale':
                stopped = ''
            if status == 'stopped':
                stopped = stopped or (off if off and off < today else today)
            record.update(raw=raw, day=today, stopped=stopped)
            for stage, key in enumerate(functions):
                if key(values[i]):
                    self.aliases[stage][key(values[i])].add(assigned[i])
            current[entry_key(raw)].append(record)
        # An ambiguous current duplicate is not assigned a reactivation event.
        self.current = {key: rows[0]['events'] for key, rows in current.items() if len(rows) == 1 and rows[0]['events']}


def build_lifecycle(archive, root=ROOT):
    archive, root = Path(archive), Path(root)
    objects, registries, tracked = {}, {}, {}
    def load(path):
        if not isinstance(path, str) or not re.fullmatch(r'objects/[0-9a-f]{2}/[0-9a-f]{64}\.json\.gz', path):
            raise ValueError('Invalid archive object path')
        if path not in objects:
            payload = gzip.decompress((archive/path).read_bytes())
            if hashlib.sha256(payload).hexdigest() != Path(path).name[:-8]:
                raise ValueError('Corrupt archive object: '+path)
            objects[path] = json.loads(payload)
        return objects[path]
    runs = [read(p) for p in archive.glob('runs/*/*.json')]
    runs.sort(key=lambda r: (stamp_time(r['timestamp']), not r.get('baseline', False), r['id']))
    for run in runs:
        for s in run['sources']:
            sid = s['id']
            if not re.fullmatch(r'(mobile|telecom|unicom|gb):[a-z]+', sid):
                raise ValueError('Invalid archive source ID')
            baseline = run.get('baseline') or s.get('baseline') or s.get('status') == 'baseline'
            if not s.get('snapshot') or (s.get('status') != 'updated' and sid in registries):
                continue
            # Retained snapshots seed state only at their actual capture time.
            stamp = s.get('snapshotTimestamp') or run['timestamp']
            snapshot = load(s['snapshot'])
            if not isinstance(snapshot.get('items'), list):
                raise ValueError('Invalid archive snapshot')
            registries.setdefault(sid, Registry()).observe(snapshot['items'], stamp, emit=not baseline and s.get('status') == 'updated')
            tracked.setdefault(sid, stamp)
    result = {'version': 1, 'timezone': 'Asia/Shanghai', 'updated': runs[-1]['timestamp'] if runs else '',
        'definition': '只有历史官方停售或下线日期已过，之后恢复在售才算重新上线；接口缺项、首次上线和普通修改均不算。优先用新的官方上线日期，否则单列监测确认日期。',
        'sources': {sid: {'trackedFrom': tracked[sid], 'items': registry.current} for sid, registry in sorted(registries.items())}}
    write(root/'data/lifecycle.json', result)
    return result


if __name__ == '__main__':
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument('--archive', type=Path, required=True)
    p.add_argument('--root', type=Path, default=ROOT)
    args = p.parse_args()
    data = build_lifecycle(args.archive, args.root)
    print('Lifecycle index:', len(data['sources']), 'sources')
