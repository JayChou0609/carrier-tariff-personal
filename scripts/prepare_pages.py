#!/usr/bin/env python3
"""Prepare an allowlisted static Pages artifact; pipeline state and source stay in Git."""
import argparse
from pathlib import Path
import shutil
from build_coverage import build, ROOT
import json


def prepare(root, out, repo=''):
    if out.exists():
        raise ValueError('Output directory must be new: ' + str(out))
    coverage = build(root)
    out.mkdir(parents=True)
    for name in ['index.html', 'app.js', 'style.css', 'common-extras.js', 'logo.png',
                 'tariff-fetch-source.zip', 'manifest.json', 'sw.js', 'push-center.html', '.nojekyll', 'LICENSE']:
        shutil.copy2(root / name, out / name)
    for folder in ['icons', 'custom', 'history', 'telecom', 'unicom', 'gb']:
        if folder in ['icons', 'custom', 'history']:
            shutil.copytree(root / folder, out / folder,
                            ignore=shutil.ignore_patterns('__pycache__', 'node_modules'))
        else:
            (out / folder).mkdir()
            for src in (root / folder).iterdir():
                if src.is_file() and src.suffix in ['.html', '.js', '.css', '.png', '.webp', '.svg', '.ico']:
                    shutil.copy2(src, out / folder / src.name)
    for folder in ['data', 'telecom/data', 'unicom/data', 'gb/data']:
        target = out / folder
        target.mkdir(exist_ok=True)
        wanted = {'latest.json', 'history.json'}
        wanted.update(Path(s['path']).name for s in coverage['sources']
                      if s['available'] and str(Path(s['path']).parent) == folder)
        if folder == 'data':
            wanted.update(['announce.json', 'refresh-status.json'])
        for name in wanted:
            src = root / folder / name
            if src.exists():
                shutil.copy2(src, target / name)
    (out / 'data/coverage.json').write_text(json.dumps(coverage, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    if repo:
        owner, project = repo.split('/')
        base = 'https://' + owner + '.github.io/' + ('' if project.lower() == owner.lower()+'.github.io' else project+'/')
        for file in out.rglob('*.html'):
            text = file.read_text(encoding='utf-8')
            # Canonical metadata must identify the new site rather than the upstream author.
            text = text.replace('https://amxysw.github.io/carrier-tariff-site/', base)
            file.write_text(text, encoding='utf-8')
    return coverage


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', type=Path, default=ROOT / '_pages')
    ap.add_argument('--repo', default='')
    args = ap.parse_args()
    prepare(ROOT, args.out, args.repo)
    print('Pages artifact:', args.out)
