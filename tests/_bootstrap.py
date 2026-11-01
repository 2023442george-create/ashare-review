"""测试引导：把 backend 加入 sys.path，并把数据目录指向临时目录。

必须在任何 `app.*` 导入之前 import 本模块。
为什么强制改数据目录而不是沿用环境变量：测试会写 signal_log / signal_outcome，
一旦落到真实的 data/review.db，用户辛苦积累的前瞻样本就被测试数据污染了——
而前瞻样本是不可重建的。宁可忽略外部设置，也不能有这个风险。
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

TEST_DATA_DIR = tempfile.mkdtemp(prefix="ashare-review-test-")
os.environ["REVIEW_DATA_DIR"] = TEST_DATA_DIR
os.environ["REVIEW_SCHEDULER"] = "0"
os.environ["REVIEW_WARMUP"] = "0"


def sources_down():
    """模拟所有数据源都不可达。测试不能靠"碰巧没有网络"，有网时真实数据会让它们失败。"""
    async def _none(*_a, **_k):
        return None
    from app.core.config import settings
    patches = [mock.patch("app.core.http.fetch", _none), mock.patch.object(settings, "allow_akshare", False)]

    class _Down:
        def __enter__(self):
            for p in patches:
                p.start()

        def __exit__(self, *_exc):
            for p in patches:
                p.stop()
    return _Down()
