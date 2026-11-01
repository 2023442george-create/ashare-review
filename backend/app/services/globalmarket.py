"""外围市场服务：美股 / 日韩台 / 港股 / 汇率商品 / A50期货 + 对A股影响解读。

多源策略（逐资产 failover）：
东方财富(全) → 腾讯(美股/港股/VIX) → 新浪(美股gb_$ / 亚太int_ / 期货hf_ / 外汇fx_)
→ Yahoo → Stooq → 内置样例
"""
from __future__ import annotations

from typing import Any

from ..core import cache
from ..core.assets import GLOBAL_ASSETS, Asset
from ..core.config import settings
from ..core.utils import fnum
from ..sources import eastmoney as em
from ..sources import mock, sina, tencent, yahoo


def _empty(a: Asset) -> dict:
    return {"key": a.key, "name": a.name, "group": a.group, "role": a.role, "unit": a.unit,
            "price": None, "pct": None, "change": None, "high": None, "low": None,
            "open": None, "prev_close": None, "time": "", "source": "none"}


async def _fill_em(assets: list[Asset], out: dict[str, dict]) -> None:
    secids = [a.em for a in assets if a.em]
    if not secids:
        return
    rows = await em.quote_list(secids, "f1,f2,f3,f4,f12,f13,f14,f15,f16,f17,f18")
    idx = {str(r.get("f12")): r for r in rows if r.get("f12")}
    for a in assets:
        if not a.em or a.key in out:
            continue
        r = idx.get(a.em.split(".")[-1])
        if not r or fnum(r.get("f2")) is None:
            continue
        d = _empty(a)
        d.update({"price": fnum(r.get("f2")), "pct": fnum(r.get("f3")), "change": fnum(r.get("f4")),
                  "high": fnum(r.get("f15")), "low": fnum(r.get("f16")), "open": fnum(r.get("f17")),
                  "prev_close": fnum(r.get("f18")), "source": "eastmoney"})
        out[a.key] = d


async def _fill_tx(assets: list[Asset], out: dict[str, dict]) -> None:
    pend = [a for a in assets if a.tx and a.key not in out]
    if not pend:
        return
    rows = await tencent.quote([a.tx for a in pend])
    idx = {r["code"].lower(): r for r in rows}
    for a in pend:
        r = idx.get((a.tx or "").lower())
        if not r:
            continue
        d = _empty(a)
        d.update({"price": r.get("price"), "pct": r.get("pct"), "change": r.get("change"),
                  "high": r.get("high"), "low": r.get("low"), "open": r.get("open"),
                  "prev_close": r.get("prev_close"), "time": r.get("time"), "source": "tencent",
                  "stale": _is_stale(r.get("time"))})
        out[a.key] = d


def _is_stale(t: Any) -> bool:
    """行情时间距今超过 3 天视为陈旧（部分免费源对冷门品种更新不及时）"""
    if not t:
        return False
    import datetime as dt
    import re as _re

    from ..core.utils import now_cn

    digits = _re.sub(r"\D", "", str(t))[:8]
    if len(digits) < 8:
        return False
    try:
        d = dt.datetime.strptime(digits, "%Y%m%d").date()
    except ValueError:
        return False
    return (now_cn().date() - d).days > 3


async def _fill_sina(assets: list[Asset], out: dict[str, dict]) -> None:
    pend = [a for a in assets if a.sina and a.key not in out]
    if not pend:
        return
    raw = await sina.quote_raw([a.sina for a in pend])
    for a in pend:
        f = raw.get(a.sina or "")
        if not f:
            continue
        d = _empty(a)
        p = _parse_sina(f, a.sina_kind)
        if p.get("price") is None:
            continue
        d.update(p)
        d["source"] = "sina"
        out[a.key] = d


def _parse_sina(f: list[str], kind: str) -> dict:
    try:
        if kind == "us" and len(f) >= 5:
            price = fnum(f[1])
            prev = round(price / (1 + (fnum(f[2]) or 0) / 100), 2) if price and fnum(f[2]) is not None else None
            return {"price": price, "pct": fnum(f[2]), "time": f[3], "change": fnum(f[4]),
                    "open": fnum(f[5]) if len(f) > 5 else None,
                    "high": fnum(f[6]) if len(f) > 6 else None,
                    "low": fnum(f[7]) if len(f) > 7 else None, "prev_close": prev}
        if kind == "znb" and len(f) >= 4:
            # znb_xxx: 1最新 2涨跌 3涨跌幅 6日期 7时间 8今开 9昨收 10最高 11最低（部分品种只有前 6 列）
            full = len(f) > 11
            return {"price": fnum(f[1]), "change": fnum(f[2]), "pct": fnum(f[3]),
                    "time": f"{f[6]} {f[7]}" if full else "",
                    "open": fnum(f[8]) if full else None, "prev_close": fnum(f[9]) if full else None,
                    "high": fnum(f[10]) if full else None, "low": fnum(f[11]) if full else None}
        if kind == "hf" and len(f) >= 9:
            # hf_xxx: 0最新 4最高 5最低 6时间 7昨结 8今开 12日期
            price = fnum(f[0])
            prev = fnum(f[7])
            return {"price": price, "prev_close": prev, "open": fnum(f[8]), "high": fnum(f[4]),
                    "low": fnum(f[5]), "time": f"{f[12] if len(f) > 12 else ''} {f[6]}".strip(),
                    "change": round(price - prev, 4) if price is not None and prev else None,
                    "pct": round((price / prev - 1) * 100, 3) if price and prev else None}
        if kind == "fx" and len(f) >= 12:
            # fx_sxxxx: 0时间 3最新 5今开 6最高 7最低 8最新 9名称 10涨跌幅 11涨跌 17日期。没有昨收列
            price = fnum(f[3]) or fnum(f[1])
            chg = fnum(f[11])
            return {"price": price, "prev_close": round(price - chg, 5) if price is not None and chg is not None else None,
                    "open": fnum(f[5]), "high": fnum(f[6]), "low": fnum(f[7]),
                    "time": f"{f[17] if len(f) > 17 else ''} {f[0]}".strip(),
                    "change": chg, "pct": fnum(f[10])}
        if kind == "dini" and len(f) >= 11:
            # DINIW: 0时间 3昨收 5今开 6最高 7最低 8最新 10日期
            price, prev = fnum(f[8]), fnum(f[3])
            return {"price": price, "prev_close": prev, "open": fnum(f[5]), "high": fnum(f[6]), "low": fnum(f[7]),
                    "time": f"{f[10]} {f[0]}",
                    "change": round(price - prev, 4) if price is not None and prev else None,
                    "pct": round((price / prev - 1) * 100, 3) if price and prev else None}
        if kind == "bond" and len(f) >= 14:
            # globalbd_xxx: 1最新收益率 4最高 5最低 7涨跌幅 8涨跌(百分点) 12日期 13时间
            return {"price": fnum(f[1]), "high": fnum(f[4]), "low": fnum(f[5]), "pct": fnum(f[7]),
                    "change": fnum(f[8]), "time": f"{f[12]} {f[13]}"}
        if kind == "stock":
            return {"price": fnum(f[3]), "open": fnum(f[1]), "prev_close": fnum(f[2]),
                    "high": fnum(f[4]), "low": fnum(f[5])}
    except (IndexError, TypeError):
        pass
    return {}


async def _fill_yahoo(assets: list[Asset], out: dict[str, dict]) -> None:
    pend = [a for a in assets if a.yahoo and a.key not in out]
    if not pend:
        return
    rows = await yahoo.quote([a.yahoo for a in pend])
    idx = {str(r.get("code")): r for r in rows}
    for a in pend:
        r = idx.get(a.yahoo or "")
        if not r or r.get("price") is None:
            continue
        d = _empty(a)
        d.update({"price": r["price"], "pct": r.get("pct"), "change": r.get("change"),
                  "high": r.get("high"), "low": r.get("low"), "open": r.get("open"),
                  "prev_close": r.get("prev_close"), "source": "yahoo"})
        out[a.key] = d


async def _fill_stooq(assets: list[Asset], out: dict[str, dict]) -> None:
    pend = [a for a in assets if a.stooq and a.key not in out]
    if not pend:
        return
    rows = await yahoo.stooq_quote([a.stooq for a in pend])
    idx = {str(r.get("code")).lower(): r for r in rows}
    for a in pend:
        r = idx.get((a.stooq or "").lower())
        if not r or r.get("price") in (None, 0, "N/D"):
            continue
        d = _empty(a)
        # Stooq 的 CSV 没有昨收字段。用开盘价代替昨收会把“日内涨跌”误算成
        # “日涨跌幅”，因此这里只保留价格，不给错误的 pct。
        d.update({"price": r.get("price"), "open": fnum(r.get("open")),
                  "high": r.get("high"), "low": r.get("low"),
                  "change": None, "pct": None,
                  "pct_unavailable_reason": "Stooq 无昨收字段",
                  "time": f"{r.get('date')} {r.get('time')}", "source": "stooq"})
        out[a.key] = d


def _fill_mock(assets: list[Asset], out: dict[str, dict]) -> None:
    rows = {r["name"]: r for r in mock.global_quotes()}
    for a in assets:
        if a.key in out:
            continue
        r = rows.get(a.name)
        if not r:
            continue
        d = _empty(a)
        d.update({"price": r["price"], "pct": r["pct"], "change": r["change"], "time": r["time"],
                  "source": "mock"})
        out[a.key] = d


async def quotes(force: bool = False) -> cache.Sourced:
    assets = GLOBAL_ASSETS

    async def _all():
        out: dict[str, dict] = {}
        for fn in (_fill_em, _fill_tx, _fill_sina, _fill_yahoo, _fill_stooq):
            try:
                await fn(assets, out)
            except Exception:  # noqa: BLE001
                continue
            if len(out) == len(assets):
                break
        # 在线模式下取不到的品种保持缺失（界面显示"—"并计入 missing），不再填样例价格冒充行情
        for a in assets:
            out.setdefault(a.key, {**_empty(a), "source": "none"})
        for d in out.values():
            if d.get("time") and _is_stale(d.get("time")):
                d["stale"] = True
        order = {a.key: i for i, a in enumerate(assets)}
        rows = sorted(out.values(), key=lambda d: order.get(d["key"], 99))
        used = sorted({d["source"] for d in rows if d.get("price") is not None})
        return {"items": rows, "sources_used": used,
                "missing": [a.name for a in assets if a.key not in out or out[a.key].get("price") is None]}

    async def _mock_only():
        out: dict[str, dict] = {}
        _fill_mock(assets, out)
        order = {a.key: i for i, a in enumerate(assets)}
        rows = sorted(out.values(), key=lambda d: order.get(d["key"], 99))
        return {"items": rows, "sources_used": ["mock"],
                "missing": [a.name for a in assets if a.key not in out]}

    providers = [("mock", _mock_only)] if settings.offline else [("multi", _all)]
    return await cache.chain(
        providers, cache_key="global:quotes", ttl=settings.ttl_global, force=force,
        validator=lambda r: bool(r) and bool(r.get("items")),
    )


# ---------------- 隔夜/外围信号解读 ----------------
def signals(items: list[dict]) -> dict:
    usable = [d for d in items if eligible_for_signal(d)]
    excluded = [d.get("key") for d in items if not eligible_for_signal(d)]
    m = {d["key"]: d for d in usable}
    sig: list[dict] = []

    def add(level: str, text: str, weight: int = 1) -> None:
        sig.append({"level": level, "text": text, "weight": weight})

    sox = (m.get("SOX") or {}).get("pct")
    if sox is not None:
        if sox >= 2:
            add("利好", f"费城半导体 +{sox:.2f}%，A股半导体/存储/设备大概率大幅高开，注意高开兑现风险", 3)
        elif sox >= 0.5:
            add("利好", f"费城半导体 +{sox:.2f}%，芯片链情绪偏暖", 2)
        elif sox <= -2:
            add("利空", f"费城半导体 {sox:.2f}%，A股芯片链承压，规避高位半导体", 3)

    hxc = (m.get("HXC") or {}).get("pct")
    if hxc is not None:
        if hxc >= 1.5:
            add("利好", f"中概金龙 +{hxc:.2f}%，港股与A股风险偏好回升", 2)
        elif hxc <= -1.5:
            add("利空", f"中概金龙 {hxc:.2f}%，外资情绪偏空，注意权重拖累", 2)

    ixic = (m.get("IXIC") or {}).get("pct")
    if ixic is not None:
        if ixic >= 1:
            add("利好", f"纳指 +{ixic:.2f}%，AI/算力/科技题材有外盘支撑", 2)
        elif ixic <= -1:
            add("利空", f"纳指 {ixic:.2f}%，成长股开盘承压", 2)

    a50 = (m.get("A50") or {}).get("pct")
    if a50 is not None:
        if a50 >= 0.5:
            add("利好", f"A50期货 +{a50:.2f}%，★A股高开概率大，竞价可积极参与", 3)
        elif a50 <= -0.5:
            add("利空", f"A50期货 {a50:.2f}%，★A股低开概率大，竞价谨慎、勿追高", 3)
        else:
            add("中性", f"A50期货 {a50:+.2f}%，开盘方向不明确，看竞价量能", 1)

    vix = (m.get("VIX") or {}).get("price")
    if vix is not None:
        if vix >= 30:
            add("利空", f"VIX={vix:.1f} 恐慌高位，全球risk-off，降低仓位", 3)
        elif vix >= 20:
            add("中性", f"VIX={vix:.1f} 偏高，注意波动放大", 1)
        elif vix < 14:
            add("利好", f"VIX={vix:.1f} 极低，风险偏好充分", 1)

    n225 = (m.get("N225") or {}).get("pct")
    ks11 = (m.get("KS11") or {}).get("pct")
    if n225 is not None and ks11 is not None:
        if n225 <= -1.5 or ks11 <= -1.5:
            add("利空", f"亚太走弱（日经{n225:+.2f}%/韩股{ks11:+.2f}%），区域风险偏好下行", 2)
        elif n225 >= 1 and ks11 >= 1:
            add("利好", f"亚太普涨（日经{n225:+.2f}%/韩股{ks11:+.2f}%），亚洲科技链共振", 2)

    cnh = (m.get("USDCNH") or {}).get("pct")
    if cnh is not None:
        if cnh >= 0.3:
            add("利空", f"离岸人民币贬 {cnh:.2f}%，警惕外资流出与权重护盘失败", 2)
        elif cnh <= -0.3:
            add("利好", f"离岸人民币升 {abs(cnh):.2f}%，利好外资回流与成长股", 2)

    udi = (m.get("UDI") or {}).get("pct")
    if udi is not None and udi >= 0.6:
        add("利空", f"美元指数 +{udi:.2f}%，压制有色/黄金/成长估值", 1)

    gc = (m.get("GC") or {}).get("pct")
    if gc is not None and gc >= 1.5:
        add("利好", f"黄金 +{gc:.2f}%，避险与贵金属板块有题材", 1)

    cl = (m.get("CL") or {}).get("pct")
    if cl is not None and abs(cl) >= 3:
        add("利空" if cl > 0 else "中性", f"原油 {cl:+.2f}%，关注石油石化/油运/航空成本传导", 1)

    hs = (m.get("HSTECH") or {}).get("pct")
    if hs is not None and hs >= 2:
        add("利好", f"恒生科技 +{hs:.2f}%，A股TMT/AI应用日内有联动", 1)

    score = sum(s["weight"] for s in sig if s["level"] == "利好") - sum(s["weight"] for s in sig if s["level"] == "利空")
    if score >= 5:
        overall, tip = "外围偏多", "开盘可积极，重点看竞价与主线延续"
    elif score >= 2:
        overall, tip = "外围中性偏多", "跟随主线做多，控制追高幅度"
    elif score <= -5:
        overall, tip = "外围偏空", "低开概率大，先观察半小时，勿在竞价抢筹"
    elif score <= -2:
        overall, tip = "外围中性偏空", "减仓接力，优先低位首板与超跌反抽"
    else:
        overall, tip = "外围中性", "以A股自身情绪与主线为准"
    return {"score": score, "overall": overall, "tip": tip, "signals": sig,
            "excluded": excluded, "usable_count": len(usable)}


def eligible_for_signal(item: dict) -> bool:
    """模拟、缺失或陈旧行情不得进入外围多空评分。"""
    return (
        item.get("price") is not None
        and item.get("source") not in ("mock", "none", "")
        and not item.get("stale")
    )


async def overview(force: bool = False) -> dict:
    q = await quotes(force=force)
    data = q.data or {"items": [], "sources_used": [], "missing": []}
    items = data.get("items") or []
    groups: dict[str, list[dict]] = {}
    for it in items:
        groups.setdefault(it["group"], []).append(it)
    return {
        "items": items,
        "groups": [{"name": k, "items": v} for k, v in groups.items()],
        "signal": signals(items),
        "sources_used": data.get("sources_used"),
        "missing": data.get("missing"),
        "meta": q.meta(),
    }