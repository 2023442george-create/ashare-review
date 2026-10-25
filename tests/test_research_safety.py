"""评分口径与决策闸门：防止"看起来很好的数字"悄悄回到评分里。

本文件的核心是一条回归测试：情绪分绝不能再使用昨日涨停股的**收盘**涨跌幅。
那个数字对一只今天一字板封死的票是全天都拿不到的价格，用它当"打板次日收益"
会在一字板密集的最危险行情里高估得最厉害。修好容易，复发更容易——
只要有人写一行 `m.get("tradable_premium") or m.get("prev_premium")` 就回去了。
"""
import unittest
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _bootstrap  # noqa: F401,E402

from app.core import params  # noqa: E402
from app.services.report import apply_reconcile_gate, assess_data_quality  # noqa: E402
from app.services.sentiment import score_components, score_band  # noqa: E402


def _metrics(**kw):
    base = {"limit_up": 70, "limit_down": 2, "broken": 15, "broken_rate": 18.0,
            "max_boards": 5, "up_ratio": 56.0, "promote_rate": 30.0,
            "tradable_premium": 2.0, "tradable_premium_sample": 80}
    base.update(kw)
    return base


class PremiumCaliberTests(unittest.TestCase):
    def test_close_based_premium_is_ignored_by_the_score(self):
        """只给收盘口径、不给可成交口径时，溢价因子必须退回中性，不得采用收盘值。"""
        comps, _ = score_components({"limit_up": 70, "prev_premium": 9.9})
        prem = [c for c in comps if c["key"] == "tradable_premium"][0]
        self.assertTrue(prem["low_confidence"])
        self.assertIsNone(prem["value"])
        self.assertEqual(prem["score"], params.SENTIMENT["tradable_premium"]["missing"])

    def test_a_huge_but_tiny_sample_premium_cannot_move_the_score(self):
        """9 只样本、平均 +9.9% 的"赚钱效应"不许抬高情绪分。"""
        strong_small = score_components(_metrics(tradable_premium=9.9,
                                                 tradable_premium_sample=9))[1]
        neutral = score_components(_metrics(tradable_premium=None,
                                            tradable_premium_sample=0))[1]
        self.assertAlmostEqual(strong_small, neutral, places=6)

    def test_a_large_sample_premium_does_move_the_score(self):
        low = score_components(_metrics(tradable_premium=-2.0))[1]
        high = score_components(_metrics(tradable_premium=4.0))[1]
        self.assertGreater(high, low + 5)

    def test_premium_factor_exposes_its_sample_size(self):
        comps, _ = score_components(_metrics(tradable_premium_sample=41))
        prem = [c for c in comps if c["key"] == "tradable_premium"][0]
        self.assertEqual(prem["sample"], 41)
        self.assertEqual(prem["min_sample"], params.STATS["min_sample"])


class ScoreShapeTests(unittest.TestCase):
    def test_component_scores_stay_in_range(self):
        comps, total = score_components({
            "limit_up": 500, "limit_down": 0, "broken": 0, "broken_rate": 0,
            "max_boards": 99, "tradable_premium": 99, "tradable_premium_sample": 500,
            "up_ratio": 100, "promote_rate": 100})
        self.assertTrue(0 <= total <= 100)
        self.assertTrue(all(0 <= c["score"] <= 100 for c in comps))

    def test_extreme_negative_inputs_stay_in_range(self):
        comps, total = score_components({
            "limit_up": 0, "limit_down": 400, "broken": 300, "broken_rate": 100,
            "max_boards": 0, "tradable_premium": -50, "tradable_premium_sample": 500,
            "up_ratio": 0, "promote_rate": 0})
        self.assertTrue(0 <= total <= 100)
        self.assertTrue(all(0 <= c["score"] <= 100 for c in comps))

    def test_weights_sum_to_one(self):
        comps, _ = score_components({})
        self.assertAlmostEqual(sum(c["weight"] for c in comps), 1.0, places=6)

    def test_missing_everything_does_not_crash(self):
        comps, total = score_components({})
        self.assertIsInstance(total, float)
        self.assertEqual(len(comps), 7)

    def test_scores_come_from_params_not_literals(self):
        """改 params 必须改变结果——否则说明阈值还硬编码在代码里。"""
        before = score_components(_metrics())[1]
        snap = params.perturbed(1.5)["sentiment"]
        self.assertNotAlmostEqual(before, score_components(_metrics(), snap)[1], places=3)


class ScoreBandTests(unittest.TestCase):
    def test_band_brackets_the_point_estimate(self):
        b = score_band(_metrics())
        self.assertLessEqual(b["lo"], b["point"])
        self.assertLessEqual(b["point"], b["hi"])
        self.assertGreater(b["width"], 0, "参数扰动区间宽度为 0 说明扰动没生效")

    def test_band_carries_param_identity(self):
        b = score_band(_metrics())
        self.assertEqual(b["param_digest"], params.digest())
        self.assertEqual(b["params_version"], params.PARAM_VERSION)


class DataQualityGateTests(unittest.TestCase):
    def _base(self):
        return (
            {"sources": {"limit_up": "eastmoney", "broken": "eastmoney",
                         "limit_down": "eastmoney", "breadth": "eastmoney"},
             "data_quality": {"premium_available": True}},
            {"sources": {"industry": "eastmoney", "concept": "eastmoney"}},
            {"signal": {"excluded": []}, "meta": {"source": "tencent"}},
            {"total_yi": 12000, "estimated": False},
        )

    def test_complete_inputs_do_not_block_decision(self):
        q = assess_data_quality(*self._base())
        self.assertEqual(q["level"], "complete")
        self.assertTrue(q["decision_enabled"])

    def test_mock_critical_source_blocks_decision(self):
        senti, ml, gl, turn = self._base()
        senti["sources"]["limit_up"] = "mock"
        q = assess_data_quality(senti, ml, gl, turn)
        self.assertEqual(q["level"], "invalid")
        self.assertFalse(q["decision_enabled"])

    def test_estimated_turnover_adds_warning(self):
        senti, ml, gl, turn = self._base()
        turn["estimated"] = True
        q = assess_data_quality(senti, ml, gl, turn)
        self.assertEqual(q["level"], "limited")
        self.assertTrue(any("估算" in w["message"] for w in q["warnings"]))


class ReconcileGateTests(unittest.TestCase):
    def _q(self):
        return {"level": "complete", "decision_enabled": True, "blockers": [], "warnings": []}

    def test_invariant_failure_blocks_decision(self):
        """算错比缺数更严重：缺数看得见，算错看不见。必须直接禁用决策。"""
        q = apply_reconcile_gate(self._q(), {
            "overall": "fail",
            "invariants_failed": [{"check": "天梯分层求和=涨停总数"}]})
        self.assertEqual(q["level"], "invalid")
        self.assertFalse(q["decision_enabled"])

    def test_cross_source_mismatch_is_a_warning_not_a_block(self):
        """跨源不一致可能只是口径差异（北交所/ST/新股），降级而不是禁用。"""
        q = apply_reconcile_gate(self._q(), {"overall": "inconsistent", "summary": "差 7 家"})
        self.assertEqual(q["level"], "limited")
        self.assertTrue(q["decision_enabled"])

    def test_missing_cross_check_is_not_treated_as_success(self):
        q = apply_reconcile_gate(self._q(), {"overall": "incomplete"})
        self.assertEqual(q["level"], "limited")
        self.assertTrue(any("不等于数据正确" in w["message"] for w in q["warnings"]))

    def test_low_confidence_factor_is_surfaced(self):
        q = apply_reconcile_gate(self._q(), {"overall": "consistent"},
                                 {"low_confidence_factors": ["tradable_premium"]})
        self.assertEqual(q["level"], "limited")

    def test_clean_reconcile_keeps_complete_and_does_not_mutate_input(self):
        src = self._q()
        q = apply_reconcile_gate(src, {"overall": "consistent"})
        self.assertEqual(q["level"], "complete")
        self.assertEqual(src["level"], "complete")
        self.assertEqual(src["warnings"], [])


class CostModelTests(unittest.TestCase):
    def test_round_trip_cost_is_material(self):
        """打板来回成本不可能忽略不计；若低于 0.3% 说明成本模型被改空了。"""
        from app.services.track import total_cost_pct
        self.assertGreater(total_cost_pct(), 0.3)

    def test_cost_includes_both_sides_and_stamp_duty(self):
        c = params.COST
        self.assertGreater(c["stamp_duty_bps"], 0)
        self.assertGreater(c["slippage_bps"], 0)


if __name__ == "__main__":
    unittest.main()
