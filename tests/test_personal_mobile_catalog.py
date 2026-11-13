import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'pipelines/mobile'))
import fetcher as f


def page(report, pages=1):
    return json.dumps({'returnCode': '0', 'data': {
        'page': {'pages': pages}, 'beans': [{'nonModuleList': [
            {'name': '流量包', 'reportNo': report, 'type1': 1, 'type2': 5,
             'onlineDay': '20260301', 'offineDay': '20261112'}]}]}})


class MobileCatalogTest(unittest.TestCase):
    def test_directory_includes_provincial_standard_and_deduplicates_alias(self):
        data = {'returnCode': '0', 'data': [
            {'tariffAttr': a, 'type1': 1, 'type2': t}
            for a, t in [('2', '1'), ('2', '2'), ('3', '5'), ('2', '5'), ('1', '4')]]}
        with patch.object(f, '_post', return_value=json.dumps(data)) as post:
            self.assertEqual(f._fetch_combos(None, '2', '931'), [('1', '1'), ('1', '2'), ('1', '5')])
            self.assertTrue(post.call_args.kwargs['api_url'].endswith('/getType2List'))
            self.assertEqual(json.loads(f._decrypt(post.call_args.args[1])),
                             {'province': '931', 'isPublic': '1'})
            self.assertEqual(f._fetch_combos(None, '1', '931'), [('1', '4')])

    def test_failed_or_malformed_directory_never_falls_back_to_six_cells(self):
        for data in [{'returnCode': '1', 'data': []}, {'returnCode': '0', 'data': []},
                     {'returnCode': '0', 'data': {}},
                     {'returnCode': '0', 'data': [{'tariffAttr': '2', 'type1': '1'}]}]:
            with self.subTest(data=data), patch.object(f, '_post', return_value=json.dumps(data)), \
                    patch.object(f, '_fetch_cell') as cell:
                items, errors, counts, failed = f._fetch_board('gansu', '2', '931', None)
                self.assertEqual(items, [])
                self.assertTrue(errors)
                self.assertEqual(failed, {'catalog'})
                cell.assert_not_called()

    def test_all_official_type_labels_preserve_expired_dates(self):
        for code, label in f.TYPE2_CN.items():
            result = f._parse_items(json.loads(page('EXPIRED')))[0]
            fields = f._nm_to_fields({'name': '旧业务', 'type2': code, 'offineDay': '20261112'})
            self.assertEqual(fields['资费类型'], label)
            self.assertEqual(fields['下线日期'], '2026年11月12日')
            self.assertEqual(result['fields']['资费类型'], '标准资费')

    def test_list_follows_official_pages(self):
        with patch.object(f, '_post', side_effect=[page('A', 2), page('B', 2)]) as post:
            result = f._fetch_cell(None, '2', '1', '5', '931')
            self.assertEqual({x['fields']['方案编号'] for x in result}, {'A', 'B'})
            self.assertEqual([json.loads(f._decrypt(c.args[1]))['page'] for c in post.call_args_list], [1, 2])

    def test_repeated_last_page_and_failed_response_are_incomplete(self):
        with patch.object(f, '_post', side_effect=[page('A', 2), page('A', 2)]):
            with self.assertRaisesRegex(ValueError, '分页不完整'):
                f._fetch_cell(None, '2', '1', '5', '931')
        with patch.object(f, '_post', return_value=json.dumps({'returnCode': '1'})):
            with self.assertRaisesRegex(ValueError, '列表查询失败'):
                f._fetch_cell(None, '2', '1', '5', '931')

    def test_board_fetches_every_discovered_category(self):
        def collect(opener, attr, t1, t2, code, ua):
            return [{'name': t1 + '-' + t2, 'fields': {'方案编号': t1 + t2}}]
        with patch.object(f, '_fetch_combos', return_value=[('1', '5'), ('2', '7')]), \
                patch.object(f, '_fetch_cell', side_effect=collect), patch.object(f.time, 'sleep'):
            items, errors, counts, failed = f._fetch_board('gansu', '2', '931', None)
            self.assertEqual(len(items), 2)
            self.assertEqual(set(counts), {'2,1,5', '2,2,7'})
            self.assertFalse(errors or failed)


if __name__ == '__main__':
    unittest.main()
