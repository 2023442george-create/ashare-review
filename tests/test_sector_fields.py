"""板块字段缺失的处理：缺字段不得被写成 0。

这组测试守的是同一类错误："上游没给这个值"被转成一个确定的数字。
涨/跌家数显示 0/0 时，用户会读成"这个板块无一只上涨"——那是一个极罕见
且含义强烈的事实。而真相往往只是镜像主机没返回 f104/f105。
两者必须在界面上长得不一样，所以在数据层就不能合并。
"""
import unittest
from unittest import mock
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _bootstrap  # noqa: F401,E402

from app.services import sectors  # noqa: E402
from app.sources import eastmoney as em  # noqa: E402


class CountParsingTests(unittest.TestCase):
    def test_missing_markers_become_none(self):
        for v in (None, "", "-", "--", "—"):
            self.assertIsNone(sectors._icount(v), repr(v))

    def test_real_zero_stays_zero(self):
        """真实的 0 必须保留——全板块无一只上涨虽然罕见，但是一个有效事实。"""
        self.assertEqual(sectors._icount(0), 0)
        self.assertEqual(sectors._icount("0"), 0)

    def test_numbers_parse(self):
        self.assertEqual(sectors._icount("37"), 37)
        self.assertEqual(sectors._icount(37.0), 37)

    def test_norm_board_without_count_fields(self):
        row = sectors._norm_board({"f12": "BK0447", "f14": "汽车", "f3": 2.1})
        self.assertIsNone(row["up_count"])
        self.assertIsNone(row["down_count"])
        self.assertEqual(row["pct"], 2.1)

    def test_norm_board_with_count_fields(self):
        row = sectors._norm_board({"f12": "BK0447", "f14": "汽车", "f3": 2.1,
                                   "f104": 37, "f105": 5})
        self.assertEqual((row["up_count"], row["down_count"]), (37, 5))


class FieldHealthTests(unittest.TestCase):
    def test_all_missing_is_flagged_with_a_note(self):
        rows = [{"up_count": None, "down_count": None, "main_flow_yi": 1.0,
                 "turnover": 2.0, "lead_stock": "甲"} for _ in range(5)]
        rows[0]["_field_meta"] = {"host": "push2delay.eastmoney.com",
                                  "missing_fields": ["f104", "f105"],
                                  "hosts_tried": [{"host": "push2delay.eastmoney.com", "rows": 5,
                                                   "missing_fields": ["f104", "f105"]}]}
        h = sectors.field_health(rows)
        self.assertTrue(h["counts_unavailable"])
        self.assertEqual(h["columns"]["up_count"]["state"], "all_missing")
        self.assertIn("f104/f105", h["note"])
        self.assertIn("push2delay", h["note"])

    def test_complete_rows_are_not_flagged(self):
        rows = [{"up_count": 10, "down_count": 2, "main_flow_yi": 1.0,
                 "turnover": 2.0, "lead_stock": "甲"}]
        h = sectors.field_health(rows)
        self.assertFalse(h["counts_unavailable"])
        self.assertEqual(h["columns"]["up_count"]["state"], "ok")
        self.assertNotIn("note", h)

    def test_partial_missing_is_not_an_upstream_alarm(self):
        """个别板块缺值是正常的，不该告警——只有整列缺才说明接口没给这个字段。"""
        rows = [{"up_count": 10, "down_count": 2}, {"up_count": None, "down_count": None}]
        h = sectors.field_health(rows)
        self.assertFalse(h["counts_unavailable"])
        self.assertEqual(h["columns"]["up_count"]["state"], "partial")

    def test_empty_input_is_safe(self):
        h = sectors.field_health(None)
        self.assertEqual(h["rows"], 0)
        self.assertFalse(h["counts_unavailable"])


class RowExtractionTests(unittest.TestCase):
    def test_list_form(self):
        self.assertEqual(em._rows_of({"data": {"diff": [{"f12": "a"}]}}), [{"f12": "a"}])

    def test_dict_form_is_ordered_by_index(self):
        """个别镜像把 diff 返回成 {"0":{...},"1":{...}}；按下标排序取出，否则顺序会乱。"""
        got = em._rows_of({"data": {"diff": {"1": {"f12": "b"}, "0": {"f12": "a"},
                                             "10": {"f12": "k"}}}})
        self.assertEqual([r["f12"] for r in got], ["a", "b", "k"])

    def test_empty_shapes(self):
        for payload in (None, {}, {"data": None}, {"data": {"diff": None}}, {"data": {"diff": []}}):
            self.assertEqual(em._rows_of(payload), [])

    def test_dash_counts_as_absent(self):
        rows = [{"f104": "-"}, {"f104": ""}]
        self.assertFalse(em._field_present(rows, "f104"))
        self.assertTrue(em._field_present(rows + [{"f104": 3}], "f104"))

    def test_real_zero_counts_as_present(self):
        self.assertTrue(em._field_present([{"f104": 0}], "f104"))


class ClistHostFallbackTests(unittest.TestCase):
    """核心回归：字段不全的主机不能终止链路。

    旧实现是"第一个返回了行的主机就采用"，于是一个只给行情、不给统计字段的
    镜像会让下游永远拿不到涨跌家数，而且毫无提示。
    """
    def _fetch(self, by_host):
        async def fetch_json(url, *, source="", params=None, **kw):
            for host, payload in by_host.items():
                if host in url:
                    return payload
            return None
        return fetch_json

    def test_skips_a_field_poor_host_and_uses_a_complete_one(self):
        poor = {"data": {"diff": [{"f12": "BK1", "f14": "甲", "f3": 1.0}]}}
        rich = {"data": {"diff": [{"f12": "BK1", "f14": "甲", "f3": 1.0, "f104": 20, "f105": 3}]}}
        by_host = {em.QUOTE_HOSTS[0]: poor, em.QUOTE_HOSTS[1]: rich}
        with mock.patch("app.core.http.fetch_json", self._fetch(by_host)):
            rows, meta = asyncio.run(em.clist_detail("m:90+t:2", "f12,f14,f3,f104,f105",
                                                     require=("f104", "f105")))
        self.assertEqual(meta["host"], em.QUOTE_HOSTS[1])
        self.assertEqual(meta["missing_fields"], [])
        self.assertEqual(rows[0]["f104"], 20)

    def test_all_hosts_poor_returns_data_and_reports_missing(self):
        """全都缺字段时仍要返回数据（涨跌幅等列是有用的），但必须如实报告缺了什么。"""
        poor = {"data": {"diff": [{"f12": "BK1", "f14": "甲", "f3": 1.0}]}}
        by_host = {h: poor for h in em.QUOTE_HOSTS}
        with mock.patch("app.core.http.fetch_json", self._fetch(by_host)):
            rows, meta = asyncio.run(em.clist_detail("m:90+t:2", "f12,f14,f3,f104,f105",
                                                     require=("f104", "f105")))
        self.assertTrue(rows)
        self.assertEqual(meta["missing_fields"], ["f104", "f105"])
        self.assertEqual(len(meta["hosts_tried"]), len(em.QUOTE_HOSTS))

    def test_no_data_at_all(self):
        with mock.patch("app.core.http.fetch_json", self._fetch({})):
            rows, meta = asyncio.run(em.clist_detail("m:90+t:2", "f12", require=("f104",)))
        self.assertEqual(rows, [])
        self.assertEqual(meta["missing_fields"], ["f104"])

    def test_boards_em_marks_upstream_gap_on_first_row(self):
        poor = {"data": {"diff": [{"f12": "BK1", "f14": "甲", "f3": 1.0},
                                  {"f12": "BK2", "f14": "乙", "f3": 0.5}]}}
        by_host = {h: poor for h in em.QUOTE_HOSTS}
        with mock.patch("app.core.http.fetch_json", self._fetch(by_host)):
            out = asyncio.run(sectors._boards_em("industry", "pct", 60))
        self.assertEqual(len(out), 2)
        self.assertIsNone(out[0]["up_count"])
        h = sectors.field_health(out)
        self.assertTrue(h["counts_unavailable"])
        self.assertEqual(h["upstream"]["missing_fields"], ["f104", "f105"])


if __name__ == "__main__":
    unittest.main()
