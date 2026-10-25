"""参数指纹与涨跌幅制度表：这些是"算得对"的前提，错了全部下游都错。"""
import unittest

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _bootstrap  # noqa: F401,E402  必须在任何 app.* 导入之前执行

from app.core import params, regime


class ParamDigestTests(unittest.TestCase):
    def test_digest_is_deterministic(self):
        """同一组参数必须永远得到同一指纹，否则无法证明"当时用的是这组参数"。"""
        self.assertEqual(params.digest(), params.digest())
        self.assertEqual(len(params.digest()), 12)

    def test_digest_changes_when_a_threshold_changes(self):
        snap = params.snapshot()
        before = params.digest(snap)
        snap["sentiment"]["limit_up"]["scale"] = 91.0
        self.assertNotEqual(before, params.digest(snap))

    def test_perturbed_weights_still_normalised(self):
        for f in (0.5, 0.8, 1.0, 1.2, 2.0):
            w = [v["weight"] for v in params.perturbed(f)["sentiment"].values()]
            self.assertAlmostEqual(sum(w), 1.0, places=9, msg=f"factor={f}")
            self.assertTrue(all(x > 0 for x in w))

    def test_perturb_weights_helper_normalises(self):
        out = params.perturb_weights(params.COMPOSITE, 1.3)
        self.assertAlmostEqual(sum(out.values()), 1.0, places=9)
        self.assertEqual(set(out), set(params.COMPOSITE))

    def test_snapshot_is_a_copy(self):
        snap = params.snapshot()
        snap["sentiment"]["limit_up"]["weight"] = 0.99
        self.assertNotEqual(params.SENTIMENT["limit_up"]["weight"], 0.99)


class RegimeTests(unittest.TestCase):
    def test_chinext_limit_changed_in_2020(self):
        """创业板 2020-08-24 由 10% 改 20%：跨该日的回测必须分段，否则涨停判定错。"""
        self.assertEqual(regime.limit_pct("300001", "2020-08-21")["pct"], 10.0)
        self.assertEqual(regime.limit_pct("300001", "2020-08-24")["pct"], 20.0)

    def test_board_detection(self):
        cases = {"600519": "main_sh", "000001": "main_sz", "300750": "chinext",
                 "688111": "star", "920001": "bse", "123456": "unknown"}
        for code, board in cases.items():
            self.assertEqual(regime.board_of(code), board, code)

    def test_unknown_board_never_defaults_to_ten_percent(self):
        """无法归板时必须返回 None。退回默认 10% 就是制造静默错误。"""
        self.assertIsNone(regime.limit_pct("123456", "2026-10-23")["pct"])

    def test_st_uses_five_percent_on_main_board(self):
        self.assertEqual(regime.limit_pct("600519", "2026-10-23", is_st=True)["pct"], 5.0)
        # 创业板 ST 仍是 20%
        self.assertEqual(regime.limit_pct("300001", "2026-10-23", is_st=True)["pct"], 20.0)

    def test_new_listing_has_no_limit(self):
        r = regime.limit_pct("301999", "2026-10-23", listed_days=3)
        self.assertIsNone(r["pct"])
        self.assertIn("不设涨跌幅", r["reason"])

    def test_limit_up_price_respects_board(self):
        """同样 +20%：创业板算封板，主板不算。混用口径就会在这里出错。"""
        self.assertTrue(regime.is_limit_up_price(12.0, 10.0, "300001", "2026-10-23")["matched"])
        self.assertFalse(regime.is_limit_up_price(12.0, 10.0, "600519", "2026-10-23")["matched"])
        self.assertTrue(regime.is_limit_up_price(11.0, 10.0, "600519", "2026-10-23")["matched"])

    def test_limit_up_price_unknown_is_none_not_false(self):
        """口径不确定必须是 None（不计入分母），不能当成 False（判定为没封住）。"""
        self.assertIsNone(regime.is_limit_up_price(11.0, 10.0, "123456", "2026-10-23")["matched"])

    def test_caliber_events_are_listed_in_range(self):
        dates = [e["date"] for e in regime.caveats_for("2020-01-01", "2025-01-01")]
        self.assertIn("2020-08-24", dates)
        self.assertIn("2024-08-19", dates)
        self.assertNotIn("2019-07-22", dates)


if __name__ == "__main__":
    unittest.main()
