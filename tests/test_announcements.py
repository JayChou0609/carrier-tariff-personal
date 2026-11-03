"""Regression checks for province identity, pagination, cache retention and safe rich text."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('announcements', ROOT / 'pipelines/scripts/announce_fetch.py')
a = importlib.util.module_from_spec(spec)
spec.loader.exec_module(a)


class AnnouncementTest(unittest.TestCase):
    def test_unicom_reads_all_pages_and_sorts_before_limiting(self):
        pages = []
        def post(url, form, headers):
            self.assertEqual(form['province'], '034')
            if url == a.UNI_LIST_URL:
                page = int(form['pageNo'])
                pages.append(page)
                rows = [{'id': str(i), 'title': '江苏公告' + str(i), 'publishTime': '2026-10-%02d' % i, 'creatorProvinceName': '江苏'} for i in (range(1, 16) if page == 1 else range(16, 21))]
                rows += [{'id': 'other', 'title': '江西公告', 'publishTime': '2026-11-03', 'creatorProvinceName': '江西'}]
                return json.dumps({'result': rows, 'totalPages': 2})
            return json.dumps({'tNoticeDto': {'title': '????', 'noticeDetails': '<p>江苏正文</p>', 'noticeTime': '2026-10-%02d' % int(form['announcementId']), 'annexInfos': [{'enclosureUrl': 'https://m1.img.10010.com/a.xlsx', 'enclosureName': '???'}]}})
        with patch.object(a, '_http_post', side_effect=post), patch.object(a.time, 'sleep'):
            items = a.fetch_uni()
        self.assertEqual(pages, [1, 2])
        self.assertEqual(len(items), 15)
        self.assertEqual(items[0]['id'], '20')
        self.assertEqual(items[-1]['id'], '6')
        self.assertEqual(items[0]['title'], '江苏公告20')
        self.assertEqual(items[0]['attachments'][0]['name'], 'a.xlsx')

    def test_rich_text_keeps_images_tables_and_removes_active_attributes(self):
        result = a.clean_html('<script>alert(1)</script><img src="/a.jpg" onerror="alert(2)"><a href="jav&#x61;script:alert(3)">x</a><table><tr><td colspan="2">正文</td></tr></table>', 'uni')
        self.assertNotIn('alert(', result)
        self.assertNotIn('onerror', result)
        self.assertIn('https://m1.img.10010.com/a.jpg', result)
        self.assertIn('colspan="2"', result)

    def test_failure_preserves_only_same_province_and_operator(self):
        with tempfile.TemporaryDirectory() as td:
            p = str(Path(td) / 'announce.json')
            item = {'id': '1', 'title': '江苏公告', 'content': '<p>正文</p>'}
            a.write_json([item], p, 'mobile')
            success = json.loads(Path(p).read_text())
            a.write_json([], p, 'mobile', 'failed', 'timeout')
            retained = json.loads(Path(p).read_text())
            self.assertEqual(retained['items'], success['items'])
            self.assertEqual(retained['updated'], success['updated'])
            self.assertEqual(retained['status'], 'failed')
            Path(p).write_text(json.dumps({'items': [{'title': '江西公告'}]}))
            a.write_json([], p, 'mobile', 'failed', 'timeout')
            self.assertEqual(json.loads(Path(p).read_text())['items'], [])
            with self.assertRaises(ValueError):
                a.write_json([], p, 'mobile')

    def test_published_feeds_are_jiangsu_with_latest_fifteen(self):
        for path, operator in [('data/announce.json', 'mobile'), ('unicom/data/announce.json', 'unicom')]:
            data = json.loads((ROOT / path).read_text())
            self.assertEqual(data['province'], 'jiangsu')
            self.assertEqual(data['operator'], operator)
            self.assertEqual(data['count'], 15)
            self.assertEqual(len({it['id'] for it in data['items']}), 15)
            dates = [it['date'] for it in data['items']]
            self.assertEqual(dates, sorted(dates, reverse=True))
            for it in data['items']:
                self.assertTrue(it['title'])
                self.assertTrue(it['content'])
                self.assertNotIn('???', it['title'])


if __name__ == '__main__':
    unittest.main()
