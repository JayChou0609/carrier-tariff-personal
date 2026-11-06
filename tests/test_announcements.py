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

    def test_unicom_headquarters_uses_only_official_national_label(self):
        def post(url, form, headers):
            self.assertEqual(form['province'], '034')
            if url == a.UNI_LIST_URL:
                return json.dumps({'result':[
                    {'id':'national','title':'总部全国公告','publishTime':'2026-11-05','creatorProvinceName':'全国'},
                    {'id':'jiangsu','title':'江苏公告','publishTime':'2026-11-06','creatorProvinceName':'江苏'},
                    {'id':'unknown','title':'范围缺失','publishTime':'2026-11-06'}], 'totalPages':1})
            self.assertEqual(form['announcementId'], 'national')
            return json.dumps({'tNoticeDto':{'noticeDetails':'<p>全国公告正文</p>','noticeTime':'2026-11-05'}})
        with patch.object(a,'_http_post',side_effect=post),patch.object(a.time,'sleep'):
            self.assertEqual([item['id'] for item in a.fetch_uni('quanguo')], ['national'])

    def test_national_failure_never_uses_provincial_cache(self):
        with tempfile.TemporaryDirectory() as td:
            p=str(Path(td)/'announce.json')
            a.write_json([{'id':'js','title':'江苏公告'}],p,'unicom')
            a.write_json([],p,'unicom','failed','timeout','quanguo')
            d=json.loads(Path(p).read_text())
            self.assertEqual(d['province'],'quanguo')
            self.assertEqual(d['items'],[])

    def test_telecom_list_sorting_and_balanced_rich_text(self):
        listing='<ul><li><a href="/js/sy_ycgg/1.html">旧公告</a><span>2026-01-01</span></li><li><a href="/js/sy_ycgg/2.html">新公告</a><span>2026-11-05</span></li><li><a href="/other">无关导航</a></li></ul>'
        self.assertEqual([x['id'] for x in a.telecom_list(listing)],['2','1'])
        html='<nav>不要采集导航</nav><div class="notice_content"><div><p>公告正文</p><a href="/js/jsfile/a.xlsx">附件</a><img src="/images/a.jpg" onerror="alert(1)"><script>bad()</script></div></div><footer>不要采集页脚</footer>'
        content=a.telecom_content(html)
        self.assertIn('公告正文',content)
        for bad in ['不要采集','onerror','bad()']:
            self.assertNotIn(bad,content)
        self.assertEqual(a.find_attachments(content,a.TELECOM_SITE)[0]['url'],'https://img.189.cn/js/jsfile/a.xlsx')
        with self.assertRaises(ValueError):a.telecom_content('<html>挑战页面</html>')
        with self.assertRaises(ValueError):a.telecom_list('<html>错误页面</html>')

    def test_new_published_feeds_have_correct_operator_and_scope(self):
        for path,operator,scope in [('unicom/data/announce-national.json','unicom','quanguo'),('telecom/data/announce.json','telecom','jiangsu')]:
            data=json.loads((ROOT/path).read_text())
            self.assertEqual((data['operator'],data['province']),(operator,scope))
            self.assertEqual(data['count'],15)
            self.assertEqual(len({x['id'] for x in data['items']}),15)
            self.assertEqual([x['date'] for x in data['items']],sorted([x['date'] for x in data['items']],reverse=True))
            self.assertTrue(all(x['title'] and x['content'] for x in data['items']))

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
