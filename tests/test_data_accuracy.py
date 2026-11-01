"""数据准确性回归：每条测试都对应一次和上游原始数据核对时发现的真实错误。"""
import asyncio
import datetime as dt
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _bootstrap  # noqa: F401,E402

from app.core import cache  # noqa: E402
from app.core.utils import is_trade_day  # noqa: E402
from app.services import globalmarket as gm  # noqa: E402
from app.services import lhb, market, screener, sentiment  # noqa: E402
from app.sources import tencent  # noqa: E402


class CalendarTests(unittest.TestCase):
    def test_spring_festival_extra_closure(self):
        self.assertFalse(is_trade_day(dt.date(2026, 2, 23)))


class BreadthTests(unittest.TestCase):
    def test_gt5_starts_at_bucket_6(self):
        """分桶 5 是 4%~5%，不能算进"涨幅>5%"。"""
        fenbu = [{"5": 37}, {"6": 35}, {"11": 47}, {"-5": 644}, {"-6": 475}, {"-11": 82}, {"0": 74}]

        async def fake(_d):
            return {"qdate": 20261030, "fenbu": fenbu}
        with patch("app.services.sentiment.em.zdfenbu", fake):
            b = asyncio.run(sentiment._breadth_em(None))
        self.assertEqual(b["gt5_up"], 82)
        self.assertEqual(b["lt5_down"], 557)


class SinaParseTests(unittest.TestCase):
    def test_znb_columns(self):
        f = "首尔综合指数,5730.7400,-206.92,-3.48,2:27 AM,1759127220,2026-10-30,14:33:00,5760.35,5937.66,5784.98,5599.42,0".split(",")
        p = gm._parse_sina(f, "znb")
        self.assertEqual((p["price"], p["pct"], p["prev_close"], p["high"], p["low"]),
                         (5730.74, -3.48, 5937.66, 5784.98, 5599.42))
        self.assertEqual(p["time"], "2026-10-30 14:33:00")

    def test_znb_short_row(self):
        p = gm._parse_sina("香港恒生指数,23294.42,335.77,1.46,04:08,1793434080".split(","), "znb")
        self.assertEqual((p["price"], p["pct"], p["prev_close"]), (23294.42, 1.46, None))

    def test_fx_uses_published_change(self):
        """第 8 列是最新价不是昨收，拿它算涨跌幅会恒为 0。"""
        f = ("04:59:58,6.652800,6.652900,6.652800,91,6.656000,6.657800,6.648700,6.652800,"
             "离岸人民币,-0.050000,-0.003000,0.001367,,6.995700,6.649700,,2026-10-31").split(",")
        p = gm._parse_sina(f, "fx")
        self.assertEqual(p["pct"], -0.05)
        self.assertEqual(p["prev_close"], 6.6558)
        self.assertEqual((p["high"], p["low"]), (6.6578, 6.6487))

    def test_dollar_index(self):
        f = "05:41:42,101.9669,101.9669,101.8857,5052,101.9016,102.0903,101.5851,101.9669,美元指数,2026-10-31".split(",")
        p = gm._parse_sina(f, "dini")
        self.assertEqual((p["price"], p["prev_close"]), (101.9669, 101.8857))
        self.assertAlmostEqual(p["pct"], 0.08, places=2)

    def test_us10y(self):
        f = ("美国10年期国债,4.937,4.910,4.932,4.958,4.892,0,0.4512,0.0222,0,0,1793395500,"
             "2026-10-30,17:25:00,2036-08-15,4.625,1年2次,97.633,美国").split(",")
        p = gm._parse_sina(f, "bond")
        self.assertEqual((p["price"], p["pct"]), (4.937, 0.4512))

    def test_old_quote_is_flagged_stale(self):
        self.assertTrue(gm._is_stale("2025-09-26 13:30:00"))


class KlineAmountTests(unittest.TestCase):
    def test_tencent_kline_returns_amount_in_yuan(self):
        async def fake(*_a, **_k):
            return {"data": {"sh000001": {"day": [
                ["2026-10-30", "3605.65", "3599.02", "3660.21", "3595.26", "497973940.00", {}, "1.02", "76422719.09"]]}}}
        with patch("app.core.http.fetch_json", fake):
            rows = asyncio.run(tencent.kline("sh000001", "day", 1))
        self.assertEqual(rows[0][2], 3599.02)                       # 收盘价仍在下标 2
        self.assertAlmostEqual(rows[0][6], 764227190900.0, delta=1)

    def _history(self, sh, sz):
        async def fake_kline(sym, _days, force=False):
            return cache.Sourced(data=sh if sym == "sh000001" else sz, source="tencent")

        async def fake_quotes(*_a, **_k):
            return cache.Sourced(data={}, source="tencent")
        with patch.object(market, "kline", fake_kline), patch.object(market, "fetch_quotes", fake_quotes):
            return asyncio.run(market.turnover_history(days=5))

    def test_one_sided_day_has_no_total(self):
        """只取到一个市场的日子不能当两市合计，否则像缩量一半。"""
        res = self._history([["2026-10-29", 1, 1, 1, 1, 1, 300.0], ["2026-10-30", 1, 1, 1, 1, 1, 400.0]],
                            [["2026-10-30", 1, 1, 1, 1, 1, 500.0]])
        by_date = {r["date"]: r["amount"] for r in res["items"]}
        self.assertIsNone(by_date["2026-10-29"])
        self.assertEqual(by_date["2026-10-30"], 900.0)
        self.assertFalse(res["estimated"])


def _seat(dept, buy, sell, tid="A", code="000568"):
    return {"code": code, "trade_id": tid, "dept": dept, "buy": buy, "sell": sell, "net": buy - sell,
            "net_yi": round((buy - sell) / 1e8, 2), "side": "buy", "seat": "", "tag": "", "style": "", "next_hint": ""}


class LhbTests(unittest.TestCase):
    def test_seat_in_both_lists_counts_once(self):
        both = _seat("深股通专用", 4e8, 1e8)
        rows = lhb.dedupe_seats([both, dict(both, side="sell")], {"A"})
        self.assertEqual(len(rows), 1)

    def test_distinct_institution_seats_are_kept(self):
        rows = lhb.dedupe_seats([_seat("机构专用", 1e8, 0), _seat("机构专用", 2e8, 0)], {"A"})
        self.assertEqual(len(rows), 2)

    def test_multi_reason_keeps_single_day_row(self):
        """三日累计包含当日，相加会把当日算两遍。"""
        rows = lhb._pick_base_rows([
            {"code": "002636", "trade_id": "3d", "amount": 1.0e10, "net": 2.78e8, "reason": "连续三日偏离"},
            {"code": "002636", "trade_id": "1d", "amount": 4.0e9, "net": 1.32e8, "reason": "日涨幅偏离"},
        ])
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]["trade_id"], rows[0]["net"]), ("1d", 1.32e8))
        self.assertIn("连续三日", rows[0]["reason"])

    def test_seats_of_other_list_are_excluded(self):
        self.assertEqual(lhb.dedupe_seats([_seat("某营业部", 1e8, 0, tid="3d")], {"1d"}), [])

    def test_rank_keeps_sellers(self):
        seats = [dict(_seat(f"席位{i}", 1e8 * (50 - i), 0), code=str(i)) for i in range(60)]
        rank = lhb.seat_rank_from(seats + [_seat("大卖家", 0, 9e9)])
        self.assertEqual(rank[-1]["dept"], "大卖家")
        self.assertLessEqual(len(rank), 40)


class HotIndustryTests(unittest.TestCase):
    def test_hot_uses_merged_members(self):
        """主线名是申万一级，涨停股是东财细分，要按 members 比对。"""
        async def fake():
            return {"main_lines": [{"name": "食品饮料", "members": ["白酒Ⅱ", "饮料制造"]}, {"name": "银行"}]}
        with patch.object(screener.sectors, "main_line", fake):
            hot = asyncio.run(screener._hot_industries())
        self.assertEqual(hot, {"白酒Ⅱ", "饮料制造", "银行"})


if __name__ == "__main__":
    unittest.main()
