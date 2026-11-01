"""数据完整性守卫：样例数据和"全部源失败时算出的假分"绝不能写进历史。

账本、情绪历史、报告快照都是事后无法重建的数据。这里的每一条测试都对应一个
真实出现过的污染路径，修之前都会失败。
"""
import asyncio
import datetime as dt
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _bootstrap  # noqa: F401,E402

from app.core import cache, store  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.core.utils import holiday_coverage, last_trade_day  # noqa: E402
from app.services import globalmarket, news, report, sentiment, track  # noqa: E402


class _Mode(unittest.TestCase):
    def setUp(self):
        self._offline, self._retries = settings.offline, settings.max_retries
        settings.max_retries = 0
        cache.cache_clear()

    def tearDown(self):
        settings.offline, settings.max_retries = self._offline, self._retries
        cache.cache_clear()


class OfflineNeverWritesTests(_Mode):
    def test_ledger_refuses_offline(self):
        settings.offline = True
        d = str(last_trade_day(dt.date.today() - dt.timedelta(days=3)))
        res = asyncio.run(track.freeze(d))
        self.assertFalse(res["ok"])
        self.assertEqual(store.load_signals(d), [])
        self.assertFalse(asyncio.run(track.settle())["ok"])

    def test_report_snapshot_not_saved_offline(self):
        settings.offline = True
        self.assertFalse(report._may_save_snapshot("2026-10-30", {"data_quality": {"decision_enabled": True}}))

    def test_offline_news_shows_samples(self):
        """离线演示模式下快讯页不能是空白。"""
        settings.offline = True
        self.assertTrue(asyncio.run(news.feed(20, force=True))["items"])


class OnlineFailureTests(_Mode):
    def test_failed_sentiment_is_not_saved(self):
        """所有源失败时按 0 家涨停算出的分数不能落库，否则会覆盖当天真实记录。"""
        settings.offline = False
        before = len(store.load_sentiment_history(500))
        with _bootstrap.sources_down():
            res = asyncio.run(sentiment.core(force=True))
        self.assertFalse(res["data_quality"]["saved"])
        self.assertEqual(len(store.load_sentiment_history(500)), before)

    def test_news_does_not_fall_back_to_samples(self):
        settings.offline = False
        with _bootstrap.sources_down():
            self.assertEqual(asyncio.run(news.feed(20, force=True))["items"], [])

    def test_global_does_not_fill_sample_prices(self):
        settings.offline = False
        with _bootstrap.sources_down():
            items = asyncio.run(globalmarket.overview(force=True)).get("items") or []
        self.assertFalse([i for i in items if i.get("source") == "mock"])

    def test_good_snapshot_not_overwritten_by_blocked_one(self):
        settings.offline = False
        store.save_snapshot("2026-10-29", {"data_quality": {"decision_enabled": True}})
        self.assertFalse(report._may_save_snapshot("2026-10-29", {"data_quality": {"decision_enabled": False}}))
        self.assertTrue(report._may_save_snapshot("2026-10-29", {"data_quality": {"decision_enabled": True}}))
        self.assertTrue(report._may_save_snapshot("2026-10-28", {"data_quality": {"decision_enabled": False}}))


class SentimentHistoryDedupTests(unittest.TestCase):
    def test_mixed_date_formats_collapse_to_latest(self):
        c = store.conn()
        c.execute("INSERT OR REPLACE INTO sentiment_daily VALUES('20250103','{\"score\":1}','2025-01-03 15:10:00')")
        c.execute("INSERT OR REPLACE INTO sentiment_daily VALUES('2025-01-03','{\"score\":2}','2025-01-03 21:00:00')")
        c.commit()
        rows = [r for r in store.load_sentiment_history(1000) if r["trade_date"] == "2025-01-03"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["score"], 2)


class CatchUpTests(unittest.TestCase):
    def _run(self, when):
        from app.core import scheduler
        calls = []
        orig = (scheduler.now_cn, scheduler.job_close, scheduler.job_ledger, scheduler.job_macro)

        async def rec(name):
            calls.append(name)
        scheduler.now_cn = lambda: when
        scheduler.job_close = lambda: rec("close")
        scheduler.job_ledger = lambda: rec("ledger")
        scheduler.job_macro = lambda: rec("macro")
        try:
            asyncio.run(scheduler.catch_up())
        finally:
            scheduler.now_cn, scheduler.job_close, scheduler.job_ledger, scheduler.job_macro = orig
        return calls

    def test_evening_start_runs_missed_jobs(self):
        from app.core.utils import CN_TZ
        self.assertEqual(self._run(dt.datetime(2026, 11, 2, 21, 30, tzinfo=CN_TZ)), ["close", "ledger", "macro"])

    def test_no_catch_up_before_close_or_on_holiday(self):
        from app.core.utils import CN_TZ
        self.assertEqual(self._run(dt.datetime(2026, 11, 2, 10, 0, tzinfo=CN_TZ)), [])
        self.assertEqual(self._run(dt.datetime(2026, 10, 1, 21, 0, tzinfo=CN_TZ)), [])   # 国庆


class HolidayCoverageTests(unittest.TestCase):
    def test_missing_year_is_reported(self):
        cov = holiday_coverage(dt.date(2099, 3, 1))
        self.assertFalse(cov["ok"])
        self.assertIn(2099, cov["missing"])

    def test_december_also_requires_next_year(self):
        years = holiday_coverage()["years"]
        last = max(years)
        self.assertIn(last + 1, holiday_coverage(dt.date(last, 12, 5))["missing"])
        self.assertTrue(holiday_coverage(dt.date(last, 6, 1))["ok"])


if __name__ == "__main__":
    unittest.main()
