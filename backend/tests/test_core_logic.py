from __future__ import annotations

import asyncio
import datetime as dt
import unittest
from unittest.mock import patch

from app.core.cache import filter_providers
from app.core.utils import normalize_date
from app.services.auction import judge_auction
from app.services.industry_map import to_sw
from app.services.globalmarket import signals
from app.services.limitup import _norm_em, _pool_em, board_type, history_depth_ok
from app.services.reconcile import board_crosscheck
from app.services.report import _is_final_snapshot, assess_data_quality, build
from app.services.sectors import _sort_rows, line_confirm, position_ladder
from app.services.sentiment import _breadth_em, _quote_open_entry, promotion_rates


class DateAndSourceTests(unittest.TestCase):
    def test_date_normalization(self):
        self.assertEqual(normalize_date("20261023"), "2026-10-23")
        self.assertEqual(normalize_date("2026/10/23"), "2026-10-23")

    def test_mock_is_online_last_resort_blocked(self):
        async def real():
            return 1

        def fake():
            return 2

        online = filter_providers([("eastmoney", real), ("mock", fake)], offline=False)
        offline = filter_providers([("eastmoney", real), ("mock", fake)], offline=True)
        self.assertEqual([x[0] for x in online], ["eastmoney"])
        self.assertEqual([x[0] for x in offline], ["mock"])


class BoardAndPromotionTests(unittest.TestCase):
    def test_missing_seal_time_is_unknown_not_one_word(self):
        self.assertEqual(board_type(0, 0, 0, 10.0), "未知板型")
        row = _norm_em({"c": "000001", "n": "测试", "p": 10, "amount": 100,
                        "fund": 10, "ltsz": 1000, "fbt": 0, "lbt": 0, "zbc": 0,
                        "zttj": {"days": 1, "ct": 1}, "lbc": 1})
        self.assertEqual(row["board_type"], "未知板型")

    def test_first_promotion_uses_code_intersection(self):
        prev = [
            {"code": "A", "boards": 1},
            {"code": "B", "boards": 2},
        ]
        today = [
            {"code": "A", "boards": 2},
            {"code": "C", "boards": 2},
        ]
        rates = promotion_rates(prev, today)
        self.assertEqual(rates["promote_rate"], 50.0)
        self.assertEqual(rates["first_promote_rate"], 100.0)
        self.assertEqual(rates["promoted_first"], 1)

    def test_open_entry_excludes_limit_sealed(self):
        gap, ret, sealed = _quote_open_entry(
            {"prev_close": 10, "open": 11, "price": 11, "limit_up": 11}
        )
        self.assertEqual(gap, 10.0)
        self.assertEqual(ret, 0.0)
        self.assertTrue(sealed)

    def test_pool_date_uses_request_not_source_qdate(self):
        async def fake_pool(date=None):
            return {"qdate": 20261023, "tc": 1,
                    "pool": [{"c": "000001", "n": "测试", "p": 10, "lbc": 1, "fbt": 93000}]}

        with patch("app.services.limitup.em.zt_pool", fake_pool):
            data = asyncio.run(_pool_em("zt", "2026-10-22"))
        self.assertEqual(data["date"], "2026-10-22")
        self.assertEqual(data["source_qdate"], "20261023")

    def test_breadth_rejects_other_date(self):
        async def fake_breadth(date=None):
            return {"qdate": 20261023, "fenbu": [{"1": 3000}, {"0": 100}]}

        with patch("app.services.sentiment.em.zdfenbu", fake_breadth):
            data = asyncio.run(_breadth_em("2026-10-22"))
        self.assertIsNone(data)

    def test_pool_rejects_non_trade_day(self):
        async def fake_pool(date=None):
            return {"qdate": 20261003, "tc": 1, "pool": [{"c": "000001", "n": "测试"}]}

        with patch("app.services.limitup.em.zt_pool", fake_pool):
            data = asyncio.run(_pool_em("zt", "2026-10-03"))  # 周六
        self.assertIsNone(data)

    def test_history_depth_rejects_older_date(self):
        # 盘中（当前时段=今天）用今天行情算昨天的次日指标，就是把未来数据回填历史。
        with patch("app.services.limitup.current_trade_date",
                   return_value=dt.date(2026, 10, 23)):
            self.assertTrue(history_depth_ok("2026-10-23"))
            self.assertFalse(history_depth_ok("2026-10-22"))


class SectorConfirmTests(unittest.TestCase):
    def test_all_four_dimensions_pass(self):
        self.assertEqual(line_confirm(6, 3, 4.2, 8.5), [])

    def test_each_missing_dimension_is_reported(self):
        gaps = line_confirm(3, 1, 1.0, -2.0)
        self.assertEqual(len(gaps), 4)
        self.assertTrue(any("涨停仅3家" in g for g in gaps))
        self.assertTrue(any("无连板龙头" in g for g in gaps))
        self.assertTrue(any("未超2%" in g for g in gaps))
        self.assertTrue(any("净流出" in g for g in gaps))

    def test_missing_sector_quote_is_not_zero(self):
        gaps = line_confirm(6, 3, None, None)
        self.assertIn("缺少板块涨幅", gaps)
        self.assertIn("缺少主力资金", gaps)


class ReportSnapshotTests(unittest.TestCase):
    def test_past_date_is_final_future_is_not(self):
        self.assertTrue(_is_final_snapshot("2020-01-02"))
        self.assertFalse(_is_final_snapshot("2099-01-02"))

    def test_cannot_rebuild_other_day_without_snapshot(self):
        with patch("app.services.report.current_trade_date",
                   return_value=dt.date(2026, 10, 23)), \
             patch("app.services.report.last_trade_day",
                   return_value=dt.date(2026, 10, 23)), \
             patch("app.services.report.store.load_snapshot", return_value=None):
            with self.assertRaises(ValueError):
                asyncio.run(build("2026-10-22"))


class ReportQualityTests(unittest.TestCase):
    def _senti(self):
        return {
            "sources": {"limit_up": "eastmoney", "broken": "eastmoney",
                        "limit_down": "eastmoney", "breadth": "eastmoney"},
            "data_quality": {"premium_available": True},
            "metrics": {"prev_limit_up": 20},
        }

    def test_missing_sector_degrades_not_blocks(self):
        q = assess_data_quality(
            self._senti(), {"sources": {"industry": "none", "concept": "none"}},
            {"signal": {"excluded": []}, "meta": {"source": "multi"}}, {"total_yi": 20000},
        )
        self.assertEqual(q["level"], "limited")
        self.assertTrue(q["decision_enabled"])

    def test_missing_sentiment_blocks_decision(self):
        senti = self._senti()
        senti["sources"]["limit_up"] = "mock"
        q = assess_data_quality(
            senti, {"sources": {"industry": "eastmoney", "concept": "eastmoney"}},
            {"signal": {"excluded": []}, "meta": {"source": "multi"}}, {"total_yi": 20000},
        )
        self.assertEqual(q["level"], "invalid")
        self.assertFalse(q["decision_enabled"])


class GlobalAndAuctionTests(unittest.TestCase):
    def test_stale_global_data_cannot_score(self):
        result = signals([
            {"key": "VIX", "price": 40, "pct": 20, "source": "tencent", "stale": True},
            {"key": "SOX", "price": 100, "pct": 2.5, "source": "sina"},
        ])
        self.assertEqual(result["excluded"], ["VIX"])
        self.assertEqual(result["score"], 3)
        self.assertTrue(all("VIX" not in s["text"] for s in result["signals"]))

    def test_auction_rules(self):
        self.assertEqual(judge_auction(4.0, False, 3.0, "first_board", True)["level"], "pass")
        self.assertEqual(judge_auction(8.0, False, 9.0, "first_board", True)["level"], "avoid")
        self.assertEqual(judge_auction(11.0, True, 9.0, "first_board", True)["level"], "unbuyable")
        self.assertEqual(judge_auction(4.0, False, 3.0, "first_board", False)["level"], "wait")
        self.assertEqual(judge_auction(1.0, False, 1.0, "first_board", True)["level"], "weak")


class SectorSourceTests(unittest.TestCase):
    def test_position_ladder_orders_by_boards_then_fund(self):
        zt_ind = {"通用设备": {"stocks": [
            {"code": "A", "name": "甲", "boards": 1, "fund": 5e8, "first_min": 600},
            {"code": "B", "name": "乙", "boards": 3, "fund": 1e7, "first_min": 570},
            {"code": "C", "name": "丙", "boards": 1, "fund": 2e8, "first_min": 570},
        ]}}
        p = position_ladder(zt_ind)["通用设备"]
        # 3 板优先；同为 1 板时封单 5 亿排在 2 亿之前
        self.assertEqual([x["code"] for x in p], ["B", "A", "C"])
        self.assertEqual(p[0]["seat_label"], "龙一")
        self.assertEqual(p[1]["seat_label"], "龙二")
        self.assertEqual(p[2]["seat_label"], "跟风")
        self.assertEqual(p[1]["board_gap"], 2)

    def test_sort_rows_puts_none_last(self):
        rows = [{"pct": None}, {"pct": 2.0}, {"pct": -1.0}]
        self.assertEqual(_sort_rows(rows, "pct")[0]["pct"], 2.0)
        self.assertIsNone(_sort_rows(rows, "pct")[-1]["pct"])

    def test_board_crosscheck_flags_large_gap(self):
        async def fake(kind="gn", limit=80):
            return [{"name": "昨日涨停", "pct": 3.38}]

        with patch("app.sources.tencent.board_rank", fake):
            ok = asyncio.run(board_crosscheck(3.38))
            bad = asyncio.run(board_crosscheck(9.90))
        self.assertTrue(ok["ok"])
        self.assertEqual(ok["diff"], 0.0)
        self.assertFalse(bad["ok"])

    def test_board_crosscheck_skips_without_sample(self):
        self.assertIsNone(asyncio.run(board_crosscheck(None))["ok"])


class IndustryMapTests(unittest.TestCase):
    def test_truncated_names_map_to_sw_level1(self):
        self.assertEqual(to_sw("汽车零部"), "汽车")
        self.assertEqual(to_sw("自动化设"), "机械设备")
        self.assertEqual(to_sw("炼化及贸"), "石油石化")
        self.assertEqual(to_sw("房地产开"), "房地产")

    def test_exact_alias_wins_over_prefix(self):
        # 「电力」属于公用事业，不能被前缀吞到「电力设备」里
        self.assertEqual(to_sw("电力"), "公用事业")
        self.assertEqual(to_sw("半导体"), "电子")

    def test_unknown_industry_returns_none(self):
        self.assertIsNone(to_sw("不存在的行业"))
        self.assertIsNone(to_sw(""))


if __name__ == "__main__":
    unittest.main()
