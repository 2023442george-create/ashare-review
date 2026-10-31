"""定时任务：盘中自动刷新、收盘后自动落库历史情绪。

- 交易日 09:15-11:35 / 12:55-15:05：每 2 分钟刷新行情与情绪
- 15:10：生成当日复盘快照（含龙虎榜、板块、报告），写入 SQLite 历史
- 15:14：冻结当日信号到结果账本（含未选中标的），并结算此前各日的前瞻结果
- 15:25 / 21:10：计算宏观水位（估值/ERP/国债/两融/ETF 份额）并写入每日快照
- 21:00：补充龙虎榜（交易所一般 17:00-19:00 公布）

为什么冻结必须由定时任务做、而不是等人点按钮：
前瞻样本的全部价值来自"当时就记下来了"。任何需要人每天记得去点一下的流程，
最后都会变成断断续续的样本——而带缺口的样本无法支撑任何统计结论。
"""
from __future__ import annotations

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from ..services import lhb, limitup, macro, market, report, sentiment, track
from .config import settings
from .utils import is_trade_day, last_trade_day, now_cn

log = logging.getLogger("review.scheduler")
_scheduler: AsyncIOScheduler | None = None


async def job_intraday() -> None:
    if not is_trade_day(now_cn().date()):
        return
    try:
        await market.overview(force=True)
        await sentiment.core(force=True)
        log.info("intraday refresh done")
    except Exception as exc:  # noqa: BLE001
        log.warning("intraday refresh failed: %s", exc)


async def job_close() -> None:
    """15:10 收盘快照。非交易日（节假日的周一到周五）不跑，否则会用节后数据重写节前快照。"""
    if not is_trade_day(now_cn().date()):
        return
    d = str(last_trade_day())
    try:
        await limitup.pool("zt", d, force=True)
        await limitup.pool("zb", d, force=True)
        await sentiment.core(d, force=True)
        await market.overview(force=True)
        rep = await report.build(d, force=True)
        log.info("close snapshot done: %s score=%s", d, (rep.get("composite") or {}).get("score"))
    except Exception as exc:  # noqa: BLE001
        log.warning("close snapshot failed: %s", exc)


async def job_ledger() -> None:
    """收盘后冻结今日信号 + 结算此前各日结果。两件事必须在同一个任务里顺序执行。"""
    d = str(last_trade_day())
    if not is_trade_day(now_cn().date()):
        return
    try:
        fr = await track.freeze(d)
        log.info("ledger freeze %s: %s rows (%s)", d, fr.get("frozen"), fr.get("reason") or "ok")
    except Exception as exc:  # noqa: BLE001
        log.warning("ledger freeze failed: %s", exc)
    try:
        se = await track.settle()
        log.info("ledger settle: %s outcomes, skipped=%s", se.get("settled"), se.get("skipped"))
    except Exception as exc:  # noqa: BLE001
        log.warning("ledger settle failed: %s", exc)


async def job_macro() -> None:
    """收盘后计算一次宏观水位；overview() 内部会把温度摘要写入 macro_daily。

    国债、两融、ETF 份额多在收盘后陆续更新，21:00 再跑一次补齐当天数据。
    """
    if not is_trade_day(now_cn().date()):
        return
    try:
        res = await macro.overview(force=True)
        t = res.get("temperature") or {}
        log.info("macro done: score=%s used=%s/%s gaps=%s", t.get("score"), t.get("used"), t.get("total"),
                 len(res.get("gaps") or []))
    except Exception as exc:  # noqa: BLE001
        log.warning("macro failed: %s", exc)


async def job_lhb() -> None:
    """21:00 补拉龙虎榜并重建报告。非交易日不跑。"""
    if not is_trade_day(now_cn().date()):
        return
    d = str(last_trade_day())
    try:
        await lhb.daily(d, force=True)
        await report.build(d, force=True)
        log.info("lhb refresh done: %s", d)
    except Exception as exc:  # noqa: BLE001
        log.warning("lhb refresh failed: %s", exc)


async def catch_up() -> None:
    """启动时补跑"今天"错过的收盘任务。

    为什么需要：定时任务只在程序开着时才会触发。如果每天晚上才打开程序，
    15:10 快照、15:14 账本冻结、15:25 宏观快照就永远不会执行，账本一直是空的。

    只补当天、且只在收盘后：当晚补冻结用的仍是当天收盘后可见的数据，不涉及后视信息；
    补冻结以前的日期则会用到之后的信息，所以刻意不做（与 README「不要事后补冻结」一致）。
    """
    from . import store

    now = now_cn()
    if not is_trade_day(now.date()) or now.hour * 60 + now.minute < 15 * 60 + 12:
        return
    d = str(now.date())
    if store.load_snapshot(d) is None:
        log.info("catch-up: 今日收盘快照缺失，补跑")
        await job_close()
    if not store.load_signals(d):
        log.info("catch-up: 今日结果账本未冻结，补跑")
        await job_ledger()
    if not any(r.get("trade_date") == d for r in store.load_macro_history(5)):
        log.info("catch-up: 今日宏观快照缺失，补跑")
        await job_macro()


def start() -> None:
    global _scheduler
    if not settings.scheduler_enabled or _scheduler is not None:
        return
    _scheduler = AsyncIOScheduler(timezone=settings.timezone)
    _scheduler.add_job(job_intraday, CronTrigger(day_of_week="mon-fri", hour="9-11", minute="*/2"), id="intraday_am")
    _scheduler.add_job(job_intraday, CronTrigger(day_of_week="mon-fri", hour="13-14", minute="*/2"), id="intraday_pm")
    _scheduler.add_job(job_close, CronTrigger(hour=15, minute=10, day_of_week="mon-fri"), id="close_snapshot")
    _scheduler.add_job(job_ledger, CronTrigger(hour=15, minute=14, day_of_week="mon-fri"), id="ledger")
    _scheduler.add_job(job_lhb, CronTrigger(hour=21, minute=0, day_of_week="mon-fri"), id="lhb_night")
    _scheduler.add_job(job_macro, CronTrigger(hour=15, minute=25, day_of_week="mon-fri"), id="macro_close")
    _scheduler.add_job(job_macro, CronTrigger(hour=21, minute=10, day_of_week="mon-fri"), id="macro_night")
    _scheduler.start()
    log.info("scheduler started (intraday/2min, close@15:10, ledger@15:14, macro@15:25/21:10, lhb@21:00)")


def stop() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None