import json
from pathlib import Path
import sys
import tempfile
import unittest
from html.parser import HTMLParser
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from build_coverage import build
from prepare_pages import prepare


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []
        self.ids = []
    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if 'id' in a:
            self.ids.append(a['id'])
        for k in ['src', 'href']:
            if a.get(k):
                self.links.append(a[k])


class PersonalDataTest(unittest.TestCase):
    def test_coverage_matches_snapshots(self):
        manifest = build()
        self.assertEqual(len(manifest['sources']), 128)
        self.assertEqual(len({s['id'] for s in manifest['sources']}), 128)
        for s in manifest['sources']:
            if s['available']:
                data = json.loads((ROOT / s['path']).read_text())
                self.assertEqual(s['total'], len(data['items']))
                self.assertEqual(s['timestamp'], data.get('timestamp', ''))
            else:
                self.assertIsNone(s['path'])
                self.assertIsNone(s['total'])
            self.assertEqual(s['completeness'], 'not_verified')

    def test_national_data_required(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaisesRegex(ValueError, 'national snapshot'):
                build(Path(td))

    def test_pages_artifact_links_and_privacy(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / 'pages'
            prepare(ROOT, out, 'example-user/tariffs')
            for file in out.rglob('*.html'):
                parser = Links()
                parser.feed(file.read_text())
                self.assertEqual(len(parser.ids), len(set(parser.ids)), str(file))
                for link in parser.links:
                    url = urlsplit(link)
                    if url.scheme or url.netloc or not url.path or url.path.startswith('/'):
                        continue
                    target = file.parent / unquote(url.path)
                    self.assertTrue(target.exists(), '%s -> %s' % (file, link))
            for name in ['.git', '.env', 'pipelines', 'scripts', '.github', 'unicom/data/_pool.json', 'data/_degrade.json']:
                self.assertFalse((out / name).exists(), name)
            self.assertTrue((out / 'data/announce.json').exists())
            self.assertTrue((out / 'unicom/data/announce.json').exists())
            for carrier in ['', 'telecom/', 'unicom/', 'gb/']:
                self.assertTrue((out / (carrier + 'data/quanguo.json')).exists())
            self.assertIn('https://example-user.github.io/tariffs/', (out / 'index.html').read_text())
            self.assertIn('我的资费', (out / 'index.html').read_text())


if __name__ == '__main__':
    unittest.main()
