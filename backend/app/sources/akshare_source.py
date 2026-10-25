"""akshare 兜底源（可选依赖）。

akshare 聚合了东财/新浪/同花顺等几十个免费接口，是「多数据源备用」的最后一道保险。
未安装时本模块所有函数返回 None，系统自动跳过。
pip install akshare
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable

from ..core.config import settings

log = logging.getLogger("review.akshare")
_ak = None


def _akshare():
    global _ak
    if not settings.allow_akshare:
        return None
    if _ak is None:
        try:
            import akshare as ak  # type: ignore

            _ak = ak
        except Exception as exc:  # noqa: BLE001
            log.info("akshare 不可用（%s），将使用内置直连数据源", exc)
            _ak = False
    return _ak or None


def available() -> bool:
    return _akshare() is not None


async def _run(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    ak = _akshare()
    if ak is None:
        return None
    f = getattr(ak, fn.__name__ if hasattr(fn, "__name__") else str(fn), None)
    return await asyncio.to_thread(f, *args, **kwargs) if f else None


async def zt_pool(date: str) -> list[dict]:
    ak = _akshare()
    if ak is None:
        return []
    try:
        df = await asyncio.to_thread(ak.stock_zt_pool_em, date=date.replace("-", ""))
        return df.to_dict("records") if df is not None else []
    except Exception as exc:  # noqa: BLE001
        log.debug("akshare zt_pool: %s", exc)
        return []


async def index_spot() -> list[dict]:
    ak = _akshare()
    if ak is None:
        return []
    try:
        df = await asyncio.to_thread(ak.stock_zh_index_spot_em, symbol="指数成份")
        return df.to_dict("records") if df is not None else []
    except Exception:
        return []


async def sector_fund_flow(indicator: str = "今日") -> list[dict]:
    ak = _akshare()
    if ak is None:
        return []
    try:
        df = await asyncio.to_thread(ak.stock_sector_fund_flow_rank, indicator=indicator, sector_type="概念资金流")
        return df.to_dict("records") if df is not None else []
    except Exception:
        return []


async def lhb(date: str) -> list[dict]:
    ak = _akshare()
    if ak is None:
        return []
    try:
        df = await asyncio.to_thread(ak.stock_lhb_detail_em, start_date=date.replace("-", ""), end_date=date.replace("-", ""))
        return df.to_dict("records") if df is not None else []
    except Exception:
        return []