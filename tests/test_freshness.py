"""新鲜度检测：区分"代码写错了"和"跑的是旧东西"。

这两种情况的症状一模一样——新接口 404、新字段永远是空。
症状相同而原因不同的时候，系统必须自己说清楚是哪一种，
否则人会一直去翻代码，而真正要做的只是重启或重新构建。
"""
import os
import time
import unittest
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _bootstrap  # noqa: F401,E402

from app.core import config  # noqa: E402


class BackendFreshnessTests(unittest.TestCase):
    TARGET = config.BASE_DIR / "app" / "core" / "utils.py"

    def setUp(self):
        self._orig = self.TARGET.stat()

    def tearDown(self):
        os.utime(self.TARGET, (self._orig.st_atime, self._orig.st_mtime))

    def test_fresh_process_is_not_stale(self):
        self.assertFalse(config.backend_freshness()["stale"])

    def test_source_modified_after_start_is_stale(self):
        """源码 mtime 晚于进程启动 → 必须判为 stale 并给出可执行的修复动作。"""
        os.utime(self.TARGET, (self._orig.st_atime, time.time() + 120))
        f = config.backend_freshness()
        self.assertTrue(f["stale"])
        self.assertTrue(f["newest_source"].endswith("utils.py"))
        self.assertIn("重启", f["reason"])

    def test_reports_uptime_and_newest_file(self):
        f = config.backend_freshness()
        self.assertGreaterEqual(f["uptime_seconds"], 0)
        self.assertTrue(f["newest_source"].endswith(".py"))

    def test_pycache_is_ignored(self):
        """__pycache__ 里的 .pyc 不参与判断，否则跑一次测试就会把自己判成 stale。"""
        f = config.backend_freshness()
        self.assertNotIn("__pycache__", f["newest_source"])


class StaticFreshnessTests(unittest.TestCase):
    def test_shape_is_always_complete(self):
        f = config.static_freshness()
        for k in ("built", "stale", "built_at", "source_at", "reason"):
            self.assertIn(k, f)

    def test_missing_bundle_counts_as_stale(self):
        f = config.static_freshness()
        if not f["built"]:
            self.assertTrue(f["stale"])
            self.assertIn("尚未构建", f["reason"])
        else:
            self.assertIsInstance(f["stale"], bool)


if __name__ == "__main__":
    unittest.main()
