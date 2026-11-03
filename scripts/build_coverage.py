#!/usr/bin/env python3
"""Build a truthful coverage manifest from stored snapshots; never infer completeness."""
import argparse
import datetime
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'pipelines' / 'mobile'))
from province_table import PROVINCES

CARRIERS = {'mobile': ('移动', 'data', 'https://h.app.coc.10086.cn/cmcc-app/pc-pages/tariffZonePers.html'),
            'telecom': ('电信', 'telecom/data', 'https://www.189.cn/jtzfzq/'),
            'unicom': ('联通', 'unicom/data', 'https://img.client.10010.com/zifeizhuanquwt/index.html'),
            'gb': ('广电', 'gb/data', 'https://m.10099.com.cn/')}
OFFICIAL = {'telecom:jiangsu': 'https://wapjs.189.cn/mall/pages/feePart/index.html',
            'telecom:shanghai': 'https://www.189.cn/jtzfzq/sh',
            'telecom:zhejiang': 'https://www.189.cn/jtzfzq/zj'}


def build(root=ROOT):
    sources = []
    for carrier, (name, folder, official) in CARRIERS.items():
        for region, cn in [('quanguo', '全国')] + [(s, n) for s, _, n in PROVINCES]:
            sid = carrier + ':' + region
            path = Path(folder) / (region + '.json')
            available, total, timestamp = False, None, ''
            if (root / path).exists():
                data = json.loads((root / path).read_text(encoding='utf-8'))
                if not isinstance(data.get('items'), list):
                    raise ValueError('Invalid snapshot: ' + str(path))
                available, total, timestamp = True, len(data['items']), data.get('timestamp', '')
            sources.append({'id': sid, 'carrier': carrier, 'region': region, 'name': cn + name,
                            'available': available, 'total': total, 'timestamp': timestamp,
                            'path': path.as_posix() if available else None,
                            'official': OFFICIAL.get(sid, official),
                            'completeness': 'not_verified',
                            'status': 'snapshot' if available else 'not_connected'})
    for c in CARRIERS:
        if not any(s['id'] == c + ':quanguo' and s['available'] and s['total'] for s in sources):
            raise ValueError('Required national snapshot missing or empty: ' + c)
    return {'version': 1, 'generated': datetime.datetime.now(datetime.timezone.utc).isoformat(),
            'note': '快照可用不等于已核实全量。省级未接入的数据不得用全国资费代替。', 'sources': sources}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, default=ROOT)
    args = parser.parse_args()
    data = build(args.root)
    out = args.root / 'data' / 'coverage.json'
    out.write_text(json.dumps(data, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    print('Coverage:', sum(s['available'] for s in data['sources']), '/', len(data['sources']))


if __name__ == '__main__':
    main()
