"""大盘服务：指数行情、两市成交额、涨跌家数、量能结构、指数K线。"""
from __future__ import annotations

from typing import Any

from ..core import cache
from ..core.assets import A_INDEXES, Asset
from ..core.config import settings
from ..core.utils import current_trade_date, fnum, yi
from ..sources import eastmoney as em
from ..sources import mock, sina, tencent


# ---------- 各来源适配器：统一签名 (assets) -> {key: quote_dict} ----------
async def _q_tencent(assets: list[Asset]) -> dict[str, dict]:
    codes = [a.tx for a in assets if a.tx]
    rows = await tencent.quote(codes)
    idx = {r["code"].lower(): r for r in rows}
    out = {}
    for a in assets:
        if a.tx and a.tx.lower() in idx:
            out[a.key] = idx[a.tx.lower()]
    return out


async def _q_sina(assets: list[Asset]) -> dict[str, dict]:
    codes = [a.sina for a in assets if a.sina and a.sina_kind == "stock"]
    if not codes:
        return {}
    raw = await sina.quote_raw(codes)
    out = {}
    for a in assets:
        f = raw.get(a.sina or "")
        if not f:
            continue
        p = sina.parse_stock(f, a.sina or a.key)
        if p:
            out[a.key] = p
    return out


async def _q_em(assets: list[Asset]) -> dict[str, dict]:
    secids = [a.em for a in assets if a.em and a.em.split(".")[0] in ("0", "1")]
    if not secids:
        return {}
    rows = await em.quote_list(secids, "f1,f2,f3,f4,f5,f6,f12,f13,f14,f15,f16,f17,f18")
    idx = {f"{r.get('f13')}.{r.get('f12')}": r for r in rows if r.get("f12")}
    out = {}
    for a in assets:
        r = idx.get(a.em or "")
        if not r:
            continue
        out[a.key] = {
            "code": a.em, "name": r.get("f14") or a.name, "price": fnum(r.get("f2")),
            "pct": fnum(r.get("f3")), "change": fnum(r.get("f4")), "volume": fnum(r.get("f5"), 0.0),
            "amount": fnum(r.get("f6"), 0.0), "high": fnum(r.get("f15")), "low": fnum(r.get("f16")),
            "open": fnum(r.get("f17")), "prev_close": fnum(r.get("f18")),
        }
    return out


def _q_mock(assets: list[Asset]) -> dict[str, dict]:
    rows = {r["symbol"]: r for r in mock.quotes()}
    return {a.key: rows[a.key] for a in assets if a.key in rows}


REGISTRY = {"tencent": _q_tencent, "sina": _q_sina, "eastmoney": _q_em, "mock": _q_mock}


async def fetch_quotes(assets: list[Asset] | None = None, force: bool = False) -> cache.Sourced:
    assets = assets or A_INDEXES
    providers = cache.order_providers("quote", REGISTRY)
    key = "quote:" + ",".join(sorted(a.key for a in assets))

    def valid(res: Any) -> bool:
        return isinstance(res, dict) and len(res) >= max(1, int(len(assets) * 0.5))

    return await cache.chain(providers, assets, cache_key=key, ttl=settings.ttl_quote, force=force, validator=valid)


async def overview(force: bool = False) -> dict:
    """首页总览：指数 + 成交额 + 涨跌家数 + 量能对比。"""
    from . import sentiment as senti

    q = await fetch_quotes(force=force)
    quotes: dict[str, dict] = q.data or {}
    zb = await senti.breadth(force=force)

    sh = quotes.get("sh000001") or {}
    sz = quotes.get("sz399001") or {}
    amount_total = (fnum(sh.get("amount"), 0.0) or 0) + (fnum(sz.get("amount"), 0.0) or 0)

    th = await turnover_history(days=12, force=force)
    # 只看今天之前的日子：K 线还没带今天这一行时，末尾那天就是昨天，不能再往前错一位
    today = str(current_trade_date())
    totals = [r["amount"] for r in (th.get("items") or []) if r.get("amount") and r["date"] < today]
    ma5_amount = round(sum(totals[-5:]) / 5, 0) if len(totals) >= 5 else None
    prev_amount = totals[-1] if totals else None

    items = []
    for a in A_INDEXES:
        d = quotes.get(a.key) or {}
        high, low, prev = fnum(d.get("high")), fnum(d.get("low")), fnum(d.get("prev_close"))
        items.append({
            "key": a.key, "name": d.get("name") or a.name, "group": a.group, "role": a.role,
            "price": d.get("price"), "pct": d.get("pct"), "change": d.get("change"),
            "open": d.get("open"), "high": d.get("high"), "low": d.get("low"),
            "prev_close": d.get("prev_close"), "amount": d.get("amount"),
            "amount_yi": yi(fnum(d.get("amount"), 0.0)),
            # 只有腾讯直接给振幅，新浪/东财兜底时按高低价算
            "amplitude": d.get("amplitude") or (round((high - low) / prev * 100, 2) if high and low and prev else None),
        })

    return {
        "indices": items,
        "turnover": {
            "total": amount_total,
            "total_yi": yi(amount_total),
            "sh_yi": yi(fnum(sh.get("amount"), 0.0)),
            "sz_yi": yi(fnum(sz.get("amount"), 0.0)),
            "prev_yi": yi(prev_amount),
            "ma5_yi": yi(ma5_amount),
            "delta_yi": yi(amount_total - prev_amount) if prev_amount else None,
            "level": _volume_level(amount_total),
            "estimated": bool(th.get("estimated")),
            "history_source": th.get("source"),
        },
        "breadth": zb.data or {},
        "meta": {**q.meta(), "breadth_source": zb.source},
    }


def _volume_level(amount: float) -> dict:
    """游资口径的成交量档位：<8000亿 冰点 / 8000-12000 存量 / 1.2-1.8 温和 / >1.8万亿 增量"""
    y = amount / 1e8
    if y <= 0:
        return {"label": "无数据", "score": 0, "tip": ""}
    if y < 8000:
        return {"label": "地量冰点", "score": 20, "tip": "存量博弈，只做确定性龙头，控制仓位"}
    if y < 12000:
        return {"label": "存量博弈", "score": 45, "tip": "轮动快、持续性差，避免追高，做低吸"}
    if y < 18000:
        return {"label": "温和放量", "score": 70, "tip": "题材可参与，注意主线集中度"}
    if y < 25000:
        return {"label": "增量入场", "score": 85, "tip": "赚钱效应扩散期，可提升仓位打板/半路"}
    return {"label": "天量博弈", "score": 95, "tip": "天量常伴天量分歧，警惕高位见顶信号"}


KLINE_REGISTRY = {
    "tencent": lambda sym, days: tencent.kline(sym, "day", days),
    "sina": lambda sym, days: sina.kline(sym, 240, days),
    "eastmoney": None,  # 见下方包装（需要 secid）
    "mock": lambda sym, days: mock.kline(days),
}


async def _kline_em(symbol: str, days: int):
    from ..core.assets import ASSET_MAP
    from ..core.utils import code_to_secid

    a = ASSET_MAP.get(symbol)
    secid = a.em if a and a.em else code_to_secid(symbol)
    rows = await em.kline(secid, 101, 1, days)
    # 东财字段序：date,open,close,high,low,volume,amount
    return [[r[0], r[1], r[2], r[3], r[4], r[5], r[6]] for r in rows]


async def kline(symbol: str = "sh000001", days: int = 120, force: bool = False) -> cache.Sourced:
    registry = dict(KLINE_REGISTRY)
    registry["eastmoney"] = _kline_em
    providers = cache.order_providers("kline", registry)
    return await cache.chain(
        providers, symbol, days,
        cache_key=f"kline:{symbol}:{days}", ttl=settings.ttl_kline, force=force,
        validator=lambda r: isinstance(r, list) and len(r) > 5,
    )


async def turnover_history(days: int = 12, force: bool = False) -> dict:
    """两市成交额历史。

    东财、腾讯K线自带成交额则直接使用；若只能拿到新浪K线（仅成交量），
    用「今日成交额 / 今日成交量」折算系数推算历史成交额，并标记 estimated。
    这个推算把今天的股价水平套到全部历史上，时间拉长后偏差明显，所以只作兜底。
    """
    import asyncio

    from ..core.utils import fnum as _f

    ks = await asyncio.gather(kline("sh000001", days + 5, force=force),
                              kline("sz399001", days + 5, force=force))
    q = await fetch_quotes(force=force)
    quotes: dict[str, dict] = q.data or {}
    series: dict[str, list] = {}
    for key, res in zip(("sh000001", "sz399001"), ks):
        rows = res.data or []
        today_amount = _f((quotes.get(key) or {}).get("amount"), 0.0) or 0
        has_amount = any(len(r) > 6 and r[6] for r in rows)
        if has_amount:
            series[key] = [[r[0], _f(r[6], 0.0)] for r in rows if len(r) > 6 and r[6]]
            continue
        vols = [[r[0], _f(r[5], 0.0)] for r in rows]
        if not vols or not vols[-1][1]:
            series[key] = []
            continue
        factor = today_amount / vols[-1][1] if today_amount else 0
        series[key] = [[d, round(v * factor, 0)] for d, v in vols]

    sh_map, sz_map = dict(series.get("sh000001") or []), dict(series.get("sz399001") or [])
    dates = sorted(set(sh_map) | set(sz_map))[-days:]
    items = []
    for d in dates:
        sh, sz = sh_map.get(d), sz_map.get(d)
        # 只取到一个市场的那天不算两市合计：半边成交额会被读成"缩量一半"
        total = sh + sz if sh and sz else 0
        items.append({"date": d, "sh": sh, "sz": sz, "amount": total or None,
                      "amount_yi": round(total / 1e8, 2) if total else None})
    src = sorted({(ks[0].source or ""), (ks[1].source or "")} - {""})
    return {"items": items, "source": "+".join(src) or "none",
            "estimated": not any(len(r) > 6 and r[6] for r in (ks[0].data or []))}