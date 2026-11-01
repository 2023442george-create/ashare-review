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
            {"key": "max_boards", "name": "最高连板", "how": "连续涨停最多的票有几板，决定市场想象力。5板以上才有主升行情；空间板断板=情绪见顶信号"},
            {"key": "broken_rate", "name": "炸板率", "how": "炸板/(涨停+炸板)。<20%封板坚决；>35%分歧巨大，次日大概率核按钮"},
            {"key": "prev_premium", "name": "昨日涨停今日溢价", "how": "收盘价相对昨收的等权涨跌幅，代表隔日结果，不是必然可成交收益。另看开盘隔夜溢价与开盘可成交样本日内收益"},
            {"key": "promote_rate", "name": "晋级率", "how": "昨日涨停今日继续涨停比例。>30%梯队健康；<15%说明接力资金撤退"},
            {"key": "up_ratio", "name": "上涨家数占比", "how": ">60%普涨（做题材）、<40%分化（只做龙头）"},
            {"key": "limit_down", "name": "跌停家数", "how": ">10家=系统性杀跌，当日不开新仓"},
            {"key": "seal_ratio", "name": "封成比", "how": "封单额/成交额。>30%封板坚决，<5%随时可能开板"},
            {"key": "fund_mv_ratio", "name": "封单/流通市值", "how": ">3%属于强力封板，龙头特征"},
            {"key": "turnover_total", "name": "两市成交额", "how": "<8000亿地量冰点；1.2-1.8万亿温和；>1.8万亿增量入场。看5日均量趋势而非绝对值"},
            {"key": "main_flow", "name": "主力净流入", "how": "大单买入减大单卖出的估算值，不是真实账户数据。板块连续净流入+涨停多=主线；净流出但股价大涨=拉高出货嫌疑"},
            {"key": "auction_gap", "name": "竞价高开幅度", "how": "09:15-09:25 匹配价/昨收。高开过低说明承接弱，过高说明一致转分歧；超过剧本上限不追"},
            {"key": "auction_amount_ratio", "name": "竞价量能比", "how": "集合竞价成交额/候选日成交额，用于确认资金是否真的来；首板参考线2%、接力3%"},
        ],
        # 其余页面的指标说明：name 是界面文字，how 一两句讲清是什么、怎么看
        "macro": [
            {"key": "temperature", "name": "宏观温度", "how": "0~100，把估值和资金的历史分位合成一个数，看月度、季度的攻守，不看单日。<40 偏冷偏便宜，>60 偏热偏贵"},
            {"key": "pe", "name": "滚动 PE", "how": "指数总市值 / 最近 12 个月净利润，即现在的价格是几年利润。看它在过去 10 年的分位，不看绝对值"},
            {"key": "csi300", "name": "沪深300 PE", "how": "大盘蓝筹的估值。分位 <30% 偏便宜，>70% 偏贵"},
            {"key": "csiall", "name": "中证全指 PE", "how": "几乎全部 A 股的估值，比沪深300更能代表中小盘。分位 <30% 偏便宜，>70% 偏贵"},
            {"key": "erp", "name": "股债性价比 ERP", "how": "沪深300盈利收益率（1/PE）− 10年国债收益率，即买股票比买国债多赚多少。越高股票越划算"},
            {"key": "cn10y", "name": "10年期国债", "how": "无风险利率的基准。下行利好股票估值；同时也反映市场对经济偏悲观"},
            {"key": "rates", "name": "利率", "how": "中美利差 = 中国10年 − 美国10年，负得越多，人民币和外资流入压力越大。期限利差看下方说明"},
            {"key": "margin", "name": "两融余额", "how": "投资者借钱买股（融资）和借股卖出（融券）的余额，代表杠杆资金规模。数据次日才公布，比其他指标晚一天"},
            {"key": "flows", "name": "资金水位", "how": "成交额看场内有多少钱在交易；两融余额和融资买入占比看杠杆资金有多积极。分位越高越热"},
            {"key": "etf", "name": "宽基 ETF 份额", "how": "看份额不看规模：规模会随净值涨跌，份额变化才是真实申购赎回。下跌中份额大增，常被视为汇金等长线资金托底"},
            {"key": "futures", "name": "股指期货会员持仓", "how": "中金所每日公布前 20 名期货公司的多空单。空单多是机构对冲，净空常态化，要看变化：快速加空=加对冲或看空"},
            {"key": "basis", "name": "主力合约基差", "how": "期货价 − 现货价。负数叫贴水，年化后可跨合约比较。贴水加深=对冲增多或看空，收敛=情绪回暖"},
            {"key": "style", "name": "风格比值", "how": "两个指数相除，比值涨说明分子更强。不看绝对值，看方向和历史分位，用来判断资金偏小盘还是大盘、偏防守还是进攻"},
            {"key": "ah", "name": "AH 溢价指数", "how": "同一批公司 A 股相对 H 股贵多少，100 表示同价。越高 A 股相对越贵、港股越划算"},
            {"key": "south", "name": "南向资金", "how": "内地资金经港股通买港股的净额。持续净买入说明资金更看好港股，常与 AH 溢价走高同时出现"},
            {"key": "lift", "name": "限售股解禁", "how": "到期可以卖出的限售股市值，是潜在供给而不是必然抛售。未来 30 日明显高于过去 30 日时注意压力"},
        ],
        "limitup": [
            {"key": "ladder", "name": "连板天梯", "how": "按连续涨停天数分层。层层都有票=接力通畅；中间缺层叫断层，说明晋级难，不宜追高"},
            {"key": "board_type", "name": "板型", "how": "一字=开盘封死基本买不到；T字=开盘封住后开过板；秒板=开盘 5 分钟内封住；换手板=盘中充分换手后封住；烂板=炸板≥2次；尾盘板=14:45 后才封"},
            {"key": "fund", "name": "封单额", "how": "收盘时封在涨停价上的买单金额，越大次日越容易继续走强"},
            {"key": "first_time", "name": "首封", "how": "第一次封上涨停的时间，越早通常越强；末封是最后一次封住的时间，炸板后回封才会不同"},
            {"key": "days_board", "name": "几天几板", "how": "如 3天2板：最近 3 个交易日里有 2 个涨停，反映股性活跃度，和严格连板数不同"},
        ],
        "sectors": [
            {"key": "mainline", "name": "主线四维确认", "how": "板块内涨停≥4家、最高板≥2、板块涨幅>2%、主力净流入>0，四项同时成立才算确认；缺一项说明可能只是资金短线扎堆"},
            {"key": "main_flow_ratio", "name": "净占比", "how": "主力净流入 / 成交额，大小不同的板块用它比较才公平"},
            {"key": "pct_nd", "name": "5日/20日涨幅", "how": "看板块的持续性：当日大涨但 20 日仍弱多为反弹，5 日和 20 日同步走强才像趋势"},
        ],
        "lhb": [
            {"key": "lhb_net", "name": "龙虎榜净额", "how": "上榜席位买入 − 卖出，只含前五大买卖席位，不是这只票全天的资金净流入"},
            {"key": "inst_net", "name": "机构专用净买入", "how": "所有机构专用席位的合计净额。持续净买入的题材通常比纯游资票持续性好"},
            {"key": "north_net", "name": "股通席位净买入", "how": "仅统计上榜个股的沪/深股通专用席位，不等于全市场北向净买入（后者已于 2024-08 停止披露）"},
            {"key": "win_3day", "name": "3日胜率", "how": "该席位上榜后 3 个交易日上涨的比例，看的是历史统计，次数太少时没有参考意义"},
        ],
    }