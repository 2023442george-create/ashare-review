"""涨跌停池服务：涨停/炸板/跌停明细 + 连板天梯 + 板型识别。

游资复盘的第一手材料：谁封板、几点封的、封单多大、炸了几次、几天几板、什么板块。
"""
from __future__ import annotations

from typing import Any

from ..core import cache
from ..core.config import settings
from ..core.utils import (code_to_symbol, current_trade_date, fnum, is_trade_day,
                          last_trade_day, normalize_date, prev_trade_day, to_date,
                          yyyymmdd)
from ..sources import akshare_source as aks
from ..sources import eastmoney as em
from ..sources import mock


def _fmt_time(v: Any) -> str:
    n = int(fnum(v, 0) or 0)
    if n <= 0:
        return ""
    s = str(n).zfill(6)
    return f"{s[:2]}:{s[2:4]}:{s[4:]}"


def _minutes(v: Any) -> int:
    """把 93012 转成当日分钟数（9*60+30=570）"""
    n = int(fnum(v, 0) or 0)
    if n <= 0:
        return 0
    s = str(n).zfill(6)
    return int(s[:2]) * 60 + int(s[2:4])


def board_type(first_min: int, last_min: int, broken: int, pct: float | None) -> str:
    # first_min=0 表示源未给首封时间，不能当成 09:25 前的一字板。
    if first_min <= 0:
        return "未知板型"
    if first_min <= 9 * 60 + 25 and broken == 0:
        return "一字板"
    if first_min <= 9 * 60 + 25 and broken > 0:
        return "T字板"
    if first_min <= 9 * 60 + 35:
        return "秒板"
    if last_min >= 14 * 60 + 45:
        return "尾盘板"
    if broken >= 2:
        return "烂板"
    return "换手板"


def _norm_em(r: dict, kind: str = "zt") -> dict:
    price = fnum(r.get("p"), 0.0, 0.001)
    amount = fnum(r.get("amount"), 0.0)
    fund = fnum(r.get("fund"), 0.0)
    ltsz = fnum(r.get("ltsz"), 0.0)
    fbt = _minutes(r.get("fbt"))
    lbt = _minutes(r.get("lbt"))
    broken = int(fnum(r.get("zbc"), 0) or 0)
    zt = r.get("zttj") or {}
    boards = int(fnum(r.get("lbc"), 1) or 1)
    pct = fnum(r.get("zdp"))
    code = str(r.get("c") or "")
    return {
        "code": code,
        "symbol": code_to_symbol(code),
        "name": r.get("n"),
        "price": price,
        "pct": pct,
        "amount": amount,
        "float_mv": ltsz,
        "total_mv": fnum(r.get("tshare"), 0.0),
        "turnover": fnum(r.get("hs")),
        "boards": boards,
        "days": int(fnum(zt.get("days"), boards) or boards),
        "cts": int(fnum(zt.get("ct"), boards) or boards),
        "first_time": _fmt_time(r.get("fbt")),
        "last_time": _fmt_time(r.get("lbt")),
        "first_min": fbt,
        "last_min": lbt,
        "fund": fund,
        "broken_times": broken,
        "industry": r.get("hybk") or "",
        "seal_ratio": round(fund / amount * 100, 2) if amount else None,
        "fund_mv_ratio": round(fund / ltsz * 100, 3) if ltsz else None,
        "board_type": board_type(fbt, lbt, broken, pct),
        "limit_price": fnum(r.get("ztp"), 0.0, 0.001) if kind == "zb" else price,
        "days_board": f"{zt.get('days', boards)}天{zt.get('ct', boards)}板",
    }


def _norm_ak(r: dict) -> dict | None:
    """akshare 涨停池字段名（中文）归一化"""
    code = str(r.get("代码") or "")
    if not code:
        return None
    fund = fnum(r.get("封板资金"), 0.0)
    amount = fnum(r.get("成交额"), 0.0)
    ltsz = fnum(r.get("流通市值"), 0.0)
    fbt = _minutes(str(r.get("首次封板时间") or "").replace(":", ""))
    lbt = _minutes(str(r.get("最后封板时间") or "").replace(":", ""))
    broken = int(fnum(r.get("炸板次数"), 0) or 0)
    boards = int(fnum(r.get("连板数"), 1) or 1)
    return {
        "code": code, "symbol": code_to_symbol(code), "name": r.get("名称"),
        "price": fnum(r.get("最新价")), "pct": fnum(r.get("涨跌幅")),
        "amount": amount, "float_mv": ltsz, "total_mv": fnum(r.get("总市值"), 0.0),
        "turnover": fnum(r.get("换手率")), "boards": boards, "days": boards, "cts": boards,
        "first_time": str(r.get("首次封板时间") or ""), "last_time": str(r.get("最后封板时间") or ""),
        "first_min": fbt, "last_min": lbt, "fund": fund, "broken_times": broken,
        "industry": r.get("所属行业") or "",
        "seal_ratio": round(fund / amount * 100, 2) if amount else None,
        "fund_mv_ratio": round(fund / ltsz * 100, 3) if ltsz else None,
        "board_type": board_type(fbt, lbt, broken, fnum(r.get("涨跌幅"))),
        "days_board": f"{boards}天{boards}板",
    }


async def _pool_em(kind: str, date: str | None):
    fn = {"zt": em.zt_pool, "zb": em.zb_pool, "dt": em.dt_pool}[kind]
    data = await fn(date)
    if not isinstance(data, dict) or ("pool" not in data and "tc" not in data):
        return None
    rows = data.get("pool") or []
    raw_qdate = data.get("qdate")
    asked_d = to_date(str(date)) if date else current_trade_date()
    if asked_d and not is_trade_day(asked_d):
        return None
    # 东财 qdate 恒为「最近交易日」，与 date 参数无关；业务日期必须以请求为准，
    # 否则所有历史日期的涨停池都会被判成「源日期不一致」而永久为空。
    return {
        "date": normalize_date(asked_d),
        "source_qdate": str(raw_qdate or ""),
        "total": int(fnum(data.get("tc"), len(rows)) or len(rows)),
        "items": [_norm_em(r, kind) for r in rows],
    }


async def _pool_ak(kind: str, date: str | None):
    if kind != "zt" or not aks.available():
        return None
    d = yyyymmdd(date)
    rows = await aks.zt_pool(d)
    items = [x for x in (_norm_ak(r) for r in rows) if x]
    return {"date": d, "total": len(items), "items": items} if items else None


async def _pool_mock(kind: str, date: str | None):
    data = {"zt": mock.zt_pool, "zb": mock.zb_pool, "dt": mock.dt_pool}[kind]()
    return {"date": str(data.get("qdate")), "total": data.get("tc", 0),
            "items": [_norm_em(r, kind) for r in data.get("pool") or []]}


REGISTRY = {"eastmoney": _pool_em, "akshare": _pool_ak, "mock": _pool_mock}


async def pool(kind: str = "zt", date: str | None = None, force: bool = False) -> cache.Sourced:
    kind = kind if kind in ("zt", "zb", "dt") else "zt"
    # 默认取「当前展示交易日」，盘中才能看到当天
    d = normalize_date(date or current_trade_date())
    ordered = cache.order_providers("limit_pool", REGISTRY)
    providers = [(name, _make(fn, kind, d)) for name, fn in ordered]
    return await cache.chain(
        providers, cache_key=f"pool:{kind}:{d}", ttl=settings.ttl_pool, force=force,
        validator=lambda r: isinstance(r, dict) and r.get("items") is not None,
    )


def _make(fn, kind: str, date: str):
    async def _call():
        return await fn(kind, date)
    return _call


async def ladder(date: str | None = None, force: bool = False) -> dict:
    """连板天梯：按连板高度分层，展示市场高度与断层。"""
    res = await pool("zt", date, force=force)
    items = (res.data or {}).get("items") or []
    levels: dict[int, list[dict]] = {}
    for it in items:
        levels.setdefault(max(1, int(it.get("boards") or 1)), []).append(it)
    max_b = max(levels) if levels else 0
    out = []
    for b in sorted(levels, reverse=True):
        rows = sorted(levels[b], key=lambda x: -(x.get("fund") or 0))
        out.append({
            "boards": b,
            "count": len(rows),
            "stocks": [{
                "code": r["code"], "name": r["name"], "industry": r["industry"],
                "fund": r["fund"], "seal_ratio": r["seal_ratio"], "board_type": r["board_type"],
                "first_time": r["first_time"], "turnover": r["turnover"],
                "float_mv": r["float_mv"], "days_board": r["days_board"],
            } for r in rows],
        })
    # 断层检测：某高度为 0 而更低高度仍有票 → 空间板断层，晋级难度大
    gaps = [b for b in range(2, max_b) if b not in levels]
    return {
        "date": (res.data or {}).get("date"),
        "max_boards": max_b,
        "levels": out,
        "gaps": gaps,
        "source": res.source,
        "comment": _ladder_comment(max_b, gaps, len(items)),
    }


def history_depth_ok(date: str | None, days: int = 1) -> bool:
    """目标日是否仍可由「当前实时行情」代表。

    实时行情只对应一个交易日：正在进行的当天，或最近已收盘日。更早的日期必须
    先有本地逐股历史行情，否则禁止用实时行情冒充历史。
    """
    return normalize_date(date) == normalize_date(current_trade_date())


def _ladder_comment(max_b: int, gaps: list[int], zt_count: int) -> str:
    if max_b <= 0:
        return "无涨停，市场冰点，空仓等待"
    if max_b >= 7:
        return f"空间板已到{max_b}板，情绪高位，龙头一致性极强但接力风险同步放大"
    if gaps:
        return f"最高{max_b}板，但{','.join(str(g) for g in gaps)}板断层，晋级通道不畅，谨慎追高"
    if max_b >= 4:
        return f"最高{max_b}板，梯队完整无断层，情绪处于发酵/主升阶段"
    if zt_count >= 60:
        return f"最高{max_b}板但涨停{zt_count}家，属于「广度好、高度差」的普涨轮动行情，做首板优于做接力"
    return f"最高{max_b}板，高度不足，情绪偏弱，以低吸首板为主"


async def prev_pool(kind: str = "zt", n: int = 1) -> cache.Sourced:
    d = str(prev_trade_day(last_trade_day(), n))
    return await pool(kind, d)