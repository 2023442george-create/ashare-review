"""龙虎榜服务：谁在买、买多少、是不是知名游资、次日胜率如何。"""
from __future__ import annotations

from typing import Any

from ..core import cache
from ..core.config import settings
from ..core.utils import code_to_symbol, fnum, last_trade_day, yi
from ..sources import akshare_source as aks
from ..sources import eastmoney as em
from ..sources import mock
from . import game_seats


def _norm_stock(r: dict) -> dict:
    code = str(r.get("SECURITY_CODE") or "")
    buy = fnum(r.get("BILLBOARD_BUY_AMT"), 0.0)
    sell = fnum(r.get("BILLBOARD_SELL_AMT"), 0.0)
    net = fnum(r.get("BILLBOARD_NET_AMT"), (buy or 0) - (sell or 0))
    return {
        "code": code,
        "symbol": code_to_symbol(code),
        "name": r.get("SECURITY_NAME_ABBR"),
        "close": fnum(r.get("CLOSE_PRICE")),
        "pct": fnum(r.get("CHANGE_RATE")),
        "turnover": fnum(r.get("TURNOVERRATE")),
        "amount": fnum(r.get("ACCUM_AMOUNT"), 0.0),
        "amount_yi": yi(fnum(r.get("ACCUM_AMOUNT"), 0.0)),
        "buy": buy, "sell": sell, "net": net,
        "buy_yi": yi(buy), "sell_yi": yi(sell), "net_yi": yi(net),
        "float_mv_yi": yi(fnum(r.get("FREE_MARKET_CAP"), 0.0)),
        "reason": r.get("EXPLANATION") or "",
        "d1_pct": fnum(r.get("D1_CLOSE_ADJCHRATE")),
        "d2_pct": fnum(r.get("D2_CLOSE_ADJCHRATE")),
        "d5_pct": fnum(r.get("D5_CLOSE_ADJCHRATE")),
        "deal_ratio": fnum(r.get("DEAL_AMOUNT_RATIO")),
        "net_ratio": fnum(r.get("DEAL_NET_RATIO")),
        "trade_id": str(r.get("TRADE_ID") or ""),
    }


def _norm_seat(r: dict, side: str) -> dict:
    dept = r.get("OPERATEDEPT_NAME") or ""
    hit = game_seats.match(dept)
    return {
        "code": str(r.get("SECURITY_CODE") or ""),
        "symbol": code_to_symbol(str(r.get("SECURITY_CODE") or "")),
        "trade_id": str(r.get("TRADE_ID") or ""),
        "dept": dept,
        "side": side,
        "buy": fnum(r.get("BUY"), 0.0),
        "sell": fnum(r.get("SELL"), 0.0),
        "net": fnum(r.get("NET"), 0.0),
        "net_yi": yi(fnum(r.get("NET"), 0.0)),
        "win_3day": fnum(r.get("RISE_PROBABILITY_3DAY")),
        "times_3day": int(fnum(r.get("TOTAL_BUYER_SALESTIMES_3DAY"), 0) or 0),
        "seat": hit["seat"] if hit else "",
        "tag": hit["tag"] if hit else "",
        "style": hit["style"] if hit else "",
        "next_hint": hit["next"] if hit else "",
        "noise": game_seats.is_noise(dept),
    }


async def _daily_em(date: str) -> dict | None:
    rows = await em.lhb_list(date)
    if not rows:
        return None
    buys, sells = await _seats_em(date)
    base = _pick_base_rows([_norm_stock(r) for r in rows])
    seats = dedupe_seats(buys + sells, {st["trade_id"] for st in base})
    by_code: dict[str, list[dict]] = {}
    for s in seats:
        by_code.setdefault(s["code"], []).append(s)
    items = []
    for st in base:
        cs = sorted(by_code.get(st["code"], []), key=lambda x: -abs(x.get("net") or 0))
        st["seats"] = cs[:10]
        known = [x for x in cs if x.get("seat")]
        st["known_seats"] = [{"seat": x["seat"], "tag": x["tag"], "net_yi": x["net_yi"],
                              "side": x["side"], "style": x["style"], "next_hint": x["next_hint"]} for x in known]
        st["known_net_yi"] = round(sum(x.get("net") or 0 for x in known) / 1e8, 2)
        st["game_tag"] = _game_tag(known)
        items.append(st)
    items.sort(key=lambda x: -(x.get("net") or 0))
    return {"date": date, "count": len(items), "items": items, "seat_rank": seat_rank_from(seats),
            "raw_seat_count": len(seats), "inst_net_yi": _dept_net_yi(seats, "机构专用", "机构投资者"),
            "north_net_yi": _dept_net_yi(seats, "股通专用")}


def _pick_base_rows(stocks: list[dict]) -> list[dict]:
    """同一只票因多个原因上榜时只保留一行，优先单日榜。

    "日涨幅偏离"是当日数据，"连续三日累计"覆盖三天且包含当日，两行相加会把当日算两遍。
    成交额最小的那行统计区间最短；其余原因只并入 reason。
    """
    by_code: dict[str, list[dict]] = {}
    for st in stocks:
        by_code.setdefault(st["code"], []).append(st)
    out = []
    for group in by_code.values():
        group.sort(key=lambda s: s.get("amount") or 0)
        keep = group[0]
        keep["reason"] = " / ".join(dict.fromkeys(s["reason"] for s in group if s["reason"]))
        out.append(keep)
    return out


def dedupe_seats(seats: list[dict], trade_ids: set[str]) -> list[dict]:
    """只保留选中榜单的席位，并去掉买卖榜里的重复行。

    同时进入买入前五和卖出前五的席位会在两张表里各出现一次，买卖金额完全相同，
    不去重净额就翻倍。多个"机构专用"是不同席位，金额不同，不会被去掉。
    """
    out, seen = [], set()
    for s in seats:
        key = (s["trade_id"], s["dept"], s["buy"], s["sell"])
        if s["trade_id"] in trade_ids and key not in seen:
            seen.add(key)
            out.append(s)
    return out


def _dept_net_yi(seats: list[dict], *keywords: str) -> float:
    return round(sum(s.get("net") or 0 for s in seats if any(k in (s.get("dept") or "") for k in keywords)) / 1e8, 2)


async def _seats_em(date: str) -> tuple[list[dict], list[dict]]:
    buys = await em.lhb_seats(date, "BUY")
    sells = await em.lhb_seats(date, "SELL")
    return [_norm_seat(r, "buy") for r in buys], [_norm_seat(r, "sell") for r in sells]


def _game_tag(known: list[dict]) -> str:
    tags = [k["tag"] for k in known if k.get("tag")]
    if not tags:
        return "无明显知名资金"
    if "顶级游资" in tags:
        return "顶级游资介入"
    if "一线游资" in tags:
        return "一线游资介入"
    if "机构" in tags and "散户大本营" in tags:
        return "机构与散户对手盘"
    if "散户大本营" in tags:
        return "散户大本营接盘（谨慎）"
    if "机构" in tags:
        return "机构主导"
    return "/".join(sorted(set(tags)))


def seat_rank_from(seats: list[dict]) -> list[dict]:
    """当日活跃营业部排行：谁在扫货、谁在出货。"""
    agg: dict[str, dict] = {}
    for s in seats:
        if not s.get("dept"):
            continue
        a = agg.setdefault(s["dept"], {
            "dept": s["dept"], "seat": s.get("seat") or "", "tag": s.get("tag") or "",
            "style": s.get("style") or "", "next_hint": s.get("next_hint") or "",
            "times": 0, "buy": 0.0, "sell": 0.0, "net": 0.0, "stocks": [],
        })
        a["times"] += 1
        a["buy"] += s.get("buy") or 0
        a["sell"] += s.get("sell") or 0
        a["net"] += s.get("net") or 0
        a["stocks"].append({"code": s["code"], "side": s["side"], "net_yi": s.get("net_yi")})
    out = list(agg.values())
    for a in out:
        a["buy_yi"] = round(a["buy"] / 1e8, 2)
        a["sell_yi"] = round(a["sell"] / 1e8, 2)
        a["net_yi"] = round(a["net"] / 1e8, 2)
        a.pop("buy", None); a.pop("sell", None); a.pop("net", None)
    out.sort(key=lambda x: -(x["net_yi"]))
    # 前 20 扫货、后 20 出货；只截头部会让净卖出的席位消失
    return out if len(out) <= 40 else out[:20] + out[-20:]


async def _daily_ak(date: str) -> dict | None:
    if not aks.available():
        return None
    rows = await aks.lhb(date)
    if not rows:
        return None
    items = []
    for r in rows:
        items.append({
            "code": str(r.get("代码") or ""), "symbol": code_to_symbol(str(r.get("代码") or "")),
            "name": r.get("名称"), "close": fnum(r.get("收盘价")), "pct": fnum(r.get("涨跌幅")),
            "net": fnum(r.get("龙虎榜净买额"), 0.0), "net_yi": yi(fnum(r.get("龙虎榜净买额"), 0.0)),
            "amount_yi": yi(fnum(r.get("龙虎榜成交额"), 0.0)),
            "reason": r.get("上榜原因") or "", "seats": [], "known_seats": [],
            "known_net_yi": 0, "game_tag": "",
        })
    items.sort(key=lambda x: -(x.get("net") or 0))
    return {"date": date, "count": len(items), "items": items, "seat_rank": []}


async def _daily_mock(date: str) -> dict:
    items = []
    seats = [_norm_seat({"SECURITY_CODE": c, "OPERATEDEPT_NAME": n, "BUY": b, "SELL": s, "NET": n_}, "buy")
             for n, b, s, n_, c in mock.SEATS]
    for r in mock.lhb():
        st = _norm_stock(r)
        st["seats"] = [x for x in seats if x["code"] == st["code"]]
        st["known_seats"] = [{"seat": x["seat"], "tag": x["tag"], "net_yi": x["net_yi"], "side": x["side"],
                              "style": x["style"], "next_hint": x["next_hint"]} for x in st["seats"] if x.get("seat")]
        st["known_net_yi"] = round(sum(x.get("net") or 0 for x in st["seats"] if x.get("seat")) / 1e8, 2)
        st["game_tag"] = _game_tag([x for x in st["seats"] if x.get("seat")])
        items.append(st)
    return {"date": date, "count": len(items), "items": items, "seat_rank": seat_rank_from(seats)}


REGISTRY = {"eastmoney": _daily_em, "akshare": _daily_ak, "mock": _daily_mock}


async def daily(date: str | None = None, force: bool = False) -> cache.Sourced:
    d = date or str(last_trade_day())
    ordered = cache.order_providers("lhb", REGISTRY)
    providers = [(name, (lambda dd=d, fn=fn: fn(dd))) for name, fn in ordered]
    return await cache.chain(
        providers, cache_key=f"lhb:{d}", ttl=settings.ttl_lhb, force=force,
        validator=lambda r: isinstance(r, dict) and r.get("items"),
    )