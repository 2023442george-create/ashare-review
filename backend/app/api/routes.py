"""REST API 路由。所有接口都带 `meta.source`，前端会显示这条数据实际来自哪个源。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, HTTPException, Query
from fastapi.responses import PlainTextResponse

from ..core import cache, params, regime, store
from ..core.config import backend_freshness, settings, static_freshness
from ..core import http
from ..core.http import SOURCE_STATS
from ..core.utils import holiday_coverage, last_trade_day
from ..services import (auction as auction_svc, globalmarket, lhb as lhb_svc, limitup, macro, market,
                        news as news_svc, reconcile as reconcile_svc, report as report_svc,
                        screener as screener_svc, sectors, sentiment, track as track_svc)

router = APIRouter(prefix="/api")


def _wrap(res: Any, extra: dict | None = None) -> dict:
    """Sourced -> dict，统一附带来源信息"""
    if hasattr(res, "meta"):
        data = res.data
        out = data if isinstance(data, dict) else {"items": data}
        out = dict(out or {})
        out.setdefault("meta", {})
        out["meta"].update(res.meta())
        if extra:
            out.update(extra)
        return out
    return res if isinstance(res, dict) else {"items": res}


@router.get("/health")
async def health() -> dict:
    return {
        "app": settings.app_name, "version": settings.version, "offline": settings.offline,
        "scheduler": settings.scheduler_enabled, "cache": {"entries": cache.cache_stats()["entries"]},
        "sources": SOURCE_STATS,
        "hosts": http.host_state(),
        "priority": settings.source_priority,
        "trade_date": str(last_trade_day()),
        "frontend": static_freshness(),
        "backend": backend_freshness(),
        "calendar": holiday_coverage(),
    }


@router.post("/refresh")
async def refresh(kind: str = "all") -> dict:
    n = cache.cache_clear(None if kind == "all" else kind)
    out: dict[str, Any] = {"cleared": n}
    if kind in ("all", "market"):
        out["market"] = _wrap(await market.overview(force=True)).get("meta")
        out["sentiment"] = (await sentiment.core(force=True)).get("sources")
    if kind in ("all", "global"):
        out["global"] = (await globalmarket.overview(force=True)).get("meta")
    if kind in ("all", "news"):
        out["news"] = (await news_svc.feed(limit=60, force=True)).get("meta")
    if kind == "macro":
        # 宏观接口多、数据日更，只在明确要求时重拉，不跟随"全部刷新"
        out["macro"] = (await macro.overview(force=True)).get("meta")
    return out


# ---------------- 大盘 ----------------
@router.get("/market/overview")
async def market_overview(force: bool = False) -> dict:
    return _wrap(await market.overview(force=force))


@router.get("/market/kline")
async def market_kline(symbol: str = "sh000001", days: int = 120, force: bool = False) -> dict:
    res = await market.kline(symbol, min(days, 800), force=force)
    return {"symbol": symbol, "items": res.data or [], "meta": res.meta()}


@router.get("/market/margin")
async def market_margin(force: bool = False) -> dict:
    return _wrap(await market.margin(force=force))


@router.get("/market/hsgt")
async def market_hsgt(force: bool = False) -> dict:
    return _wrap(await market.hsgt(force=force))


# ---------------- 情绪 ----------------
@router.get("/sentiment")
async def sentiment_core(date: str = "", force: bool = False) -> dict:
    return await sentiment.core(date or None, force=force)


@router.get("/sentiment/history")
async def sentiment_history(days: int = 60) -> dict:
    return {"items": store.load_sentiment_history(days)}


# ---------------- 涨跌停 ----------------
@router.get("/limitup")
async def limit_pool(kind: str = "zt", date: str = "", force: bool = False) -> dict:
    res = await limitup.pool(kind, date or None, force=force)
    data = dict(res.data or {})
    data["kind"] = kind
    data["meta"] = res.meta()
    return data


@router.get("/limitup/ladder")
async def limit_ladder(date: str = "", force: bool = False) -> dict:
    return await limitup.ladder(date or None, force=force)


# ---------------- 板块 ----------------
@router.get("/sectors")
async def sector_list(kind: str = "industry", sort: str = "pct", limit: int = 40, force: bool = False) -> dict:
    res = await sectors.boards(kind, sort, limit, force=force)
    # field_health 告诉前端哪一列是"上游没给"而不是"真的是 0"
    return _wrap(res, {"field_health": sectors.field_health(res.data)})


@router.get("/sectors/probe")
async def sector_probe(kind: str = "industry", pz: int = 3) -> dict:
    """字段级探针：逐个东财镜像主机看原始响应带回了哪些字段（排查涨跌家数等列缺失）。"""
    return await sectors.probe(kind, pz)


@router.get("/sectors/mainline")
async def sector_mainline(force: bool = False) -> dict:
    return await sectors.main_line(force=force)


@router.get("/sectors/stockflow")
async def sector_stockflow(limit: int = 50, sort: str = "f62", force: bool = False) -> dict:
    return _wrap(await sectors.stock_flow(limit, sort, force=force))


# ---------------- 龙虎榜 ----------------
@router.get("/lhb")
async def lhb_daily(date: str = "", force: bool = False) -> dict:
    return _wrap(await lhb_svc.daily(date or None, force=force))


@router.get("/lhb/focus")
async def lhb_focus(date: str = "") -> dict:
    return {"items": await lhb_svc.focus_stocks(date or None)}


# ---------------- 外围 ----------------
@router.get("/global")
async def global_overview(force: bool = False) -> dict:
    return await globalmarket.overview(force=force)


# ---------------- 宏观水位 ----------------
@router.get("/macro/overview")
async def macro_overview(force: bool = False) -> dict:
    """估值分位、股债性价比、利率、红利息差、成交额/两融分位、宽基 ETF 份额与宏观温度分。"""
    return await macro.overview(force=force)


@router.get("/macro/history")
async def macro_history(days: int = 250) -> dict:
    """每日宏观温度快照（收盘后定时任务写入）。"""
    return macro.history(min(days, 2000))


@router.get("/macro/probe")
async def macro_probe() -> dict:
    """逐个宏观数据源发最小请求，报告是否可用、样例值与缺失字段。首次接入时用来核对接口。"""
    return await macro.probe()


# ---------------- 资讯 ----------------
@router.get("/news")
async def news_feed(limit: int = 100, source: str = "", tag: str = "", keyword: str = "", force: bool = False) -> dict:
    return await news_svc.feed(limit, source, tag, keyword, force=force)


# ---------------- 选股器 ----------------
@router.get("/screener")
async def screener(strategy: str = "first_board", date: str = "") -> dict:
    return await screener_svc.run(strategy, date or None)


@router.get("/screener/strategies")
async def screener_strategies() -> dict:
    return {"items": [{"key": k, "desc": v} for k, v in screener_svc.STRATEGIES.items()]}


# ---------------- 次日竞价确认 ----------------
@router.get("/auction")
async def auction_confirm(strategy: str = "first_board", date: str = "", force: bool = False) -> dict:
    return await auction_svc.build(strategy, date or None, force=force)


# ---------------- 复盘报告 ----------------
@router.get("/report")
async def report_build(date: str = "", force: bool = False) -> dict:
    try:
        return await report_svc.build(date or None, force=force)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/report.md", response_class=PlainTextResponse)
async def report_markdown(date: str = "", force: bool = False) -> str:
    try:
        rep = await report_svc.build(date or None, force=force)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return rep.get("markdown") or ""


@router.post("/report/note")
async def report_note(payload: dict = Body(...)) -> dict:
    d = payload.get("date") or str(last_trade_day())
    store.save_note(d, payload.get("content") or "")
    return {"ok": True, "date": d}


@router.get("/report/note")
async def report_note_get(date: str = "") -> dict:
    d = date or str(last_trade_day())
    return {"date": d, "content": store.load_note(d)}


# ---------------- 研究：结果账本 ----------------
@router.get("/track/status")
async def track_status() -> dict:
    """研究状态（由账本统计算出，不是写死的字段）。"""
    return track_svc.status()


@router.post("/track/freeze")
async def track_freeze(date: str = "") -> dict:
    """冻结某交易日的全部可选标的（含未选中），幂等。收盘后由定时任务自动调用。"""
    return await track_svc.freeze(date or None)


@router.post("/track/settle")
async def track_settle(date: str = "", strategy: str = "") -> dict:
    """用次日开盘价入场、T+N 收盘价出场回填前瞻结果，并逐样本扣除基准。"""
    return await track_svc.settle(date or None, strategy=strategy or None)


@router.get("/track/record")
async def track_record(strategy: str = "first_board", horizon: int = 1,
                       include_untradable: bool = False, force: bool = False) -> dict:
    """战绩表：样本量、中位数、Bootstrap 区间、分层单调性、分层置换 p 值、不可成交率。"""
    return track_svc.record(strategy, horizon, include_untradable, force=force)


@router.get("/track/matrix")
async def track_matrix() -> dict:
    """跨策略 × 持有期总表，并对全部 p 值做 BH 多重检验校正。"""
    return track_svc.multi_record()


@router.get("/track/signals")
async def track_signals(date: str = "", strategy: str = "", only_selected: bool = False) -> dict:
    """查看某日冻结的原始信号记录（含冻结时间戳与参数指纹），供第三方复核。"""
    return {"items": store.load_signals(date or None, strategy or None, only_selected),
            "dates": store.signal_dates()}


# ---------------- 研究：对账与参数 ----------------
@router.get("/reconcile")
async def reconcile(date: str = "", force: bool = False) -> dict:
    """数据对账：跨接口家数比对 + 按涨跌幅制度表独立判定封板 + 不变量检查。"""
    return await reconcile_svc.run(date or None, force=force)


@router.get("/research/params")
async def research_params() -> dict:
    """当前全部阈值/权重/成本/统计设置及其指纹。复核的第一步是先确认用的是哪组参数。"""
    snap = params.snapshot()
    return {"params": snap, "digest": params.digest(), "version": params.PARAM_VERSION,
            "prior_note": params.PRIOR_NOTE, "cost_pct_round_trip": track_svc.total_cost_pct()}


@router.get("/research/trials")
async def research_trials(limit: int = 200) -> dict:
    """试错台账：一共试过多少策略/参数。多重检验校正需要这个分母。"""
    return {"items": store.list_trials(limit)}


@router.get("/research/regime")
async def research_regime(date: str = "", start: str = "", end: str = "") -> dict:
    """涨跌幅制度档位与统计口径变更时间线。跨这些日期的序列不是同一种数据。"""
    out: dict[str, Any] = {"note": regime.regime_note(date or str(last_trade_day()))}
    if start:
        out["caveats"] = regime.caveats_for(start, end or None)
    else:
        out["all_events"] = regime.CALIBER_EVENTS
    return out


# ---------------- 自选 ----------------
@router.get("/watchlist")
async def watchlist() -> dict:
    items = store.list_watch()
    if items:
        from ..core.assets import Asset

        assets = [Asset(key=i["code"], name=i["name"], group="自选",
                        tx=i["code"], sina=i["code"], sina_kind="stock") for i in items]
        q = await market.fetch_quotes(assets)
        quotes = q.data or {}
        for i in items:
            d = quotes.get(i["code"]) or {}
            i.update({"price": d.get("price"), "pct": d.get("pct"), "amount": d.get("amount"),
                      "name": d.get("name") or i.get("name")})
    return {"items": items}


@router.post("/watchlist")
async def watchlist_add(payload: dict = Body(...)) -> dict:
    store.add_watch(str(payload.get("code", "")), payload.get("name", ""), payload.get("tag", ""))
    return {"ok": True}


@router.delete("/watchlist/{code}")
async def watchlist_del(code: str) -> dict:
    store.del_watch(code)
    return {"ok": True}


# ---------------- 数据源设置 ----------------
@router.get("/settings/sources")
async def settings_sources() -> dict:
    return {"priority": settings.source_priority, "stats": SOURCE_STATS, "offline": settings.offline}


@router.post("/settings/sources")
async def settings_sources_update(payload: dict = Body(...)) -> dict:
    prio = payload.get("priority") or {}
    for k, v in prio.items():
        if isinstance(v, list) and v:
            settings.source_priority[k] = [str(x) for x in v]
    if "offline" in payload:
        settings.offline = bool(payload["offline"])
    return {"ok": True, "priority": settings.source_priority, "offline": settings.offline}


@router.get("/meta/indicators")
async def meta_indicators() -> dict:
    """指标说明书：每个指标是什么、游资怎么用（前端「?」提示用）"""
    from ..core.assets import A_INDEXES, GLOBAL_ASSETS

    return {
        "indexes": [{"key": a.key, "name": a.name, "role": a.role} for a in A_INDEXES],
        "global": [{"key": a.key, "name": a.name, "group": a.group, "role": a.role} for a in GLOBAL_ASSETS],
        "sentiment": [
            {"key": "limit_up", "name": "涨停家数", "how": "≥90家=情绪强，40家以下=情绪弱；连续3天上升=发酵期"},
            {"key": "max_boards", "name": "最高连板（空间板）", "how": "决定市场想象力。5板以上才有主升行情；空间板断板=情绪见顶信号"},
            {"key": "broken_rate", "name": "炸板率", "how": "炸板/(涨停+炸板)。<20%封板坚决；>35%分歧巨大，次日大概率核按钮"},
            {"key": "prev_premium", "name": "昨日涨停今日溢价", "how": "收盘价相对昨收的等权涨跌幅，代表隔日结果，不是必然可成交收益。另看开盘隔夜溢价与开盘可成交样本日内收益"},
            {"key": "promote_rate", "name": "晋级率", "how": "昨日涨停今日继续涨停比例。>30%梯队健康；<15%说明接力资金撤退"},
            {"key": "up_ratio", "name": "上涨家数占比", "how": ">60%普涨（做题材）、<40%分化（只做龙头）"},
            {"key": "limit_down", "name": "跌停家数", "how": ">10家=系统性杀跌，当日不开新仓"},
            {"key": "seal_ratio", "name": "封成比", "how": "封单额/成交额。>30%封板坚决，<5%随时可能开板"},
            {"key": "fund_mv_ratio", "name": "封单/流通市值", "how": ">3%属于强力封板，龙头特征"},
            {"key": "turnover_total", "name": "两市成交额", "how": "<8000亿地量冰点；1.2-1.8万亿温和；>1.8万亿增量入场。看5日均量趋势而非绝对值"},
            {"key": "main_flow", "name": "主力净流入", "how": "板块主力净流入连续为正+涨停家数多=主线；净流出但股价大涨=拉高出货嫌疑"},
            {"key": "auction_gap", "name": "竞价高开幅度", "how": "09:15-09:25 匹配价/昨收。高开过低说明承接弱，过高说明一致转分歧；超过剧本上限不追"},
            {"key": "auction_amount_ratio", "name": "竞价量能比", "how": "集合竞价成交额/候选日成交额，用于确认资金是否真的来；首板参考线2%、接力3%"},
        ],
    }