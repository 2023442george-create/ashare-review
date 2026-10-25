"""复盘报告的 Markdown 渲染：保证"证据边界"那一节真的会被写出来。

为什么单独测它：报告是用户每天真正会读的那份输出。渲染函数纯粹但字段很多，
一旦某个新字段在 build() 里没传下来，报告会静默少掉一整节，而没有任何报错。
"""
import unittest
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _bootstrap  # noqa: F401,E402

from app.core import params  # noqa: E402
from app.services import report as R  # noqa: E402


def _payload(**over):
    p = {
        "date": "2026-10-23",
        "generated_at": "2026-10-23 15:20:00",
        "research_status": {
            "methodology_version": "params-x/track-v1", "param_digest": "deadbeef1234",
            "params_stable": True, "frozen_days": 42, "settled_days": 37,
            "stage_cn": "初步样本（已结算 37/60 个交易日）", "validated": False,
            "cost_pct": 0.702, "benchmark": "sz399303",
            "statement": "由账本算出的状态。",
            "what_would_change_this": ["连续结算 ≥60 日", "BH 校正后 p ≤0.05"],
        },
        "reconcile": {"overall": "consistent", "summary": "两条独立路径一致（涨停池 58 vs 分布档 58，差 0）",
                      "invariants_failed": []},
        "data_quality": {"level": "complete", "decision_enabled": True, "blockers": [],
                         "warnings": [], "as_of": "2026-10-23 15:20:00", "point_in_time": True},
        "composite": {
            "score": 68.4, "band": {"point": 68.4, "lo": 61.0, "hi": 74.9, "width": 13.9,
                                    "perturb_pct": 20.0, "param_digest": "deadbeef1234", "note": "n"},
            "decision_enabled": True, "position": "6-8成（进攻）", "position_tip": "可上",
            "parts": [{"name": "市场情绪", "score": 70.0, "weight": 0.5, "source": "x"}],
        },
        "market": {
            "indices": [{"name": "上证指数", "price": 3400.0, "pct": 0.5, "amount_yi": 5000}],
            "turnover": {"total_yi": 15000, "level": {"label": "温和放量", "tip": "可参与"},
                         "delta_yi": 800, "ma5_yi": 14000, "estimated": False},
            "breadth": {"up": 3000, "down": 1800, "flat": 100, "up_ratio": 62.5},
            "style": {"label": "成长/小盘占优", "desc": "d", "play": "p"},
        },
        "sentiment": {
            "score": 70.0, "label": "主升发酵",
            "phase": {"phase": "发酵", "desc": "d", "score_delta": 3.0, "trend": "上升"},
            "metrics": {"limit_up": 58, "limit_down": 1, "broken": 12, "broken_rate": 17.1,
                        "max_boards": 5, "lianban_count": 15, "first_board_count": 43,
                        "one_word_count": 4, "prev_premium": 3.4, "prev_red_ratio": 61.0,
                        "open_premium": 1.9, "open_entry_return": 1.2,
                        "tradable_premium": 1.2, "tradable_premium_sample": 41,
                        "premium_sample": 52, "unbuyable_rate": 21.2,
                        "promote_rate": 31.0, "first_promote_rate": 22.0,
                        "fund_total_yi": 88.0, "avg_seal_ratio": 18.0},
            "components": [{"name": "涨停家数", "value": 58, "score": 64.4, "weight": 0.18,
                            "low_confidence": False},
                           {"name": "昨涨停可成交溢价", "value": 1.2, "score": 64.4, "weight": 0.17,
                            "unit": "%", "low_confidence": False}],
            "score_band": {"point": 70.0, "lo": 64.1, "hi": 76.2, "width": 12.1,
                           "perturb_pct": 20.0},
            "low_confidence_factors": [],
            "factor_independence": {"effective_factors": 2.1, "nominal_factors": 7,
                                    "verdict": "因子高度共线，加权细调属于伪精度"},
            "prev_premium_detail": {"stats": {"tradable": {
                "n": 41, "median": 0.9, "win_rate": 56.1, "reportable": True, "note": "",
                "ci": {"lo": -0.4, "hi": 2.8}}}},
            "score_history": [],
        },
        "ladder": {"max_boards": 5, "levels": [{"boards": 5, "count": 1, "stocks": [{"name": "甲"}]}],
                   "gaps": [], "comment": "梯队完整"},
        "main_lines": [{"name": "机器人", "zt_count": 8, "max_boards": 5, "pct": 4.2,
                        "main_flow_yi": 12.0, "reason": "r", "stocks": [{"name": "甲", "boards": 5}]}],
        "hot_concepts": [], "flow_in_top": [], "flow_out_top": [],
        "global": {"signal": {"overall": "中性", "tip": "t", "signals": [{"level": "中性", "text": "x"}]},
                   "items": [{"name": "纳斯达克", "price": 18000, "pct": 0.4}]},
        "news": {"hot_words": [{"word": "机器人", "count": 9}],
                 "important": [{"source": "财联社", "title": "标题"}], "latest": [], "sources_ok": []},
        "lhb": {"top_net": [], "game_stocks": [{"code": "600000", "name": "甲", "pct": 10.0,
                                                "fund_yi": 1.2, "why": ["顶级游资"]}],
                "seat_rank": [{"dept": "某营业部", "net_yi": 1.1}]},
        "picks": {"first_board": [{"name": "甲", "code": "600000", "score": 88}],
                  "relay": [{"name": "乙", "code": "600001", "days_board": "2天2板"}],
                  "risk": [{"name": "丙", "code": "600002", "risk": "炸板"}]},
        "action_plan": [{"step": "0. 数据体检", "detail": "数据完整"}],
        "note": "",
        "sources": {},
    }
    p.update(over)
    return p


class MarkdownTests(unittest.TestCase):
    def setUp(self):
        self.md = R.to_markdown(_payload())

    def test_renders_without_error(self):
        self.assertIn("# A股复盘报告 · 2026-10-23", self.md)

    def test_evidence_section_is_present(self):
        self.assertIn("## 二、结论证据与验证边界", self.md)
        self.assertIn("冻结 42 日 / 结算 37 日", self.md)
        self.assertIn("次一交易日**开盘价**", self.md)
        self.assertIn("0.702%", self.md)
        self.assertIn("sz399303", self.md)

    def test_validation_state_is_shown_as_unverified(self):
        self.assertIn("**未验证**", self.md)
        self.assertIn("连续结算 ≥60 日", self.md)
        self.assertNotIn("已验证历史回测", self.md)

    def test_composite_score_carries_perturbation_band(self):
        self.assertIn("±20.0% 参数扰动区间 61.0–74.9", self.md)

    def test_tradable_premium_is_the_headline_and_close_based_is_demoted(self):
        self.assertIn("昨涨停可成交溢价（评分口径）1.2%", self.md)
        self.assertIn("样本 41/52", self.md)
        self.assertIn("95% 区间 [-0.4, 2.8]", self.md)
        self.assertIn("买不到）比例 21.2%", self.md)
        self.assertIn("不参与评分", self.md)

    def test_factor_independence_is_reported(self):
        self.assertIn("2.1 / 名义 7", self.md)
        self.assertIn("伪精度", self.md)

    def test_reconcile_summary_is_reported(self):
        self.assertIn("两条独立路径一致", self.md)

    def test_score_band_and_confidence_row(self):
        self.assertIn("参数扰动区间 **64.1–76.2**", self.md)
        self.assertIn("| 情绪因子 | 数值 | 得分 | 权重 | 置信 |", self.md)

    def test_footer_states_reproduction_recipe(self):
        self.assertIn(str(params.STATS["seed"]), self.md)
        self.assertIn("deadbeef1234", self.md)

    def test_low_confidence_factors_are_flagged_when_present(self):
        md = R.to_markdown(_payload(sentiment={**_payload()["sentiment"],
                                               "low_confidence_factors": ["tradable_premium"]}))
        self.assertIn("低置信因子", md)

    def test_unstable_param_digest_is_flagged(self):
        rs = {**_payload()["research_status"], "params_stable": False}
        md = R.to_markdown(_payload(research_status=rs))
        self.assertIn("多个参数指纹", md)

    def test_missing_optional_blocks_do_not_crash(self):
        """字段缺失时报告应降级而不是抛异常——否则定时任务会整份报告失败。"""
        p = _payload(reconcile={}, research_status={})
        p["sentiment"] = {**p["sentiment"], "score_band": {}, "factor_independence": {},
                          "prev_premium_detail": {}}
        md = R.to_markdown(p)
        self.assertIn("## 二、结论证据与验证边界", md)


if __name__ == "__main__":
    unittest.main()
