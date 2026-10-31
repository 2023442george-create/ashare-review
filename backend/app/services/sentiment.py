"""市场情绪服务：涨跌家数、涨停结构、连板高度、炸板率、次日溢价、情绪温度与周期阶段。

这是「游资复盘」的核心：不看指数看情绪，不看基本面看资金合力。
"""
from __future__ import annotations

from typing import Any

from ..core import cache, params, store
from ..core.config import settings
from ..core.utils import (current_trade_date, fnum, last_trade_day, normalize_date,
                          prev_trade_day, to_date)
from ..sources import eastmoney as em
from ..sources import mock
from . import limitup, validate as V


# ---------------- 涨跌家数（市场宽度） ----------------
async def _breadth_em(date: str | None = None) -> dict | None:
    data = await em.zdfenbu(date)
    if not isinstance(data, dict):
        return None
    # 东财涨跌分布的 date 参数并不生效，请求任何日期都返回最近交易日。
    # 必须校验源日期，否则历史广度会把最新一天冒充成目标日。
    asked = to_date(str(date)) if date else None
    src_d = to_date(str(data.get("qdate"))) if str(data.get("qdate") or "") not in ("", "0", "None") else None
    if asked and src_d and asked != src_d:
        return None
    fb = data.get("fenbu") or []
    if not fb:
        return None
    buckets: dict[int, int] = {}
    for item in fb:
        for k, v in item.items():
            try:
                buckets[int(k)] = int(fnum(v, 0) or 0)
            except ValueError:
                continue
    up = sum(v for k, v in buckets.items() if k >= 1)
    down = sum(v for k, v in buckets.items() if k <= -1)
    flat = buckets.get(0, 0)
    hist = [
        {"label": "涨停", "key": 11, "value": buckets.get(11, 0), "type": "limit_up"},
        {"label": ">9%", "key": 10, "value": buckets.get(10, 0), "type": "up"},
        {"label": "7~9%", "key": 9, "value": buckets.get(9, 0) + buckets.get(8, 0), "type": "up"},
        {"label": "5~7%", "key": 7, "value": buckets.get(7, 0) + buckets.get(6, 0), "type": "up"},
        {"label": "3~5%", "key": 5, "value": buckets.get(5, 0) + buckets.get(4, 0), "type": "up"},
        {"label": "1~3%", "key": 3, "value": buckets.get(3, 0) + buckets.get(2, 0), "type": "up"},
        {"label": "0~1%", "key": 1, "value": buckets.get(1, 0), "type": "up"},
        {"label": "平盘", "key": 0, "value": flat, "type": "flat"},
        {"label": "0~-1%", "key": -1, "value": buckets.get(-1, 0), "type": "down"},
        {"label": "-1~-3%", "key": -2, "value": buckets.get(-2, 0) + buckets.get(-3, 0), "type": "down"},
        {"label": "-3~-5%", "key": -4, "value": buckets.get(-4, 0) + buckets.get(-5, 0), "type": "down"},
        {"label": "-5~-7%", "key": -6, "value": buckets.get(-6, 0) + buckets.get(-7, 0), "type": "down"},
        {"label": "<-7%", "key": -9, "value": sum(buckets.get(k, 0) for k in (-8, -9, -10)), "type": "down"},
        {"label": "跌停", "key": -11, "value": buckets.get(-11, 0), "type": "limit_down"},
    ]
    return {
        "date": str(data.get("qdate") or ""),
        "up": up, "down": down, "flat": flat, "total": up + down + flat,
        "up_ratio": round(up / max(1, up + down) * 100, 2),
        "limit_up": buckets.get(11, 0),
        "limit_down": buckets.get(-11, 0),
        "gt5_up": sum(v for k, v in buckets.items() if k >= 5),
        "lt5_down": sum(v for k, v in buckets.items() if k <= -5),
        "histogram": hist,
    }


def _breadth_mock(date: str | None = None) -> dict:
    data = mock.zdfenbu()
    buckets: dict[int, int] = {}
    for item in data["fenbu"]:
        for k, v in item.items():
            buckets[int(k)] = int(v)
    up = sum(v for k, v in buckets.items() if k >= 1)
    down = sum(v for k, v in buckets.items() if k <= -1)
    return {
        "date": str(data["qdate"]), "up": up, "down": down, "flat": buckets.get(0, 0),
        "total": up + down + buckets.get(0, 0), "up_ratio": round(up / max(1, up + down) * 100, 2),
        "limit_up": buckets.get(11, 0), "limit_down": buckets.get(-11, 0),
        "gt5_up": sum(v for k, v in buckets.items() if k >= 5),
        "lt5_down": sum(v for k, v in buckets.items() if k <= -5),
        "histogram": [],
    }


async def breadth(force: bool = False, date: str | None = None) -> cache.Sourced:
    providers = [("eastmoney", lambda: _breadth_em(date)), ("mock", lambda: _breadth_mock(date))]
    return await cache.chain(
        providers, cache_key=f"breadth:{date or 'last'}", ttl=settings.ttl_pool, force=force,
        validator=lambda r: bool(r) and r.get("total", 0) > 100,
    )


# ---------------- 情绪温度评分 ----------------
def _clamp(v: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, v))


def score_components(m: dict[str, Any], sentiment_params: dict[str, Any] | None = None) -> tuple[list[dict], float]:
    """把各项情绪指标折算成 0-100 分并加权。阈值与权重全部来自 core/params。

    与旧版的两个实质差别：

    1. **溢价因子改用可成交口径。** 旧版用 `prev_premium`（昨日涨停股今日的收盘
       涨跌幅）。那个数对一只今天一字板封死的票是**拿不到的价格**——收盘价存在，
       但你全天都没有机会成交。用它当"打板次日收益"会系统性高估赚钱效应，
       在一字板密集的强势行情里高估得最厉害，恰好是最该谨慎的时候。
       现在改用 `tradable_premium`：只统计今日开盘确实可以买入的样本，
       从开盘价算到收盘价。原来的收盘口径降级为参考值，不参与评分。

    2. **样本量门槛。** 昨日涨停只有 9 只时，"平均溢价 6.1%" 可以由一只票决定。
       样本量低于 params.STATS.min_sample 时，该因子退回中性分并标 low_confidence，
       而不是让一个噪音数字去摆动 17% 的权重。

    返回的每个因子都带 weight，权重之和恒为 1（扰动后由 params 重新归一化）。
    """
    sp = sentiment_params or params.SENTIMENT
    min_n = int(params.STATS["min_sample"])

    zt = m.get("limit_up") or 0
    dt_n = m.get("limit_down") or 0
    zb_rate = m.get("broken_rate") or 0.0
    max_b = m.get("max_boards") or 0
    up_ratio = m.get("up_ratio") or 0.0
    promote = m.get("promote_rate")
    # 刻意不回退到 prev_premium：静默回退等于把刚修掉的口径泄漏又放回来。
    prem = m.get("tradable_premium")
    prem_n = int(m.get("tradable_premium_sample") or 0)

    c_zt = sp["limit_up"]
    s_zt = _clamp(zt / max(1e-6, c_zt["scale"]) * 100)

    c_mb = sp["max_boards"]
    ladder = {int(k): float(v) for k, v in (c_mb.get("ladder") or {}).items()}
    s_b = _clamp(ladder.get(min(max_b, max(ladder) if ladder else 0), c_mb["cap"]))

    c_zb = sp["broken_rate"]
    s_zb = _clamp(100 - zb_rate * c_zb["slope"])

    c_dt = sp["limit_down"]
    s_dt = c_dt["floor"]
    for threshold, val in c_dt["steps"]:
        if dt_n <= threshold:
            s_dt = val
            break
    s_dt = _clamp(s_dt)

    c_pr = sp["tradable_premium"]
    prem_low = prem is None or prem_n < min_n
    s_prem = c_pr["missing"] if prem_low else _clamp(c_pr["center"] + prem * c_pr["slope"])

    c_up = sp["up_ratio"]
    s_up = _clamp(up_ratio * c_up["slope"] - c_up["offset"])

    c_po = sp["promote_rate"]
    s_pro = c_po["missing"] if promote is None else _clamp(promote * c_po["slope"])

    comps = [
        {"key": "limit_up", "name": "涨停家数", "value": zt, "score": round(s_zt, 1),
         "weight": c_zt["weight"], "low_confidence": False,
         "tip": "≥90家为强，40家以下情绪偏弱"},
        {"key": "max_boards", "name": "最高连板", "value": max_b, "score": round(s_b, 1),
         "weight": c_mb["weight"], "low_confidence": False,
         "tip": "空间板高度决定接力资金的想象力，5板以上进入主升"},
        {"key": "broken_rate", "name": "炸板率", "value": zb_rate, "score": round(s_zb, 1),
         "weight": c_zb["weight"], "low_confidence": False, "unit": "%",
         "tip": "<20%封板坚决；>35%分歧巨大，次日易核按钮"},
        {"key": "limit_down", "name": "跌停家数", "value": dt_n, "score": round(s_dt, 1),
         "weight": c_dt["weight"], "low_confidence": False,
         "tip": "跌停>10家说明有系统性杀跌，先保命"},
        {"key": "tradable_premium", "name": "昨涨停可成交溢价", "value": prem,
         "score": round(s_prem, 1), "weight": c_pr["weight"], "unit": "%",
         "low_confidence": bool(prem_low), "sample": prem_n, "min_sample": min_n,
         "tip": ("只统计今日开盘能真正买入的样本（剔除开盘即封死），从开盘价算到收盘价。"
                 + (f"样本 {prem_n} < {min_n}，已退回中性分" if prem_low else "")) },
        {"key": "up_ratio", "name": "上涨家数占比", "value": up_ratio, "score": round(s_up, 1),
         "weight": c_up["weight"], "low_confidence": False, "unit": "%",
         "tip": "普涨(>60%)还是分化(<40%)，决定是做题材还是做龙头"},
        {"key": "promote_rate", "name": "涨停晋级率", "value": promote, "score": round(s_pro, 1),
         "weight": c_po["weight"], "low_confidence": promote is None, "unit": "%",
         "tip": "昨日涨停今日继续涨停的比例，>30%梯队健康"},
    ]
    wsum = sum(c["weight"] for c in comps) or 1.0
    total = sum(c["score"] * c["weight"] for c in comps) / wsum
    return comps, round(total, 1)


def score_band(m: dict[str, Any]) -> dict[str, Any]:
    """把全部阈值与权重整体扰动 ±N%，给出情绪分的区间而不是一个点。

    为什么要这么做：`62.3` 这个写法在暗示小数位有意义，而这些阈值全是人为拍的
    整数（90 家、1.7 倍、30% 封成比）。扰动区间让伪精度自己暴露——如果 ±20%
    扰动把分数从 62 推到 48~74，那么"今天 62 分比昨天 59 分好"就不是一个
    可成立的判断。这是过拟合检测里"参数高原 vs 参数尖峰"的最小可用版本。
    """
    f = float(params.STATS["perturb"])
    pts = []
    for factor in (1 - f, 1.0, 1 + f):
        sp = params.SENTIMENT if abs(factor - 1.0) < 1e-9 else params.perturbed(factor)["sentiment"]
        _, t = score_components(m, sp)
        pts.append(t)
    lo, hi = min(pts), max(pts)
    return {"point": pts[1], "lo": round(lo, 1), "hi": round(hi, 1),
            "width": round(hi - lo, 1), "perturb_pct": round(f * 100, 1),
            "params_version": params.PARAM_VERSION, "param_digest": params.digest(),
            "note": ("区间来自把全部阈值/权重同时扰动 ±"
                     f"{round(f * 100)}%。区间宽度大于两日分差时，日间比较没有意义。")}


def _factor_independence(history: list[dict[str, Any]]) -> dict[str, Any]:
    """用已落库的历史情绪快照，估计七个因子的有效自由度。

    为什么这件事必须量出来：涨停家数、最高连板、晋级率、上涨家数占比在 A 股里
    高度同向——情绪好的时候四个一起涨。如果有效自由度只有 1.x，那么给它们配
    0.18/0.15/0.10/0.15 这样精细的权重就是装饰，调权重调的是噪音而不是模型。
    需要历史快照才能算，所以刚开始运行时会返回"样本不足"，这本身就是诚实的输出。
    """
    keys = ("limit_up", "max_boards", "broken_rate", "limit_down",
            "prev_premium", "up_ratio", "promote_rate")
    series = {k: [h.get(k) for h in history] for k in keys}
    series = {k: v for k, v in series.items() if len([x for x in v if x is not None]) >= 10}
    if len(series) < 2:
        return {"effective_factors": None, "nominal_factors": len(keys),
                "sample": len(history),
                "note": ("历史情绪快照不足（需每个因子 ≥10 个交易日）。"
                         "这说明目前无法判断七因子加权是否属于伪精度——"
                         "继续每日运行即可自动积累。")}
    out = V.factor_independence(series)
    eff = out.get("effective_factors")
    if eff is not None:
        out["verdict"] = ("因子高度共线，加权细调属于伪精度" if eff < 2.5
                          else ("存在明显共线，建议合并部分因子" if eff < 4
                                else "因子相对独立，加权有意义"))
    return out


def temperature_label(score: float) -> dict:
    if score >= 85:
        return {"label": "极度亢奋", "color": "#ff3b3b", "phase_hint": "高潮", "advice": "情绪透支，只做龙头不追高，逐步兑现利润"}
    if score >= 70:
        return {"label": "主升发酵", "color": "#ff7a45", "phase_hint": "发酵", "advice": "赚钱效应扩散，可积极打板/半路，仓位6-8成"}
    if score >= 55:
        return {"label": "温和偏暖", "color": "#ffb020", "phase_hint": "修复", "advice": "选择性参与主线首板与二板，仓位4-6成"}
    if score >= 40:
        return {"label": "分歧震荡", "color": "#a0a8b8", "phase_hint": "分歧", "advice": "只做确定性龙头，减少接力，仓位3成以下"}
    if score >= 25:
        return {"label": "退潮降温", "color": "#40a9ff", "phase_hint": "退潮", "advice": "空仓或轻仓观望，等待跌停潮结束"}
    return {"label": "冰点", "color": "#36cfc9", "phase_hint": "冰点", "advice": "极度冰点往往是转折前夜，盯首板与放量止跌信号，可小仓试错"}


def detect_phase(score: float, prev_scores: list[float], m: dict[str, Any]) -> dict:
    """结合历史情绪曲线判断周期阶段：冰点 → 修复 → 发酵 → 高潮 → 退潮"""
    delta = round(score - prev_scores[-1], 1) if prev_scores else 0.0
    trend = "持平"
    if len(prev_scores) >= 2:
        trend = "上升" if score > prev_scores[-1] + 3 else ("下降" if score < prev_scores[-1] - 3 else "震荡")
    zb_rate = m.get("broken_rate") or 0
    max_b = m.get("max_boards") or 0
    if score < 28 and (m.get("limit_down") or 0) >= 8:
        phase, desc = "冰点", "跌停潮+情绪冰点，杀跌末期，等待第一根放量阳线"
    elif score < 40 and trend == "下降":
        phase, desc = "退潮", "情绪持续降温，高位股杀跌，接力胜率极低"
    elif score < 45 and trend == "上升":
        phase, desc = "修复", "情绪从冰点回暖，首板/低位反包开始有溢价"
    elif score >= 85 or max_b >= 7:
        phase, desc = "高潮", "空间板极高、涨停家数爆量，一致性最强也最危险"
    elif score >= 60 and zb_rate < 30:
        phase, desc = "发酵", "主线清晰、封板坚决，是游资最好的进攻窗口"
    else:
        phase, desc = "分歧", "涨跌互现、炸板偏多，需精选个股，忌满仓梭哈"
    return {"phase": phase, "desc": desc, "score_delta": delta, "trend": trend}


# ---------------- 昨日涨停今日表现 ----------------
def promotion_rates(prev_items: list[dict], today_items: list[dict]) -> dict:
    """晋级率必须按股票代码取交集，不能用“今日二板总数”直接除以昨日首板数。"""
    prev_codes = {i["code"] for i in prev_items}
    today_codes = {i["code"] for i in today_items}
    promoted = prev_codes & today_codes
    prev_first = {i["code"] for i in prev_items if (i.get("boards") or 1) <= 1}
    today_second = {i["code"] for i in today_items if (i.get("boards") or 1) == 2}
    promoted_first = prev_first & today_second
    return {
        "prev_limit_up": len(prev_items),
        "promoted": len(promoted),
        "promote_rate": round(len(promoted) / len(prev_items) * 100, 1) if prev_items else None,
        "prev_first": len(prev_first),
        "promoted_first": len(promoted_first),
        "first_promote_rate": round(len(promoted_first) / len(prev_first) * 100, 1) if prev_first else None,
        "promoted_codes": promoted,
    }


def _quote_open_entry(q: dict) -> tuple[float | None, float | None, bool]:
    """返回（隔夜高开%, 开盘买入至收盘%, 开盘是否已封死涨停）。"""
    prev = fnum(q.get("prev_close"))
    op = fnum(q.get("open"))
    close = fnum(q.get("price")) or fnum(q.get("close"))
    limit_up = fnum(q.get("limit_up"))
    if not prev or prev <= 0 or not op or op <= 0:
        return None, None, False
    gap = round((op / prev - 1) * 100, 2)
    ret = round((close / op - 1) * 100, 2) if close and close > 0 else None
    # 集合竞价直接顶到涨停价，开盘无法保证成交。
    sealed = bool(limit_up and op >= limit_up * 0.999)
    return gap, ret, sealed


async def prev_premium(prev_items: list[dict], today_items: list[dict], allow_live: bool = True) -> dict:
    from . import market as mkt
    from ..core.assets import Asset

    rates = promotion_rates(prev_items, today_items)
    promoted_codes = rates.pop("promoted_codes")
    if not prev_items:
        return {**rates, "avg_premium": None, "open_premium": None,
                "open_entry_return": None, "tradable_premium": None,
                "tradable_sample": 0, "premium_sample": 0, "stats": {},
                "red_ratio": None, "sample": [],
                "unbuyable_count": None, "premium_available": False,
                "premium_unavailable_reason": "前一交易日无涨停样本"}

    base = {
        **rates,
        "avg_premium": None, "open_premium": None, "open_entry_return": None,
        "tradable_premium": None, "tradable_sample": 0, "premium_sample": 0, "stats": {},
        "red_ratio": None, "sample": [], "unbuyable_count": None,
        "premium_available": False,
    }
    if not allow_live:
        return {**base, "premium_unavailable_reason": "历史日期缺少本地逐股 OHLC，不能用当前行情回填"}

    assets = [Asset(key=i["code"], name=i["name"], group="个股", tx=i.get("symbol"),
                    sina=i.get("symbol"), sina_kind="stock", em=None) for i in prev_items]
    q = await mkt.fetch_quotes(assets)
    quotes: dict[str, dict] = q.data or {}
    rows = []
    pcts = []
    gaps = []
    entries = []
    as_of = ""
    for i in prev_items:
        quote = quotes.get(i["code"]) or {}
        pct = fnum(quote.get("pct"))
        gap, entry, sealed = _quote_open_entry(quote)
        tradable_entry = entry is not None and not sealed
        if pct is not None:
            pcts.append(pct)
        if gap is not None:
            gaps.append(gap)
        if tradable_entry:
            entries.append(entry)
        as_of = str(quote.get("time") or as_of)
        rows.append({"code": i["code"], "name": i["name"], "pct": pct,
                     "open_gap": gap, "open_entry_pct": entry if tradable_entry else None,
                     "open_sealed": sealed, "promoted": i["code"] in promoted_codes})
    if not pcts:
        return {**base, "premium_unavailable_reason": "逐股行情缺失"}
    tradable = round(sum(entries) / len(entries), 2) if entries else None
    return {
        **base,
        "avg_premium": round(sum(pcts) / len(pcts), 2),
        "red_ratio": round(len([p for p in pcts if p > 0]) / len(pcts) * 100, 1),
        "open_premium": round(sum(gaps) / len(gaps), 2) if gaps else None,
        "open_entry_return": tradable,
        # 评分真正使用的口径：开盘确实能买进的样本，开盘价 -> 收盘价
        "tradable_premium": tradable,
        "tradable_sample": len(entries),
        "premium_sample": len(pcts),
        "unbuyable_count": len([r for r in rows if r["open_sealed"]]),
        "unbuyable_rate": round(len([r for r in rows if r["open_sealed"]]) / len(rows) * 100, 1) if rows else None,
        # 两个口径各自的完整统计画像：样本量、中位数、四分位、Bootstrap 95% 区间。
        # 没有区间的均值在这种厚尾小样本上基本无法解读。
        "stats": {
            "close_based": V.describe(pcts, label="昨涨停今日收盘涨跌幅（含买不到的样本）"),
            "tradable": V.describe(entries, label="昨涨停今日开盘可买入样本的日内收益"),
            "open_gap": V.describe(gaps, label="隔夜高开幅度"),
        },
        "sample_size": len(pcts), "quote_as_of": as_of,
        "premium_available": True, "premium_unavailable_reason": "",
        "method": ("评分口径=开盘可成交样本的开盘->收盘收益（剔除开盘即封死涨停者）；"
                   "收盘等权涨跌幅仅作参考，因为其中包含全天无法买入的票"),
        "sample": sorted(rows, key=lambda x: -(x["pct"] if x["pct"] is not None else -99))[:40],
    }


# ---------------- 主入口 ----------------
async def core(date: str | None = None, force: bool = False, save: bool = True) -> dict:
    d = normalize_date(date)
    historical = not limitup.history_depth_ok(d)
    zt = await limitup.pool("zt", d, force=force)
    zb = await limitup.pool("zb", d, force=force)
    dt = await limitup.pool("dt", d, force=force)
    br = await breadth(force=force, date=d)

    zt_items = (zt.data or {}).get("items") or []
    zb_items = (zb.data or {}).get("items") or []
    dt_items = (dt.data or {}).get("items") or []
    b = br.data or {}

    prev_d = normalize_date(prev_trade_day(to_date(d)))
    prev = await limitup.pool("zt", prev_d)
    prem = await prev_premium((prev.data or {}).get("items") or [], zt_items, allow_live=not historical)

    max_b = max([i.get("boards") or 1 for i in zt_items], default=0)
    lianban = [i for i in zt_items if (i.get("boards") or 1) >= 2]
    first_board = [i for i in zt_items if (i.get("boards") or 1) == 1]
    one_word = [i for i in zt_items if i.get("board_type") == "一字板"]
    late_board = [i for i in zt_items if i.get("board_type") == "尾盘板"]
    bad_board = [i for i in zt_items if i.get("board_type") == "烂板"]
    unknown_board = [i for i in zt_items if i.get("board_type") == "未知板型"]
    fund_total = sum(i.get("fund") or 0 for i in zt_items)
    seal_ratios = [i.get("seal_ratio") for i in zt_items if i.get("seal_ratio") is not None]

    zt_n = len(zt_items) or (b.get("limit_up") or 0)
    zb_n = len(zb_items)
    metrics = {
        "limit_up": zt_n,
        "limit_down": len(dt_items) or (b.get("limit_down") or 0),
        "broken": zb_n,
        "broken_rate": round(zb_n / max(1, zt_n + zb_n) * 100, 1),
        "seal_rate": round(zt_n / max(1, zt_n + zb_n) * 100, 1),
        "max_boards": max_b,
        "lianban_count": len(lianban),
        "first_board_count": len(first_board),
        "one_word_count": len(one_word),
        "late_board_count": len(late_board),
        "bad_board_count": len(bad_board),
        "unknown_board_count": len(unknown_board),
        "fund_total": round(fund_total, 0),
        "fund_total_yi": round(fund_total / 1e8, 2),
        "avg_seal_ratio": round(sum(seal_ratios) / len(seal_ratios), 2) if seal_ratios else None,
        "up": b.get("up"), "down": b.get("down"), "flat": b.get("flat"),
        "up_ratio": b.get("up_ratio"),
        "gt5_up": b.get("gt5_up"), "lt5_down": b.get("lt5_down"),
        "histogram": b.get("histogram") or [],
        "promote_rate": prem.get("promote_rate"),
        "first_promote_rate": prem.get("first_promote_rate"),
        # prev_premium 保留为"参考口径"（含买不到的样本），不参与评分
        "prev_premium": prem.get("avg_premium"),
        "open_premium": prem.get("open_premium"),
        "open_entry_return": prem.get("open_entry_return"),
        # 评分实际使用的可成交口径及其样本量
        "tradable_premium": prem.get("tradable_premium"),
        "tradable_premium_sample": prem.get("tradable_sample"),
        "premium_sample": prem.get("premium_sample"),
        "unbuyable_rate": prem.get("unbuyable_rate"),
        "prev_red_ratio": prem.get("red_ratio"),
        "prev_limit_up": prem.get("prev_limit_up"),
        "premium_available": prem.get("premium_available"),
    }

    comps, total = score_components(metrics)
    band = score_band(metrics)
    hist = store.load_sentiment_history(120)
    prev_scores = [h.get("score") for h in hist if h.get("trade_date") < d and isinstance(h.get("score"), (int, float))]
    phase = detect_phase(total, prev_scores[-5:], metrics)
    label = temperature_label(total)

    payload = {
        "date": normalize_date((zt.data or {}).get("date") or d),
        "prev_date": prev_d,
        "historical": historical,
        "score": total,
        "label": label["label"],
        "color": label["color"],
        "advice": label["advice"],
        "phase": phase,
        "metrics": metrics,
        "components": comps,
        "score_band": band,
        # 七个因子到底提供了多少独立信息——由历史情绪快照算出，不是声明
        "factor_independence": _factor_independence(hist),
        "low_confidence_factors": [c["key"] for c in comps if c.get("low_confidence")],
        "prev_premium_detail": prem,
        "score_history": [{"date": h["trade_date"], "score": h.get("score"), "limit_up": h.get("limit_up"),
                           "max_boards": h.get("max_boards"), "broken_rate": h.get("broken_rate"),
                           "premium": h.get("prev_premium")} for h in hist],
        "sources": {"limit_up": zt.source, "broken": zb.source, "limit_down": dt.source, "breadth": br.source},
        "data_quality": {
            "point_in_time": not historical,
            "premium_available": prem.get("premium_available"),
            "note": prem.get("premium_unavailable_reason") or "",
        },
    }
    # 查询历史日期不允许覆盖已存记录；只有最近收盘交易日的结果可落库。
    # 另外两种情况也不落库：
    # 1) 离线样例模式：样例数据写进历史会污染情绪周期曲线
    # 2) 涨停池与涨跌分布都没取到：此时分数是按"0 家涨停"算出来的假分，
    #    落库会覆盖当天的真实记录（例如盘中网络抖动的那一次刷新）
    real = {"none", "mock", ""}
    data_ok = zt.source not in real or br.source not in real
    payload["data_quality"]["saved"] = bool(save and not historical and data_ok and not settings.offline)
    if not data_ok and not settings.offline:
        payload["data_quality"]["note"] = (payload["data_quality"]["note"] + "；" if payload["data_quality"]["note"] else "") + \
            "涨停池与涨跌分布均不可用，本次分数不可信且未写入历史"
    if payload["data_quality"]["saved"]:
        store.save_sentiment(payload["date"], {
            "score": total, "limit_up": metrics["limit_up"], "limit_down": metrics["limit_down"],
            "broken": metrics["broken"], "broken_rate": metrics["broken_rate"], "max_boards": max_b,
            "lianban_count": metrics["lianban_count"], "up_ratio": metrics["up_ratio"],
            "prev_premium": metrics["prev_premium"], "promote_rate": metrics["promote_rate"],
            "phase": phase["phase"], "fund_total_yi": metrics["fund_total_yi"],
            "premium_available": metrics["premium_available"],
            "data_version": 2,
        })
    return payload