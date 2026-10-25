"""统计检验层：检验"检验工具本身"是否可信。

这组测试的价值在于：如果置换检验在"规则毫无能力"的构造数据上也报显著，
那么它给出的任何 p 值都不能用。先验证尺子，再用尺子量东西。
"""
import random
import unittest
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _bootstrap  # noqa: F401,E402

from app.services import validate as V  # noqa: E402


class DescribeTests(unittest.TestCase):
    def test_small_sample_is_not_reportable(self):
        """9 个样本的均值不许当结论——这是对"平均溢价 6.1%"式结论的硬拦截。"""
        r = V.describe([1, 2, 3, 20, -5, 7, 8, 2, 1])
        self.assertEqual(r["n"], 9)
        self.assertFalse(r["reportable"])
        self.assertIn("样本量", r["note"])

    def test_large_sample_is_reportable(self):
        r = V.describe([1.0] * 40)
        self.assertTrue(r["reportable"])
        self.assertEqual(r["median"], 1.0)

    def test_dirty_values_are_dropped(self):
        r = V.describe([1.0, None, "x", float("nan"), float("inf"), 3.0])
        self.assertEqual(r["n"], 2)

    def test_bootstrap_ci_is_deterministic_and_brackets_point(self):
        rnd = random.Random(1)
        vals = [rnd.gauss(0, 1) for _ in range(50)]
        a = V.bootstrap_ci(vals)
        b = V.bootstrap_ci(vals)
        self.assertEqual(a, b)  # 固定种子 → 第三方能复算出同一区间
        self.assertLessEqual(a["lo"], a["point"])
        self.assertLessEqual(a["point"], a["hi"])

    def test_empty_sample_is_safe(self):
        r = V.describe([])
        self.assertEqual(r["n"], 0)
        self.assertFalse(r["reportable"])


class PermutationTests(unittest.TestCase):
    def _days(self, picker, days=30, seed=11):
        rnd = random.Random(seed)
        out = []
        for _ in range(days):
            base = rnd.gauss(0, 3)                      # 当天普涨/普跌
            uni = [base + rnd.gauss(0, 4) for _ in range(40)]
            out.append({"selected": picker(uni, rnd), "universe": uni})
        return out

    def test_no_skill_is_not_significant(self):
        """零假设成立时 p 必须不显著。这一条失败则整套统计不可用。"""
        groups = self._days(lambda uni, rnd: rnd.sample(uni, 8))
        r = V.stratified_permutation_test(groups)
        self.assertIsNotNone(r["p_value"])
        self.assertGreater(r["p_value"], 0.05)

    def test_real_skill_is_detected(self):
        groups = self._days(lambda uni, rnd: sorted(uni)[-8:])
        r = V.stratified_permutation_test(groups)
        self.assertLess(r["p_value"], 0.01)
        self.assertGreater(r["effect_size"], 2)

    def test_day_effect_alone_does_not_create_significance(self):
        """关键反例：每天都"全选"（无排序能力），只是日期波动大。

        如果实现把所有天混在一起置换，普涨日会被拿去和普跌日比较，
        这里就会凭空出现显著性。分层实现必须给出 p 接近 1。
        """
        rnd = random.Random(5)
        groups = []
        for _ in range(30):
            base = rnd.gauss(0, 8)
            uni = [base + rnd.gauss(0, 2) for _ in range(20)]
            groups.append({"selected": uni[:19], "universe": uni})
        r = V.stratified_permutation_test(groups)
        self.assertGreater(r["p_value"], 0.05)

    def test_p_value_never_zero(self):
        """p=0 是不可能的结论；必须用 (hits+1)/(iters+1) 平滑。"""
        groups = self._days(lambda uni, rnd: sorted(uni)[-8:])
        self.assertGreater(V.stratified_permutation_test(groups)["p_value"], 0)

    def test_insufficient_days_returns_none(self):
        r = V.stratified_permutation_test([{"selected": [1], "universe": [1, 2, 3]}])
        self.assertIsNone(r["p_value"])

    def test_single_day_permutation_reports_effect(self):
        rnd = random.Random(2)
        uni = [rnd.gauss(0, 5) for _ in range(80)]
        r = V.permutation_test(sorted(uni)[-10:], uni)
        self.assertLess(r["p_value"], 0.05)
        self.assertGreater(r["excess_vs_universe"], 0)


class MultipleTestingTests(unittest.TestCase):
    def test_bh_inflates_p_values(self):
        r = V.benjamini_hochberg([0.01, 0.02, 0.03, 0.2, 0.9])
        self.assertTrue(all(a >= p for a, p in zip(r["adjusted"], [0.01, 0.02, 0.03, 0.2, 0.9])))

    def test_bh_is_monotone(self):
        ps = [0.001, 0.01, 0.04, 0.05, 0.3, 0.8]
        adj = V.benjamini_hochberg(ps)["adjusted"]
        self.assertEqual(adj, sorted(adj))

    def test_lone_marginal_p_does_not_survive_16_tests(self):
        """16 次检验里出现一个 p=0.04 是预期中的噪音，BH 后不应算发现。"""
        ps = [0.04] + [0.5] * 15
        r = V.benjamini_hochberg(ps)
        self.assertEqual(r["rejected"], [])


class FactorIndependenceTests(unittest.TestCase):
    def test_collinear_factors_collapse(self):
        """三个几乎同向的因子，有效自由度必须明显小于名义个数。"""
        rnd = random.Random(4)
        x = [rnd.gauss(0, 1) for _ in range(60)]
        series = {"a": x, "b": [v + rnd.gauss(0, 0.05) for v in x],
                  "c": [-v + rnd.gauss(0, 0.05) for v in x]}
        r = V.factor_independence(series)
        self.assertLess(r["effective_factors"], 1.6)
        self.assertEqual(r["nominal_factors"], 3)

    def test_independent_factors_stay_independent(self):
        rnd = random.Random(6)
        series = {k: [rnd.gauss(0, 1) for _ in range(200)] for k in "abcd"}
        r = V.factor_independence(series)
        self.assertGreater(r["effective_factors"], 3.0)

    def test_insufficient_series_is_reported_not_guessed(self):
        r = V.factor_independence({"a": [1, 2, 3]})
        self.assertIsNone(r["effective_factors"])


class QuintileTests(unittest.TestCase):
    def test_monotonic_when_score_predicts(self):
        rnd = random.Random(8)
        pairs = [(i, i * 0.1 + rnd.gauss(0, 0.3)) for i in range(100)]
        r = V.quintile_spread(pairs)
        self.assertTrue(r["monotonic"])
        self.assertGreater(r["spread_top_minus_bottom"], 0)

    def test_not_monotonic_when_score_is_noise(self):
        rnd = random.Random(9)
        pairs = [(rnd.random(), rnd.gauss(0, 1)) for _ in range(100)]
        self.assertFalse(V.quintile_spread(pairs)["monotonic"])

    def test_too_few_samples_refuses(self):
        self.assertIsNone(V.quintile_spread([(1, 1), (2, 2)])["monotonic"])


class ExcessTests(unittest.TestCase):
    def test_excess_subtracts_baseline_pairwise(self):
        self.assertEqual(V.excess_returns([5.0, 2.0], [3.0, 3.0]), [2.0, -1.0])

    def test_missing_baseline_yields_none_not_raw_return(self):
        """基准缺失时必须返回 None，不能悄悄把毛收益当超额。"""
        self.assertEqual(V.excess_returns([5.0], [None]), [None])


class PValueUniformityTests(unittest.TestCase):
    def test_uniform_pvalues_do_not_deviate(self):
        rnd = random.Random(12)
        r = V.uniformity_of_pvalues([rnd.random() for _ in range(60)])
        self.assertFalse(r["deviates_from_uniform"])

    def test_left_skewed_pvalues_deviate(self):
        rnd = random.Random(13)
        r = V.uniformity_of_pvalues([rnd.random() * 0.15 for _ in range(60)])
        self.assertTrue(r["deviates_from_uniform"])
        self.assertTrue(r["left_skewed"])


if __name__ == "__main__":
    unittest.main()
