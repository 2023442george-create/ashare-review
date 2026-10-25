"""对账层：两条独立路径 + 不变量。

这组测试回答一个问题——如果数据真的错了，系统会不会发现？
所以每个用例都刻意喂进一个错误，然后断言它被抓到。
"""
import unittest
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _bootstrap  # noqa: F401,E402

from app.services import reconcile as rc  # noqa: E402

DATE = "2026-10-23"


def _it(code, name, price, pct):
    return {"code": code, "name": name, "price": price, "pct": pct}


class PriceBasedCheckTests(unittest.TestCase):
    def test_clean_pool_matches(self):
        items = [_it("600000", "甲", 11.0, 10.0),      # 主板 10%
                 _it("300001", "乙", 12.0, 20.0),      # 创业板 20%
                 _it("688001", "丙", 12.0, 20.0)]      # 科创板 20%
        r = rc.price_based_check(items, DATE)
        self.assertEqual(r["matched"], 3)
        self.assertEqual(r["mismatched"], 0)
        self.assertEqual(r["verdict"], "ok")

    def test_stock_that_did_not_actually_seal_is_caught(self):
        """池子里混进一只只涨了 6% 的票——必须被独立判定抓出来。"""
        items = [_it("600000", "甲", 11.0, 10.0), _it("600002", "乙", 10.6, 6.0)]
        r = rc.price_based_check(items, DATE)
        self.assertEqual(r["mismatched"], 1)
        self.assertEqual(r["verdict"], "suspect")
        self.assertEqual(r["mismatched_sample"][0]["code"], "600002")

    def test_st_stock_is_recognised_by_name(self):
        """主板 ST 股封在 5%，若不识别 ST 会被 10% 档误判成假错报。"""
        items = [_it("600003", "ST甲", 10.5, 5.0)]
        r = rc.price_based_check(items, DATE)
        self.assertEqual(r["matched"], 1)
        self.assertEqual(r["st_detected"], 1)

    def test_unknown_board_is_excluded_from_denominator(self):
        """口径不确定的票不计入分母，而不是算成一致——否则一致率会被灌水。"""
        items = [_it("600000", "甲", 11.0, 10.0), _it("123456", "怪码", 11.0, 10.0)]
        r = rc.price_based_check(items, DATE)
        self.assertEqual(r["decided"], 1)
        self.assertEqual(r["unknown"], 1)
        self.assertEqual(r["match_rate"], 100.0)

    def test_chinext_before_2020_uses_ten_percent(self):
        """同一只创业板票，2020-08-24 前后判定必须不同。"""
        items = [_it("300001", "乙", 11.0, 10.0)]
        self.assertEqual(rc.price_based_check(items, "2020-08-20")["matched"], 1)
        self.assertEqual(rc.price_based_check(items, "2026-10-23")["mismatched"], 1)

    def test_empty_pool_is_no_data_not_ok(self):
        self.assertEqual(rc.price_based_check([], DATE)["verdict"], "no_data")


class InvariantTests(unittest.TestCase):
    def _ok_metrics(self):
        return {"broken_rate": 20.0, "seal_rate": 80.0, "lianban_count": 5,
                "first_board_count": 10, "max_boards": 3, "promote_rate": 30.0,
                "premium_sample": 40, "tradable_premium_sample": 31}

    def _ok_ladder(self):
        return {"levels": [{"boards": 3, "count": 2}, {"boards": 2, "count": 3},
                           {"boards": 1, "count": 10}]}

    def test_all_pass_on_consistent_input(self):
        checks = rc.invariants(self._ok_metrics(), self._ok_ladder(), 15, 40)
        self.assertFalse([c for c in checks if c["ok"] is False], checks)

    def test_ladder_sum_mismatch_is_caught(self):
        checks = rc.invariants(self._ok_metrics(), self._ok_ladder(), 99, 40)
        failed = [c["check"] for c in checks if c["ok"] is False]
        self.assertIn("天梯分层求和=涨停总数", failed)

    def test_seal_plus_broken_must_be_100(self):
        m = self._ok_metrics()
        m["seal_rate"] = 60.0
        failed = [c["check"] for c in rc.invariants(m, self._ok_ladder(), 15, 40)
                  if c["ok"] is False]
        self.assertIn("封板率+炸板率=100", failed)

    def test_out_of_range_broken_rate_is_caught(self):
        m = self._ok_metrics()
        m["broken_rate"] = 137.0
        m["seal_rate"] = -37.0
        failed = [c["check"] for c in rc.invariants(m, self._ok_ladder(), 15, 40)
                  if c["ok"] is False]
        self.assertIn("炸板率值域", failed)

    def test_tradable_sample_cannot_exceed_total_sample(self):
        m = self._ok_metrics()
        m["tradable_premium_sample"] = 99
        failed = [c["check"] for c in rc.invariants(m, self._ok_ladder(), 15, 40)
                  if c["ok"] is False]
        self.assertIn("可成交样本≤总样本", failed)

    def test_max_boards_must_match_ladder_top(self):
        m = self._ok_metrics()
        m["max_boards"] = 9
        failed = [c["check"] for c in rc.invariants(m, self._ok_ladder(), 15, 40)
                  if c["ok"] is False]
        self.assertIn("最高连板=天梯最高层", failed)

    def test_missing_values_report_none_not_false(self):
        """缺数据应报"未知"，不能报"失败"——否则真 bug 会被淹没在噪音里。"""
        checks = rc.invariants({}, {}, 0, None)
        self.assertFalse([c for c in checks if c["ok"] is False])
        self.assertTrue([c for c in checks if c["ok"] is None])


if __name__ == "__main__":
    unittest.main()
