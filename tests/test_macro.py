"""宏观水位：分位算法、ERP 对齐、温度分的缺失处理、各数据源解析器、端到端降级。

这里验证的是"尺子本身"——分位怎么算、缺数据时会不会被当成 0、
所有源都挂掉时会不会偷偷用样例数据顶上。不验证温度分能否择时。
"""
import asyncio
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _bootstrap  # noqa: F401,E402

from app.core import cache, store  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.services import macro  # noqa: E402
from app.sources import csindex, danjuan, sse  # noqa: E402
from app.sources import eastmoney as em  # noqa: E402


class PercentileTests(unittest.TestCase):
    def test_rank_is_share_of_values_not_above(self):
        vals = list(range(1, 101))            # 1..100
        self.assertEqual(macro.percentile_rank(vals, 25, min_n=10), 25.0)
        self.assertEqual(macro.percentile_rank(vals, 100, min_n=10), 100.0)
        self.assertEqual(macro.percentile_rank(vals, 0, min_n=10), 0.0)

    def test_small_sample_returns_none(self):
        """样本不足时宁可不给分位，也不给一个看起来精确的数。"""
        self.assertIsNone(macro.percentile_rank([1, 2, 3], 2, min_n=10))

    def test_none_values_are_ignored(self):
        self.assertEqual(macro.percentile_rank([None, 1, 2, None, 3, 4], 2, min_n=4), 50.0)

    def test_quantile_interpolates(self):
        self.assertEqual(macro.quantile([0, 10], 0.5), 5.0)
        self.assertIsNone(macro.quantile([], 0.5))


class ErpAlignTests(unittest.TestCase):
    def test_erp_uses_latest_prior_yield_within_gap(self):
        pe = [["2026-01-05", 10.0], ["2026-01-06", 12.5]]
        ys = [{"date": "2026-01-02", "cn10y": 2.0}, {"date": "2026-01-05", "cn10y": 1.8}]
        rows = macro.align_erp(pe, ys, max_gap_days=7)
        # 1/10 = 10% − 1.8% = 8.2；1/12.5 = 8% − 1.8%（沿用 01-05 的利率）= 6.2
        self.assertEqual([r[1] for r in rows], [8.2, 6.2])

    def test_stale_yield_is_not_matched(self):
        """一个月前的利率不能拿来算今天的 ERP。"""
        pe = [["2026-03-01", 10.0]]
        ys = [{"date": "2026-01-01", "cn10y": 2.0}]
        self.assertEqual(macro.align_erp(pe, ys, max_gap_days=7), [])

    def test_missing_yield_values_skipped(self):
        pe = [["2026-01-06", 10.0]]
        ys = [{"date": "2026-01-05", "cn10y": 2.0}, {"date": "2026-01-06", "cn10y": None}]
        self.assertEqual(macro.align_erp(pe, ys)[0][3], 2.0)


class TemperatureTests(unittest.TestCase):
    def test_missing_components_are_excluded_not_zero(self):
        comps = [{"name": "a", "heat": 80}, {"name": "b", "heat": 60}, {"name": "c", "heat": 70},
                 {"name": "d", "heat": None}]
        t = macro.temperature(comps)
        self.assertEqual(t["score"], 70.0)
        self.assertEqual(t["used"], 3)
        self.assertEqual(t["missing"], ["d"])

    def test_too_few_components_gives_no_score(self):
        t = macro.temperature([{"name": "a", "heat": 90}, {"name": "b", "heat": None}])
        self.assertIsNone(t["score"])
        self.assertEqual(t["label"], "数据不足")

    def test_split_needs_both_sides_for_total(self):
        """只取到估值分时不能合成总分，否则等于把一边冒充成全貌。"""
        comps = [{"name": "a", "group": "valuation", "heat": 20}, {"name": "b", "group": "valuation", "heat": 40},
                 {"name": "c", "group": "flow", "heat": 90}, {"name": "d", "group": "flow", "heat": None}]
        t = macro.split_temperature(comps)
        self.assertEqual(t["valuation"]["score"], 30.0)
        self.assertIsNone(t["flow"]["score"])           # 资金分只有 1 项，不足 2 项
        self.assertIsNone(t["score"])
        self.assertEqual(t["label"], "数据不足")

    def test_split_flags_estimated_turnover(self):
        comps = [{"name": "a", "group": "valuation", "heat": 50}, {"name": "b", "group": "valuation", "heat": 50},
                 {"name": "c", "group": "flow", "heat": 80, "estimated": True}, {"name": "d", "group": "flow", "heat": 60}]
        t = macro.split_temperature(comps)
        self.assertEqual(t["score"], 60.0)
        self.assertTrue(t["flow"]["estimated"])

    def test_bands(self):
        self.assertEqual(macro.band_of(10)["label"], "冰点")
        self.assertEqual(macro.band_of(50)["label"], "中性")
        self.assertEqual(macro.band_of(100)["label"], "过热")


class EtfChangeTests(unittest.TestCase):
    def test_group_sums_only_codes_present_on_both_dates(self):
        latest = {"510300": {"shares_yi": 110.0}, "510310": {"shares_yi": 50.0}}
        lagged = {1: {"510300": {"shares_yi": 100.0}}}      # 510310 前一日缺数据
        out = macro.etf_changes(latest, lagged)
        g = next(x for x in out["groups"] if x["track"] == "沪深300")
        self.assertEqual(g["chg_1d"], 10.0)                  # 只算 510300，510310 不能当成从 0 涨到 50
        self.assertEqual(g["chg_1d_pct"], 10.0)
        r = next(x for x in out["items"] if x["code"] == "510310")
        self.assertIsNone(r["chg_1d"])


class ParserTests(unittest.TestCase):
    def test_csindex_perf(self):
        payload = {"code": "200", "data": [
            {"tradeDate": "20261030", "close": 4000.1, "peg": 13.2},
            {"tradeDate": "20261029", "close": 3990.0, "peg": 13.1},
            {"tradeDate": "20261028", "close": 3980.0, "peg": None},
        ]}
        rows = csindex.parse_index_perf(payload)
        self.assertEqual(rows, [["2026-10-29", 3990.0, 13.1], ["2026-10-30", 4000.1, 13.2]])

    def test_csindex_renamed_field_raises(self):
        """字段改名必须报错，让链路切到备用源，而不是返回空列表装作没数据。"""
        with self.assertRaises(csindex.CsindexParseError):
            csindex.parse_index_perf({"data": [{"tradeDate": "20261030", "close": 1.0}]})

    def test_danjuan(self):
        payload = {"data": {"items": [{"index_code": "SH000922", "name": "中证红利", "pe": 7.5, "pb": 0.8,
                                        "yeild": 0.0541, "roe": 0.11, "ts": 1761868800000}]}}
        snap = danjuan.parse_eva_list(payload)
        self.assertEqual(snap["SH000922"]["dividend_yield"], 5.41)
        hist = danjuan.parse_history({"data": {"index_eva_pb_growths": [
            {"pb": 1.3, "ts": 1761868800000}, {"pb": 0, "ts": 1761782400000}]}}, "pb")
        self.assertEqual(len(hist), 1)        # PB 为 0 的点被剔除

    def test_dividend_yield_normalization(self):
        self.assertEqual(danjuan.normalize_yield(5.2), 5.2)
        self.assertEqual(danjuan.normalize_yield(0.052), 5.2)
        self.assertIsNone(danjuan.normalize_yield("--"))

    def test_treasury_keeps_none(self):
        rows = em.parse_treasury([{"SOLAR_DATE": "2026-10-30 00:00:00", "EMM00166466": 1.75, "EMG00001310": None}])
        self.assertEqual(rows[0]["cn10y"], 1.75)
        self.assertIsNone(rows[0]["us10y"])

    def test_sse_etf_units(self):
        snap = sse.parse_etf_scale({"result": [{"SEC_CODE": "510300", "SEC_NAME": "沪深300ETF",
                                                "STAT_DATE": "2026-10-30", "TOT_VOL": "4567890.12"}]})
        self.assertAlmostEqual(snap["510300"]["shares_yi"], 456.789, places=3)   # 万份 → 亿份


class FuturesPositionTests(unittest.TestCase):
    CSV = "\n".join([
        "交易日,合约,排名,成交量排名,,,持买单量排名,,,持卖单量排名,,",
        ",,,会员简称,成交量,比上交易日增减,会员简称,持买单量,比上交易日增减,会员简称,持卖单量,比上交易日增减",
        "20261030,IF2511,1,中信期货,9000,100,中信期货,20000,500,中信期货,30000,1500",
        "20261030,IF2511,2,国泰君安,8000,-50,国泰君安,10000,-200,海通期货,12000,300",
        "20261030,IF2512,1,中信期货,3000,20,中信期货,5000,100,中信期货,8000,-400",
        "20261030,IF2512,2,海通期货,1000,10,海通期货,2000,--,国泰君安,1000,0",
        "合计,,,,,,,,,,,",
    ])

    def test_parse_skips_headers_and_totals(self):
        from app.sources import cffex
        rows = cffex.parse_rank_csv(self.CSV)
        self.assertEqual(len(rows), 4)
        self.assertEqual(rows[0]["contract"], "IF2511")
        self.assertEqual(rows[0]["short"], 30000)
        self.assertIsNone(rows[3]["long_chg"])          # "--" 是缺失，不是 0

    def test_aggregate_sums_member_across_contracts(self):
        from app.sources import cffex
        agg = macro.aggregate_positions(cffex.parse_rank_csv(self.CSV))
        citic = next(m for m in agg["members"] if m["name"] == "中信期货")
        self.assertEqual(citic["long"], 25000)
        self.assertEqual(citic["short"], 38000)
        self.assertEqual(citic["net"], -13000)
        self.assertEqual(citic["net_chg"], 600 - 1100)  # 多单 +600，空单 +1100
        self.assertEqual(agg["long"], 37000)
        self.assertEqual(agg["contracts"], ["IF2511", "IF2512"])
        self.assertEqual(agg["members"][0]["name"], "中信期货")   # 按净持仓绝对值排序


class OverviewTests(unittest.TestCase):
    def setUp(self):
        self._offline, self._retries = settings.offline, settings.max_retries
        settings.max_retries = 0
        cache.cache_clear()

    def tearDown(self):
        settings.offline, settings.max_retries = self._offline, self._retries
        cache.cache_clear()

    def test_offline_overview_is_complete(self):
        settings.offline = True
        res = asyncio.run(macro.overview(force=True))
        t = res["temperature"]
        self.assertIsNotNone(t["score"])
        self.assertEqual(t["score"], round((t["valuation"]["score"] + t["flow"]["score"]) / 2, 1))
        self.assertEqual(t["valuation"]["used"], 3)
        self.assertTrue(all(v in ("mock", None) or "mock" in str(v) for v in res["meta"]["sources"].values()))
        self.assertIsNotNone(res["erp"]["erp_pct"])
        self.assertTrue(res["etf"]["items"])
        fut = res["futures"]["varieties"]
        self.assertEqual([v["code"] for v in fut], ["IF", "IH", "IC", "IM"])
        self.assertEqual(len(fut[0]["history"]), macro.MACRO_PARAMS["futures_days"])
        # 离线样例不能落库，否则会污染温度历史曲线
        self.assertEqual(store.load_macro_history(10), [])

    def test_all_sources_down_reports_gaps_without_mock(self):
        """在线模式下所有源都失败：必须返回缺失 + 缺口说明，绝不能拿样例数据顶上。"""
        settings.offline = False
        res = asyncio.run(macro.overview(force=True))
        self.assertIsNone(res["temperature"]["score"])
        self.assertTrue(res["gaps"])
        self.assertNotIn("mock", res["meta"]["sources"].values())
        self.assertIsNone(res["valuation"][0]["pe"])

    def test_store_roundtrip(self):
        store.save_macro("20261030", {"score": 42.0})
        store.save_macro("2026-10-30", {"score": 43.0})     # 同一天两种写法 → 同一行
        rows = [r for r in store.load_macro_history(10) if r["trade_date"] == "2026-10-30"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["score"], 43.0)


if __name__ == "__main__":
    unittest.main()
