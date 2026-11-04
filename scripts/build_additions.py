#!/usr/bin/env python3
"""Publish first-added dates from complete archive snapshots, excluding baseline and edits."""
import argparse
from collections import defaultdict
import datetime as dt
import gzip
import hashlib
import json
from pathlib import Path
import re

from refresh_tariffs import ROOT, normalized, read, write
from pipeline_common import _item_id, stable_business_key, _aux_report_key

BEIJING = dt.timezone(dt.timedelta(hours=8))


def fingerprint(item):
    item = normalized(item)
    return json.dumps([_item_id(item), stable_business_key(item)], ensure_ascii=False, separators=(',', ':'))


def stamp_time(stamp):
    date = dt.datetime.fromisoformat(stamp.replace('Z', '+00:00'))
    if date.tzinfo is None:
        date = date.replace(tzinfo=BEIJING)
    return date.astimezone(BEIJING)


def beijing_date(stamp):
    return stamp_time(stamp).date().isoformat()


class SourceRegistry:
    """Retain aliases across ID/title changes, removals and later reappearances."""
    def __init__(self):
        self.records = []
        self.aliases = [defaultdict(set) for _ in range(3)]
        self.dates = defaultdict(set)

    def observe(self, items, candidates, day):
        values = [normalized(item) for item in items]
        functions = [_item_id, stable_business_key, _aux_report_key]
        assigned, used = {}, set()
        # Same matching priority as the tariff diff: unique ID, business identity,
        # then unique report number + categories. Shared report numbers never merge.
        for stage, key in enumerate(functions):
            buckets = defaultdict(list)
            for i, item in enumerate(values):
                if i not in assigned and key(item) and not (stage == 2 and fingerprint(item) in candidates):
                    buckets[key(item)].append(i)
            for token, indices in buckets.items():
                known = sorted(self.aliases[stage].get(token, set()) - used)
                if stage != 1 and (len(indices) != 1 or len(known) != 1):
                    continue
                for i, record in zip(indices, known):
                    assigned[i] = record
                    used.add(record)
        for i, item in enumerate(values):
            fp = fingerprint(item)
            if i not in assigned:
                assigned[i] = len(self.records)
                self.records.append(day if fp in candidates else None)
            record = assigned[i]
            for stage, key in enumerate(functions):
                if key(item):
                    self.aliases[stage][key(item)].add(record)
            self.dates[fp].add(self.records[record])

    def export(self):
        # An indistinguishable duplicate with conflicting dates stays unclassified.
        return {key: next(iter(dates)) for key, dates in self.dates.items()
                if len(dates) == 1 and None not in dates}


def build_additions(archive, root=ROOT):
    archive, root = Path(archive), Path(root)
    objects = {}
    def load_object(path):
        if not isinstance(path, str) or not re.fullmatch(r'objects/[0-9a-f]{2}/[0-9a-f]{64}\.json\.gz', path):
            raise ValueError('Invalid archive object path')
        if path not in objects:
            payload = gzip.decompress((archive / path).read_bytes())
            if hashlib.sha256(payload).hexdigest() != Path(path).name[:-8]:
                raise ValueError('Corrupt archive object: ' + path)
            objects[path] = json.loads(payload)
        return objects[path]

    runs = [read(path) for path in archive.glob('runs/*/*.json')]
    runs.sort(key=lambda run: (stamp_time(run['timestamp']), not run.get('baseline', False), run['id']))
    registries, starts = {}, {}
    for run in runs:
        day = beijing_date(run['timestamp'])
        for source in run['sources']:
            sid = source['id']
            if not re.fullmatch(r'(mobile|telecom|unicom|gb):[a-z]+', sid):
                raise ValueError('Invalid archive source ID')
            if not source.get('snapshot'):
                continue
            snapshot = load_object(source['snapshot'])
            if not isinstance(snapshot.get('items'), list):
                raise ValueError('Invalid archive snapshot')
            candidates = set()
            if source.get('status') == 'updated' and not run.get('baseline') and not source.get('baseline') and source.get('changes'):
                delta = load_object(source['changes'])
                candidates = {fingerprint(item) for item in delta.get('added_items', [])}
            registries.setdefault(sid, SourceRegistry()).observe(snapshot['items'], candidates, day)
            starts.setdefault(sid, day)
    sources = {sid: {'tracked_from': starts[sid], 'items': registry.export()}
               for sid, registry in sorted(registries.items())}
    result = {'version': 1, 'timezone': 'Asia/Shanghai',
              'updated': runs[-1]['timestamp'] if runs else '',
              'definition': '首次被本站完整归档确认为新增的日期；不是运营商上线日期。基线、修改和重复出现不计新增。',
              'sources': sources}
    write(root / 'data/additions.json', result)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--archive', type=Path, required=True)
    parser.add_argument('--root', type=Path, default=ROOT)
    args = parser.parse_args()
    result = build_additions(args.archive, args.root)
    print('First-added index:', len(result['sources']), 'sources,',
          sum(len(source['items']) for source in result['sources'].values()), 'recorded tariffs')
