"""结果账本的端到端测试，以及前视偏差（look-ahead）守卫。

为什么这组测试比任何文档都重要：
"不使用未来信息"这件事无法靠自觉保证——它是一行代码就能破坏、而且破坏后
结果会变得更好看的性质。所以必须把它写成断言：入场价必须来自候选日**之后**
的那根 K 线，一旦有人改成候选日收盘价，这里立刻红。
"""
import datetime as dt
import random
import unittest
from unittest import mock
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _bootstrap  # noqa: F401,E402

from app.core import cache, store, utils  # noqa: E402
from app.services import track  # noqa: E402

BASE = dt.date(2026, 10, 23)
DAYS = [utils.prev_trade_day(BASE, n).isoformat() for n in range(94, 0, -1)] + [BASE.isoformat()]
CAND_DATES = DAYS[:70]            # 作为候选日的那些交易日（要超过 MIN_DAYS_EVIDENCE）
N_CODES = 40
CODES = [f"60{i:04d}" for i in range(N_CODES)]
SEALED_CODES = set(CODES[:3])     # 这几只每天开盘就一字封死，应判为买不到
BENCH = track.PRIMARY_BENCHMARK


def _series(code: str, skill: bool, rnd: random.Random) -> list[list]:
    """构造一只票的日线。

    skill=True 时，代码序号越小（我们让评分也越高）次日收益越好，
    于是排序能力是真实存在的，record() 应当检测到；
    skill=False 时收益与序号无关，record() 必须报不显著。
    """
    rows = []
    close = 10.0
    idx = CODES.index(code)
    edge = (N_CODES - idx) / N_CODES * 3.0 if skill else 0.0
    for d in DAYS:
        prev = close
        if code in SEALED_CODES:
            op = round(prev * 1.10, 2)          # 开盘即涨停价
            close = op
        else:
            # 刻意保证开盘价恒不等于前收盘：这样"入场价不是候选日收盘价"
            # 这件事可以被值相等性直接断言，而不是靠巧合。
            op = round(prev * (1.005 + abs(rnd.gauss(0, 0.004))), 2)
            close = round(op * (1 + (edge + rnd.gauss(0, 2.0)) / 100), 2)
        rows.append([d, op, close, max(op, close), min(op, close), 1e6, 1e8])
    return rows


class LedgerEndToEndTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import asyncio
        cache.cache_clear()
        rnd = random.Random(42)
        cls.kl = {"skill": {}, "null": {}}
        for mode, skill in (("skill", True), ("null", False)):
            for c in CODES:
                cls.kl[mode][c] = _series(c, skill, rnd)
        # 基准：一条带日期波动的指数，用来检验"超额 = 收益 - 同期基准"
        bench, close = [], 1000.0
        for d in DAYS:
            op = round(close * (1 + rnd.gauss(0, 0.004)), 2)
            close = round(op * (1 + rnd.gauss(0, 0.8) / 100), 2)
            bench.append([d, op, close, op, op, 1e6, 1e8])
        cls.bench = bench
        inst = cls()
        # 两套世界各建一次账本：skill=评分真有排序能力，null=评分是噪音
        cls.settle_skill = asyncio.run(inst._build("t_skill", "skill"))
        cls.settle_null = asyncio.run(inst._build("t_null", "null"))

    def _kline_stub(self, mode):
        async def kline(symbol="sh000001", days=120, force=False):
            code = str(symbol).replace("sh", "").replace("sz", "")
            if str(symbol) == BENCH or code == BENCH.replace("sz", ""):
                return cache.Sourced(data=self.bench, source="test")
            return cache.Sourced(data=self.kl[mode].get(code) or [], source="test")
        return kline

    def _screener_stub(self, strategy_name):
        async def run(strategy="first_board", date=None, include_universe=False):
            rnd = random.Random(hash(date) & 0xFFFF)
            uni = [{"code": c, "name": f"票{c}", "score": round(100 - CODES.index(c) * 2
                                                                + rnd.gauss(0, 1), 1)}
                   for c in CODES]
            uni.sort(key=lambda x: -x["score"])
            return {"strategy": strategy, "items": uni[:30], "universe": uni,
                    "universe_size": len(uni), "track_top_n": 8, "note": ""}
        return run

    async def _build(self, strategy_name, mode):
        with mock.patch("app.services.screener.run", self._screener_stub(strategy_name)):
            for d in CAND_DATES:
                res = await track.freeze(d, strategies=(strategy_name,))
                self.assertTrue(res["ok"], res)
        with mock.patch("app.services.market.kline", self._kline_stub(mode)):
            # 限定策略：两套测试世界共用一个库，不限定会用后一套的价格覆盖前一套
            return await track.settle(max_dates=300, strategy=strategy_name)

    # ---------------- 前视偏差守卫 ----------------
    def test_entry_price_comes_from_the_day_after_the_signal(self):
        """入场价必须是候选日**次一**交易日的开盘价。

        这是最容易被破坏、破坏后收益最好看的地方：改用候选日收盘价，
        所有策略的"收益"都会凭空变好，因为那是收盘后才知道、却买不到的价格。
        """
        rows = store.load_outcomes("t_skill", 1)
        self.assertTrue(rows)
        for r in rows[:120]:
            i = DAYS.index(r["trade_date"])
            self.assertEqual(r["entry_date"], DAYS[i + 1],
                             "入场日必须晚于候选日一个交易日")
            self.assertNotEqual(r["entry_date"], r["trade_date"])
            expected_open = self.kl["skill"][r["code"]][i + 1][1]
            self.assertAlmostEqual(r["entry_price"], expected_open, places=4)
            # 绝不能等于候选日收盘价
            self.assertNotAlmostEqual(r["entry_price"],
                                      self.kl["skill"][r["code"]][i][2], places=6)

    def test_exit_date_matches_horizon(self):
        for h in (1, 2, 5, 10):
            rows = store.load_outcomes("t_skill", h)
            self.assertTrue(rows, f"horizon={h} 无结果")
            r = rows[0]
            i = DAYS.index(r["trade_date"])
            self.assertEqual(r["exit_date"], DAYS[i + h])

    def test_freeze_refuses_a_date_that_has_not_closed(self):
        """盘中/未来日期禁止冻结，否则冻进账本的是没定型的数据。"""
        import asyncio
        future = (dt.date.today() + dt.timedelta(days=30)).isoformat()
        res = asyncio.run(track.freeze(future, strategies=("t_future",)))
        self.assertFalse(res["ok"])
        self.assertEqual(res["frozen"], 0)
        self.assertEqual(store.load_signals(future, "t_future"), [])

    def test_frozen_at_is_not_rewritten_on_rerun(self):
        """重跑只更新内容，不改写首次冻结时间戳——否则"当时就记下了"无法自证。"""
        import asyncio

        async def go():
            with mock.patch("app.services.screener.run", self._screener_stub("t_frozen")):
                await track.freeze(CAND_DATES[0], strategies=("t_frozen",))
                first = store.load_signals(CAND_DATES[0], "t_frozen")[0]["frozen_at"]
                await track.freeze(CAND_DATES[0], strategies=("t_frozen",))
                second = store.load_signals(CAND_DATES[0], "t_frozen")[0]["frozen_at"]
                return first, second

        first, second = asyncio.run(go())
        self.assertEqual(first, second)

    # ---------------- 可成交性 ----------------
    def test_open_sealed_samples_are_marked_untradable(self):
        rows = store.load_outcomes("t_skill", 1)
        sealed = [r for r in rows if r["code"] in SEALED_CODES]
        self.assertTrue(sealed)
        self.assertTrue(all(r["tradable"] == 0 for r in sealed),
                        "开盘一字封死必须标为不可成交")
        self.assertTrue(all("封死" in (r["reason"] or "") for r in sealed))
        normal = [r for r in rows if r["code"] not in SEALED_CODES]
        self.assertTrue(all(r["tradable"] == 1 for r in normal))

    def test_record_excludes_untradable_by_default(self):
        rec = track.record("t_skill", 1, force=True)
        self.assertGreater(rec["untradable_rate"], 0)
        codes_used = {r["code"] for r in store.load_outcomes("t_skill", 1)
                      if r["tradable"] == 1}
        self.assertFalse(codes_used & SEALED_CODES)

    # ---------------- 成本与基准 ----------------
    def test_net_return_subtracts_round_trip_cost(self):
        r = store.load_outcomes("t_skill", 1)[0]
        self.assertAlmostEqual(r["ret_net_pct"], r["ret_pct"] - track.total_cost_pct(), places=3)
        self.assertGreater(track.total_cost_pct(), 0.5)  # 打板来回成本不可能低于 0.5%

    def test_excess_is_net_minus_benchmark(self):
        rows = [r for r in store.load_outcomes("t_skill", 1) if r["base_ret_pct"] is not None]
        self.assertTrue(rows)
        for r in rows[:30]:
            self.assertAlmostEqual(r["excess_pct"], r["ret_net_pct"] - r["base_ret_pct"], places=3)

    def test_benchmark_is_recorded_on_every_row(self):
        rows = store.load_outcomes("t_skill", 1)
        self.assertTrue(all(r["benchmark"] == BENCH for r in rows))

    # ---------------- 汇总结论 ----------------
    def test_record_detects_real_ranking_skill(self):
        rec = track.record("t_skill", 1, force=True)
        self.assertGreaterEqual(rec["days"], track.MIN_DAYS_EVIDENCE)
        self.assertEqual(rec["stage"], "signal_not_rejected")
        self.assertLess(rec["permutation"]["p_value"], 0.01)
        self.assertTrue(rec["quintile"]["monotonic"])

    def test_record_reports_no_evidence_when_scores_are_noise(self):
        """构造"评分与收益无关"的世界，汇总必须老实说没有证据。"""
        rec = track.record("t_null", 1, force=True)
        self.assertGreaterEqual(rec["days"], track.MIN_DAYS_EVIDENCE)
        self.assertEqual(rec["stage"], "no_evidence")
        self.assertGreater(rec["permutation"]["p_value"], 0.05)

    def test_status_never_claims_validated(self):
        st = track.status()
        self.assertFalse(st["validated"])
        self.assertIn("不会把状态置为", st["statement"])
        self.assertTrue(st["what_would_change_this"])

    def test_universe_rows_are_frozen_too(self):
        """未选中的标的也必须进账本，否则置换检验没有零分布可用。"""
        rows = store.load_signals(CAND_DATES[0], "t_skill")
        self.assertEqual(len(rows), N_CODES)
        self.assertEqual(len([r for r in rows if r["selected"]]), 8)

    def test_param_digest_is_stored_with_every_signal(self):
        from app.core import params
        rows = store.load_signals(CAND_DATES[0], "t_skill")
        self.assertTrue(all(r["param_digest"] == params.digest() for r in rows))


    def test_settle_declares_its_method(self):
        """结算口径必须写在返回值里，第三方不看代码也能知道怎么算的。"""
        m = self.settle_skill["method"]
        self.assertIn("开盘", m["entry"])
        self.assertIn("收盘", m["exit"])
        self.assertIn(BENCH, m["benchmark"])
        self.assertGreater(self.settle_skill["settled"], 0)


if __name__ == "__main__":
    unittest.main()
