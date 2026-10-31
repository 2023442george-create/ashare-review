"""宏观水位服务：回答"现在市场整体贵不贵、热不热、钱多不多"。

为什么单独成一层：情绪/涨停/板块回答的是"今天怎么做"，以天为单位；
宏观水位回答的是"整体该积极还是防守"，以月、季度为单位。两者时间尺度不同，
混在一个分数里会互相淹没，所以宏观温度分独立计算、独立展示，不参与情绪分和选股评分。

本模块覆盖（指标清单第一批 P0 + 同一批数据顺带算出的 P1）：
- 估值分位：沪深300 / 中证全指 滚动 PE（中证官方口径）近 10 年分位；PB、股息率来自蛋卷
- 股债性价比 ERP = 1/PE(沪深300) − 10 年期国债收益率，近 10 年分位
- 10 年期国债收益率、中美 10 年利差
- 红利股息率差 = 中证红利股息率 − 10 年期国债收益率
- 成交额 20 日均值分位、两融余额分位（近约 2 年）
- 宽基 ETF 份额变化（上交所口径）
- 宏观温度分：上述分位等权平均（ERP 取反向）

与项目其它部分一致的三条约束：
1. 缺数据记 None 并写进 gaps，绝不按 0 计——0 分位会被读成"极度低估"
2. 分位一律由本模块用同一套算法、同一个窗口计算，不直接采用第三方给的分位
3. 温度分是经验规则输出，不是被验证过的择时信号
"""
from __future__ import annotations

import asyncio
import bisect
import datetime as dt
import math
import time
from typing import Any

from ..core import cache, store
from ..core.config import settings
from ..core.utils import fnum, last_trade_day, now_cn, prev_trade_day, to_date, yi
from ..sources import csindex, danjuan, sse
from ..sources import eastmoney as em

# 宏观参数刻意不放进 core/params.py：那里的参数指纹会写进结果账本，
# 宏观温度不参与选股信号，改这里的窗口不应让账本判定为"参数变更"。
MACRO_PARAMS: dict[str, Any] = {
    "valuation_years": 10,     # 估值 / ERP 分位窗口（年）
    "flow_days": 500,          # 成交额 / 两融分位窗口（交易日，约 2 年）
    "min_history": 250,        # 估值类少于这么多样本不给分位
    "min_flow_history": 120,   # 资金类少于这么多样本不给分位
    "yield_match_days": 7,     # ERP 对齐：PE 当天无国债数据时最多向前找几天
    "min_components": 3,       # 温度分至少需要几个组件才输出
    "etf_lags": (1, 5, 20),    # ETF 份额对比的交易日间隔
    "etf_lookback": 4,         # 某日 ETF 份额未公布时最多往前回退几个交易日
}

# 温度分档位：(上限, 名称, 解读)
TEMP_BANDS: tuple[tuple[float, str, str], ...] = (
    (20, "冰点", "估值与资金都处在历史低位，历史上多对应底部区域，适合分批布局而非离场"),
    (40, "偏冷", "整体偏便宜、资金不活跃，可以逐步提高权益仓位"),
    (60, "中性", "没有明显的高估或低估，仓位跟随情绪与主线即可"),
    (80, "偏热", "估值和资金热度偏高，新开仓注意节奏，留足回撤空间"),
    (101, "过热", "估值与杠杆资金都处在历史高位，历史上多对应阶段顶部区域，优先控制仓位"),
)

VALUATION_INDEXES: tuple[dict[str, str], ...] = (
    {"key": "csi300", "name": "沪深300", "cs": "000300", "dj": "SH000300"},
    {"key": "csiall", "name": "中证全指", "cs": "000985", "dj": "SH000985"},
)
DIVIDEND_INDEX = {"key": "csidiv", "name": "中证红利", "cs": "000922", "dj": "SH000922"}

# 上交所上市的主要宽基 ETF：(代码, 默认名称, 跟踪指数)。汇金等增持主要集中在这些产品。
BROAD_ETFS: tuple[tuple[str, str, str], ...] = (
    ("510300", "华泰柏瑞沪深300ETF", "沪深300"),
    ("510310", "易方达沪深300ETF", "沪深300"),
    ("510330", "华夏沪深300ETF", "沪深300"),
    ("510050", "华夏上证50ETF", "上证50"),
    ("510500", "南方中证500ETF", "中证500"),
    ("512100", "南方中证1000ETF", "中证1000"),
    ("588000", "华夏科创50ETF", "科创50"),
    ("512050", "华夏中证A500ETF", "中证A500"),
)
ETF_COVERAGE_NOTE = "仅统计上交所上市的宽基 ETF；深交所产品（如 159919 嘉实沪深300、159915 创业板ETF）暂未接入"


# =====================================================================
# 纯函数：不访问网络，单元测试直接覆盖
# =====================================================================
def percentile_rank(values: list[float | None], x: float | None, min_n: int | None = None) -> float | None:
    """x 在 values 中的历史分位（0~100）：values 里小于等于 x 的比例。

    样本不足 min_n 时返回 None：几十个点算出的"历史分位"没有意义，
    宁可显示"样本不足"，也不要给一个看起来很精确的数字。
    """
    vals = sorted(v for v in values if v is not None)
    need = MACRO_PARAMS["min_history"] if min_n is None else min_n
    if x is None or len(vals) < max(1, need):
        return None
    return round(bisect.bisect_right(vals, x) / len(vals) * 100, 1)


def quantile(values: list[float | None], q: float) -> float | None:
    """线性插值分位数（q 取 0~1）。用于在图上画 20% / 50% / 80% 参考线。"""
    vals = sorted(v for v in values if v is not None)
    if not vals:
        return None
    pos = q * (len(vals) - 1)
    lo, hi = math.floor(pos), math.ceil(pos)
    if lo == hi:
        return round(vals[lo], 4)
    return round(vals[lo] + (vals[hi] - vals[lo]) * (pos - lo), 4)


def tail_years(series: list[list], years: int) -> list[list]:
    """截取序列最后 years 年（以序列最后一个日期为终点）。series 为 [[YYYY-MM-DD, ...], ...] 升序。"""
    if not series:
        return []
    end = to_date(series[-1][0])
    if end is None:
        return series
    cutoff = (end - dt.timedelta(days=round(365.25 * years))).strftime("%Y-%m-%d")
    return [r for r in series if r[0] >= cutoff]


def downsample(series: list[list], max_points: int = 520) -> list[list]:
    """等间隔抽样给前端画图，始终保留最后一个点（最新值不能被抽掉）。"""
    if len(series) <= max_points:
        return series
    step = math.ceil(len(series) / max_points)
    out = series[::step]
    if out[-1] is not series[-1]:
        out.append(series[-1])
    return out


def align_erp(pe_series: list[list], yields: list[dict], max_gap_days: int | None = None) -> list[list]:
    """把 PE 序列和 10 年国债序列按日期对齐，算出 ERP 序列。

    返回 [[date, erp, earnings_yield, cn10y], ...]，单位均为 %。
    PE 当天没有国债数据（债市休市等）时，取之前最近的一天，但间隔超过
    max_gap_days 就放弃该点——拿一个月前的利率去算今天的 ERP 是错配。
    """
    gap = MACRO_PARAMS["yield_match_days"] if max_gap_days is None else max_gap_days
    ys = [(r["date"], r["cn10y"]) for r in yields if r.get("cn10y") is not None]
    ys.sort(key=lambda x: x[0])
    ydates = [d for d, _ in ys]
    out: list[list] = []
    for row in pe_series:
        d, pe = row[0], row[-1]
        if not pe or pe <= 0:
            continue
        i = bisect.bisect_right(ydates, d) - 1
        if i < 0:
            continue
        d0, d1 = to_date(ydates[i]), to_date(d)
        if d0 is None or d1 is None or (d1 - d0).days > gap:
            continue
        ey = 100.0 / pe
        out.append([d, round(ey - ys[i][1], 4), round(ey, 4), ys[i][1]])
    return out


def rolling_mean(values: list[float], n: int) -> list[float | None]:
    """简单移动平均，前 n-1 个位置为 None。"""
    out: list[float | None] = []
    s = 0.0
    for i, v in enumerate(values):
        s += v
        if i >= n:
            s -= values[i - n]
        out.append(s / n if i >= n - 1 else None)
    return out


def band_of(score: float | None) -> dict[str, str]:
    """温度分 → 档位名称与解读。"""
    if score is None:
        return {"label": "数据不足", "tip": "可用组件不足，暂不输出温度分"}
    for upper, label, tip in TEMP_BANDS:
        if score < upper:
            return {"label": label, "tip": tip}
    return {"label": TEMP_BANDS[-1][1], "tip": TEMP_BANDS[-1][2]}


def temperature(components: list[dict]) -> dict[str, Any]:
    """等权平均各组件的 heat（0~100，越高越热），缺失组件不参与平均。

    缺失组件被排除而不是按 0 或 50 计：按 0 会把温度拉成"冰点"，按 50 会制造
    虚假的"中性"。可用组件少于 min_components 时整体不出分。
    """
    used = [c for c in components if c.get("heat") is not None]
    missing = [c["name"] for c in components if c.get("heat") is None]
    if len(used) < MACRO_PARAMS["min_components"]:
        score = None
    else:
        score = round(sum(c["heat"] for c in used) / len(used), 1)
    return {"score": score, **band_of(score), "used": len(used), "total": len(components), "missing": missing}


def etf_changes(latest: dict[str, dict], lagged: dict[int, dict[str, dict]]) -> dict[str, Any]:
    """计算每只宽基 ETF 及每个跟踪指数合计的份额变化（单位：亿份）。

    latest : {代码: {shares_yi, name}}，最新统计日
    lagged : {间隔交易日数: {代码: {shares_yi}}}
    合计只加总"两个日期都有数据"的产品，避免某只缺数据时被当成份额骤降。
    """
    rows: list[dict] = []
    groups: dict[str, dict] = {}
    for code, default_name, track in BROAD_ETFS:
        cur = (latest.get(code) or {}).get("shares_yi")
        row: dict[str, Any] = {"code": code, "name": (latest.get(code) or {}).get("name") or default_name,
                               "track": track, "shares_yi": cur}
        g = groups.setdefault(track, {"track": track, "codes": []})
        g["codes"].append(code)
        for lag, snap in lagged.items():
            prev = (snap.get(code) or {}).get("shares_yi")
            chg = round(cur - prev, 4) if cur is not None and prev is not None else None
            row[f"chg_{lag}d"] = chg
            row[f"chg_{lag}d_pct"] = round(chg / prev * 100, 2) if chg is not None and prev else None
            if chg is not None:
                g[f"chg_{lag}d"] = round(g.get(f"chg_{lag}d", 0.0) + chg, 4)
                g[f"base_{lag}d"] = g.get(f"base_{lag}d", 0.0) + prev
        if cur is not None:
            g["shares_yi"] = round(g.get("shares_yi", 0.0) + cur, 4)
        rows.append(row)
    out_groups = []
    for g in groups.values():
        item = {"track": g["track"], "codes": g["codes"], "shares_yi": g.get("shares_yi")}
        for lag in lagged:
            chg, base = g.get(f"chg_{lag}d"), g.get(f"base_{lag}d")
            item[f"chg_{lag}d"] = chg
            item[f"chg_{lag}d_pct"] = round(chg / base * 100, 2) if chg is not None and base else None
        out_groups.append(item)
    return {"items": rows, "groups": out_groups}


# =====================================================================
# 离线样例：只在 REVIEW_OFFLINE=1 时启用（cache.filter_providers 保证）
# =====================================================================
def _mock_days(years: int = 10) -> list[str]:
    """生成最近 years 年的工作日日期，用于样例序列。"""
    end = now_cn().date()
    d = end - dt.timedelta(days=round(365.25 * years))
    out = []
    while d <= end:
        if d.weekday() < 5:
            out.append(d.strftime("%Y-%m-%d"))
        d += dt.timedelta(days=1)
    return out


def _mock_series(base: float, amp: float, period: float, phase: float = 0.0) -> list[list]:
    """确定性的正弦样例序列：同一天多次运行结果一致，方便演示与测试复现。"""
    days = _mock_days()
    return [[d, round(base + amp * math.sin(i / period + phase) + amp * 0.3 * math.sin(i / 37.0), 4)]
            for i, d in enumerate(days)]


def _mock_yields() -> list[dict]:
    """样例国债序列：中国 10 年从 3.3% 缓慢下行，美国 10 年在 1.5%~4.5% 间波动。"""
    days = _mock_days()
    n = len(days)
    return [{"date": d, "cn10y": round(3.3 - 1.6 * i / n + 0.1 * math.sin(i / 50), 4),
             "cn2y": round(2.6 - 1.2 * i / n, 4), "cn30y": round(3.8 - 1.7 * i / n, 4),
             "us10y": round(3.0 + 1.5 * math.sin(i / 300), 4), "us2y": round(2.5 + 2.0 * math.sin(i / 280), 4)}
            for i, d in enumerate(days)]


def _mock_eva() -> dict[str, dict]:
    return {"SH000300": {"name": "沪深300", "pe": 12.8, "pb": 1.38, "dividend_yield": 3.1},
            "SH000985": {"name": "中证全指", "pe": 17.9, "pb": 1.62, "dividend_yield": 2.2},
            "SH000922": {"name": "中证红利", "pe": 7.6, "pb": 0.78, "dividend_yield": 5.4}}


def _mock_etf(lag: int) -> dict[str, dict]:
    """样例 ETF 份额：lag 越大份额越少，模拟持续净申购。"""
    base = {"510300": 420, "510310": 380, "510330": 260, "510050": 300,
            "510500": 120, "512100": 90, "588000": 500, "512050": 210}
    return {c: {"name": None, "shares_yi": round(v * (1 - 0.004 * lag), 4)} for c, v in base.items()}


def _mock_margin() -> list[list]:
    return [[d, round(1.6e12 + 2.5e11 * math.sin(i / 90), 0)] for i, d in enumerate(_mock_days(2))]


# =====================================================================
# 取数：每类数据一条 failover 链（主源 → 备用 → 离线样例）
# =====================================================================
def _pe_years_range() -> tuple[str, str]:
    """估值历史的起止日期（YYYYMMDD），多取一个月余量以覆盖节假日。"""
    end = now_cn().date()
    start = end - dt.timedelta(days=round(365.25 * MACRO_PARAMS["valuation_years"]) + 31)
    return start.strftime("%Y%m%d"), end.strftime("%Y%m%d")


def _enough(rows: Any) -> bool:
    """历史序列至少要有 min_history 个点才算可用，否则让链路继续尝试下一个源。"""
    return isinstance(rows, list) and len(rows) >= MACRO_PARAMS["min_history"]


async def pe_series(idx: dict[str, str], force: bool = False) -> cache.Sourced:
    """某指数的滚动 PE 历史 [[date, pe], ...]。主源中证官网，备用蛋卷。"""
    async def _csindex() -> list[list]:
        start, end = _pe_years_range()
        rows = await csindex.index_perf(idx["cs"], start, end)
        return [[d, pe] for d, _close, pe in rows]

    async def _danjuan() -> list[list]:
        return tail_years(await danjuan.history(idx["dj"], "pe"), MACRO_PARAMS["valuation_years"])

    registry = {"csindex": _csindex, "danjuan": _danjuan,
                "mock": lambda: _mock_series(13 if idx["key"] == "csi300" else 18, 2.0, 160)}
    return await cache.chain(cache.order_providers("valuation", registry),
                             cache_key=f"macro:pe:{idx['key']}", ttl=settings.ttl_macro,
                             force=force, validator=_enough)


async def pb_series(idx: dict[str, str], force: bool = False) -> cache.Sourced:
    """某指数的 PB 历史。中证官网不提供 PB，只有蛋卷一个在线源。"""
    async def _danjuan() -> list[list]:
        return tail_years(await danjuan.history(idx["dj"], "pb"), MACRO_PARAMS["valuation_years"])

    registry = {"danjuan": _danjuan,
                "mock": lambda: _mock_series(1.4 if idx["key"] == "csi300" else 1.7, 0.2, 170, 0.5)}
    return await cache.chain(cache.order_providers("valuation", registry),
                             cache_key=f"macro:pb:{idx['key']}", ttl=settings.ttl_macro,
                             force=force, validator=_enough)


async def eva_snapshot(force: bool = False) -> cache.Sourced:
    """蛋卷当前估值快照（取股息率用）。"""
    registry = {"danjuan": danjuan.eva_list, "mock": _mock_eva}
    return await cache.chain(cache.order_providers("valuation", registry),
                             cache_key="macro:eva", ttl=settings.ttl_macro, force=force,
                             validator=lambda r: isinstance(r, dict) and len(r) > 0)


async def bond_series(force: bool = False) -> cache.Sourced:
    """中美国债收益率历史（约 10 年）。主源东财新版数据中心，备用旧版接口。"""
    registry = {"eastmoney": em.treasury_yield, "eastmoney_legacy": em.treasury_yield_legacy,
                "mock": _mock_yields}

    def valid(rows: Any) -> bool:
        # 行数够、且确实带回了中国 10 年期字段，才算可用
        return _enough(rows) and any(r.get("cn10y") is not None for r in rows[-30:])

    return await cache.chain(cache.order_providers("bond", registry),
                             cache_key="macro:bond", ttl=settings.ttl_macro, force=force, validator=valid)


async def margin_series(force: bool = False) -> cache.Sourced:
    """两融余额历史 [[date, 两融余额(元)], ...]，约 2 年。"""
    async def _em() -> list[list]:
        rows = await em.margin_history(MACRO_PARAMS["flow_days"])
        out = [[str(r.get("DIM_DATE", ""))[:10], fnum(r.get("RZRQYE"))] for r in rows]
        return sorted([r for r in out if r[0] and r[1]], key=lambda x: x[0])

    registry = {"eastmoney": _em, "mock": _mock_margin}
    return await cache.chain(cache.order_providers("margin", registry),
                             cache_key="macro:margin", ttl=settings.ttl_macro, force=force,
                             validator=lambda r: isinstance(r, list) and len(r) >= 20)


async def _etf_near(target: dt.date, lag_for_mock: int) -> tuple[str | None, dict[str, dict], str]:
    """取 target 当天的 ETF 份额；未公布则逐个交易日往前回退，返回 (实际日期, 数据, 来源)。"""
    if settings.offline:
        return target.strftime("%Y-%m-%d"), _mock_etf(lag_for_mock), "mock"
    codes = {c for c, _, _ in BROAD_ETFS}
    d = target
    for _ in range(MACRO_PARAMS["etf_lookback"] + 1):
        snap = await sse.etf_scale(d.strftime("%Y-%m-%d"))
        found = {k: v for k, v in snap.items() if k in codes}
        if found:
            return d.strftime("%Y-%m-%d"), found, "sse"
        d = prev_trade_day(d)
    return None, {}, "none"


async def etf_flows(force: bool = False) -> dict[str, Any]:
    """宽基 ETF 份额：最新统计日 + 1/5/20 个交易日前，计算份额变化。"""
    key = "macro:etf"
    if not force:
        hit = cache.cache_get(key)
        if hit is not None:
            return hit
    # 先定位最新一个已公布的统计日，再以它为基准往前数 1/5/20 个交易日
    latest_date, latest, src = await _etf_near(last_trade_day(), 0)
    if not latest_date:
        return {"items": [], "groups": [], "date": None, "source": "none", "dates": {},
                "coverage": ETF_COVERAGE_NOTE, "error": "上交所 ETF 份额接口无数据或不可达"}
    base = to_date(latest_date) or last_trade_day()
    lagged: dict[int, dict[str, dict]] = {}
    dates: dict[str, str | None] = {"latest": latest_date}
    lags = MACRO_PARAMS["etf_lags"]
    # 三个历史日期互不依赖，并发拉取
    results = await asyncio.gather(*[_etf_near(prev_trade_day(base, lag), lag) for lag in lags])
    for lag, (d, snap, _s) in zip(lags, results):
        lagged[lag] = snap
        dates[f"{lag}d"] = d
    out = {**etf_changes(latest, lagged), "date": latest_date, "dates": dates, "source": src,
           "coverage": ETF_COVERAGE_NOTE}
    cache.cache_set(key, out, settings.ttl_macro)
    return out


# =====================================================================
# 组装：各分项的"当前值 + 分位 + 解读"
# =====================================================================
def _valuation_item(idx: dict[str, str], pe_res: Any, pb_res: Any, eva: dict[str, dict],
                    gaps: list[str]) -> dict[str, Any]:
    """单个指数的估值卡片：PE/PB 当前值与近 10 年分位、股息率、画图用序列。"""
    item: dict[str, Any] = {"key": idx["key"], "name": idx["name"], "code": idx["cs"]}
    pe_rows = pe_res.data if isinstance(pe_res, cache.Sourced) and pe_res.data else []
    pe_rows = tail_years(pe_rows, MACRO_PARAMS["valuation_years"])
    if pe_rows:
        vals = [r[1] for r in pe_rows]
        item.update({"date": pe_rows[-1][0], "pe": pe_rows[-1][1], "pe_pct": percentile_rank(vals, vals[-1]),
                     "pe_q": {"q20": quantile(vals, .2), "q50": quantile(vals, .5), "q80": quantile(vals, .8)},
                     "pe_source": pe_res.source, "pe_n": len(vals), "pe_from": pe_rows[0][0],
                     "pe_series": downsample(pe_rows)})
    else:
        item.update({"pe": None, "pe_pct": None, "pe_source": "none"})
        gaps.append(f"{idx['name']} PE：所有源均不可用（{getattr(pe_res, 'error', '') or pe_res}）")
    pb_rows = pb_res.data if isinstance(pb_res, cache.Sourced) and pb_res.data else []
    if pb_rows:
        vals = [r[1] for r in pb_rows]
        item.update({"pb": pb_rows[-1][1], "pb_pct": percentile_rank(vals, vals[-1]), "pb_source": pb_res.source,
                     "pb_date": pb_rows[-1][0]})
    else:
        item.update({"pb": None, "pb_pct": None, "pb_source": "none"})
        gaps.append(f"{idx['name']} PB：蛋卷不可用（中证官网不提供 PB）")
    item["dividend_yield"] = (eva.get(idx["dj"]) or {}).get("dividend_yield")
    return item


def _erp_block(pe300: list[list], bonds: list[dict], gaps: list[str]) -> dict[str, Any]:
    """股债性价比：ERP 当前值、近 10 年分位与 20/50/80% 参考线。"""
    rows = tail_years(align_erp(pe300, bonds), MACRO_PARAMS["valuation_years"])
    if not rows:
        gaps.append("ERP：缺少沪深300 PE 或 10 年期国债数据，无法计算")
        return {"erp": None, "erp_pct": None, "series": []}
    vals = [r[1] for r in rows]
    return {
        "date": rows[-1][0], "erp": rows[-1][1], "earnings_yield": rows[-1][2], "cn10y": rows[-1][3],
        "erp_pct": percentile_rank(vals, vals[-1]),
        "q": {"q20": quantile(vals, .2), "q50": quantile(vals, .5), "q80": quantile(vals, .8)},
        "n": len(vals), "from": rows[0][0],
        "series": downsample([[r[0], r[1]] for r in rows]),
        "how": "ERP 越高，股票相对债券越便宜。历史上处于 80% 分位以上时多对应底部区域，20% 以下多对应过热",
    }


def _rates_block(bonds: list[dict], gaps: list[str]) -> dict[str, Any]:
    """利率：中国 10 年、美国 10 年、中美利差，及 20 个交易日变化（bp）。"""
    cn = [r for r in bonds if r.get("cn10y") is not None]
    if not cn:
        gaps.append("10 年期国债：东财新旧接口均不可用")
        return {"cn10y": None, "us10y": None, "spread": None, "series": []}
    last = cn[-1]
    prev20 = cn[-21] if len(cn) > 20 else None
    us = [r for r in bonds if r.get("us10y") is not None]
    us_last = us[-1]["us10y"] if us else None
    spread = round(last["cn10y"] - us_last, 4) if us_last is not None else None
    if us_last is None:
        gaps.append("美国 10 年期国债：数据缺失，中美利差无法计算")
    three_years = tail_years([[r["date"], r] for r in bonds], 3)
    series = [[d, r.get("cn10y"), r.get("us10y"),
               round(r["cn10y"] - r["us10y"], 4) if r.get("cn10y") is not None and r.get("us10y") is not None else None]
              for d, r in three_years]
    return {
        "date": last["date"], "cn10y": last["cn10y"], "cn2y": last.get("cn2y"), "cn30y": last.get("cn30y"),
        "cn10y_chg20_bp": round((last["cn10y"] - prev20["cn10y"]) * 100, 1) if prev20 else None,
        "us10y": us_last, "spread": spread,
        "series": downsample(series, 400),
        "how": "国债收益率下行利好股票估值（分母变小）；中美利差倒挂越深，人民币与外资流入压力越大",
    }


def _turnover_block(th: dict, gaps: list[str]) -> dict[str, Any]:
    """成交额：最新值、20 日均值及其近约 2 年分位。"""
    pts = [(r["date"], r["amount"]) for r in (th.get("items") or []) if r.get("amount")]
    if len(pts) < 20:
        gaps.append("成交额：K 线历史不足 20 日，无法计算 20 日均值")
        return {"ma20_yi": None, "pct": None}
    ma = rolling_mean([a for _, a in pts], 20)
    ma_vals = [v for v in ma if v is not None]
    return {
        "date": pts[-1][0], "latest_yi": yi(pts[-1][1]), "ma20_yi": yi(ma_vals[-1]),
        "pct": percentile_rank(ma_vals, ma_vals[-1], MACRO_PARAMS["min_flow_history"]),
        "n": len(ma_vals), "from": pts[0][0], "source": th.get("source"),
        "estimated": bool(th.get("estimated")),
        "series": downsample([[pts[i][0], yi(v)] for i, v in enumerate(ma) if v is not None], 300),
    }


def _margin_block(res: Any, gaps: list[str]) -> dict[str, Any]:
    """两融余额：最新值、20 日变化及近约 2 年分位。"""
    rows = res.data if isinstance(res, cache.Sourced) and res.data else []
    if not rows:
        gaps.append("两融余额：东财数据中心不可用")
        return {"balance_yi": None, "pct": None, "source": "none"}
    vals = [r[1] for r in rows]
    prev20 = rows[-21][1] if len(rows) > 20 else None
    return {
        "date": rows[-1][0], "balance_yi": yi(vals[-1]),
        "chg20_yi": yi(vals[-1] - prev20) if prev20 else None,
        "pct": percentile_rank(vals, vals[-1], MACRO_PARAMS["min_flow_history"]),
        "n": len(vals), "from": rows[0][0], "source": res.source,
        "series": downsample([[d, yi(v)] for d, v in rows], 300),
        "note": "占流通市值比需全A流通市值序列，暂未接入",
    }


def _components(val: list[dict], erp: dict, turnover: dict, margin: dict) -> list[dict]:
    """温度分的组成：每项给出当前值、分位和 heat（0~100，越高越热）。"""
    v300, vall = val[0], val[1]
    erp_pct = erp.get("erp_pct")
    return [
        {"key": "pe_csi300", "name": "沪深300 PE 分位", "value": v300.get("pe"), "unit": "倍",
         "pct": v300.get("pe_pct"), "heat": v300.get("pe_pct"), "window": "近10年", "source": v300.get("pe_source")},
        {"key": "pe_csiall", "name": "中证全指 PE 分位", "value": vall.get("pe"), "unit": "倍",
         "pct": vall.get("pe_pct"), "heat": vall.get("pe_pct"), "window": "近10年", "source": vall.get("pe_source")},
        # ERP 越高代表股票越便宜，所以热度取反
        {"key": "erp", "name": "股债性价比 ERP（反向）", "value": erp.get("erp"), "unit": "%",
         "pct": erp_pct, "heat": round(100 - erp_pct, 1) if erp_pct is not None else None,
         "window": "近10年", "source": "沪深300 PE + 10年国债"},
        {"key": "turnover", "name": "成交额 20 日均值分位", "value": turnover.get("ma20_yi"), "unit": "亿",
         "pct": turnover.get("pct"), "heat": turnover.get("pct"), "window": "近约2年", "source": turnover.get("source")},
        {"key": "margin", "name": "两融余额分位", "value": margin.get("balance_yi"), "unit": "亿",
         "pct": margin.get("pct"), "heat": margin.get("pct"), "window": "近约2年", "source": margin.get("source")},
    ]


def _summary(payload: dict) -> dict[str, Any]:
    """写入历史表的精简快照（不含序列），用于画温度分历史曲线。"""
    t = payload.get("temperature") or {}
    v = {i["key"]: i for i in payload.get("valuation") or []}
    return {
        "score": t.get("score"), "label": t.get("label"), "used": t.get("used"),
        "components": {c["key"]: {"value": c.get("value"), "pct": c.get("pct")} for c in payload.get("components") or []},
        "pe_csi300": (v.get("csi300") or {}).get("pe"), "pe_csiall": (v.get("csiall") or {}).get("pe"),
        "erp": (payload.get("erp") or {}).get("erp"), "cn10y": (payload.get("rates") or {}).get("cn10y"),
        "spread": (payload.get("rates") or {}).get("spread"),
    }


async def overview(force: bool = False) -> dict[str, Any]:
    """宏观水位总览：估值、ERP、利率、红利息差、资金、ETF 份额和温度分。"""
    from . import market  # 延迟导入：market 体量大，且只用到成交额历史

    key = "macro:overview"
    if not force:
        hit = cache.cache_get(key)
        if hit is not None:
            return {**hit, "meta": {**hit.get("meta", {}), "cached": True}}
    t0 = time.perf_counter()
    gaps: list[str] = []
    v300, vall = VALUATION_INDEXES
    # 所有原始数据互不依赖，并发拉取；单项失败以异常对象返回，不拖垮整页
    (pe300, peall, pb300, pball, eva_res, bond_res, th, margin_res, etf) = await asyncio.gather(
        pe_series(v300, force), pe_series(vall, force), pb_series(v300, force), pb_series(vall, force),
        eva_snapshot(force), bond_series(force),
        market.turnover_history(days=MACRO_PARAMS["flow_days"], force=force),
        margin_series(force), etf_flows(force),
        return_exceptions=True,
    )
    eva = eva_res.data if isinstance(eva_res, cache.Sourced) and eva_res.data else {}
    bonds = bond_res.data if isinstance(bond_res, cache.Sourced) and bond_res.data else []

    # 分项组装：每个函数都会把缺口写进 gaps
    valuation = [_valuation_item(v300, pe300, pb300, eva, gaps), _valuation_item(vall, peall, pball, eva, gaps)]
    pe300_rows = pe300.data if isinstance(pe300, cache.Sourced) and pe300.data else []
    erp = _erp_block(pe300_rows, bonds, gaps)
    rates = _rates_block(bonds, gaps)
    turnover = _turnover_block(th if isinstance(th, dict) else {}, gaps)
    margin = _margin_block(margin_res, gaps)
    if isinstance(etf, Exception):
        etf = {"items": [], "groups": [], "error": f"{type(etf).__name__}: {etf}", "coverage": ETF_COVERAGE_NOTE}
    if not etf.get("items") or all(r.get("shares_yi") is None for r in etf.get("items") or []):
        gaps.append("宽基 ETF 份额：" + (etf.get("error") or "无数据"))

    # 红利股息率差：中证红利股息率 − 10 年国债（只有当前值，暂无历史分位）
    div_yield = (eva.get(DIVIDEND_INDEX["dj"]) or {}).get("dividend_yield")
    dividend = {"name": DIVIDEND_INDEX["name"], "dividend_yield": div_yield, "cn10y": rates.get("cn10y"),
                "spread": round(div_yield - rates["cn10y"], 4) if div_yield is not None and rates.get("cn10y") is not None else None,
                "source": eva_res.source if isinstance(eva_res, cache.Sourced) else "none",
                "how": "红利股息率高出国债越多，高股息资产越有吸引力；息差收窄到 1% 以内通常意味着红利已不便宜"}
    if div_yield is None:
        gaps.append("中证红利股息率：蛋卷不可用，红利股息率差无法计算")

    components = _components(valuation, erp, turnover, margin)
    payload: dict[str, Any] = {
        "as_of": str(last_trade_day()),
        "temperature": temperature(components),
        "components": components,
        "valuation": valuation,
        "erp": erp,
        "rates": rates,
        "dividend": dividend,
        "flows": {"turnover": turnover, "margin": margin},
        "etf": etf,
        "gaps": gaps,
        "params": {k: v for k, v in MACRO_PARAMS.items() if not isinstance(v, tuple)},
        "disclaimer": "温度分是各指标历史分位的等权平均，属于经验规则，没有经过择时回测验证",
        "meta": {
            "sources": {
                "pe_csi300": getattr(pe300, "source", "none"), "pe_csiall": getattr(peall, "source", "none"),
                "pb": getattr(pb300, "source", "none"), "eva": getattr(eva_res, "source", "none"),
                "bond": getattr(bond_res, "source", "none"), "margin": getattr(margin_res, "source", "none"),
                "turnover": turnover.get("source"), "etf": etf.get("source"),
            },
            "elapsed_ms": round((time.perf_counter() - t0) * 1000, 1),
            "cached": False, "offline": settings.offline,
        },
    }
    # 只有真实数据才落库：离线样例写进历史表会污染温度曲线
    if not settings.offline and payload["temperature"]["used"] > 0:
        store.save_macro(payload["as_of"], _summary(payload))
    # 有缺口时只缓存 5 分钟：否则一次网络抖动会让整页"缺数据"挂 6 小时
    cache.cache_set(key, payload, settings.ttl_macro if not gaps else min(300, settings.ttl_macro))
    return payload


def history(days: int = 250) -> dict[str, Any]:
    """已落库的每日温度快照（定时任务 15:25 写入）。"""
    return {"items": store.load_macro_history(days)}


# =====================================================================
# 探针：在用户本机核对每个源"通没通、字段对不对"
# =====================================================================
async def _probe(name: str, coro: Any) -> dict[str, Any]:
    """执行一个探测协程，统一记录耗时与异常。"""
    t0 = time.perf_counter()
    try:
        info = await coro
        info.setdefault("ok", bool(info.get("rows")))
    except Exception as exc:  # noqa: BLE001 - 探针要把一切异常都报出来
        info = {"ok": False, "error": f"{type(exc).__name__}: {exc}"[:300]}
    info["name"] = name
    info["elapsed_ms"] = round((time.perf_counter() - t0) * 1000, 1)
    return info


async def probe() -> dict[str, Any]:
    """逐个数据源发一次最小请求，报告行数、样例与缺失字段。用于首次接入时核对接口。"""
    from ..core import http

    if settings.offline:
        return {"offline": True, "items": [], "note": "离线样例模式不访问网络，请关闭 REVIEW_OFFLINE 后再探测"}
    end = now_cn().date()
    start = (end - dt.timedelta(days=20)).strftime("%Y%m%d")

    async def p_csindex() -> dict:
        raw = await http.fetch_json(f"{csindex.HOST}/csindex-home/perf/index-perf", source="csindex",
                                    params={"indexCode": "000300", "startDate": start, "endDate": end.strftime("%Y%m%d")},
                                    headers=csindex.HEADERS)
        first = ((raw or {}).get("data") or [{}])[0] if isinstance(raw, dict) else {}
        rows = csindex.parse_index_perf(raw)   # 字段对不上会抛 CsindexParseError，探针会报出来
        return {"rows": len(rows), "sample": rows[-1] if rows else None, "raw_keys": sorted(first)[:20]}

    async def p_danjuan_list() -> dict:
        rows = await danjuan.eva_list()
        want = [DIVIDEND_INDEX["dj"]] + [i["dj"] for i in VALUATION_INDEXES]
        return {"rows": len(rows), "missing_codes": [c for c in want if c not in rows],
                "sample": rows.get("SH000300")}

    async def p_danjuan_hist() -> dict:
        rows = await danjuan.history("SH000300", "pb")
        return {"rows": len(rows), "sample": rows[-1] if rows else None}

    async def p_bond() -> dict:
        raw = await em.datacenter("RPTA_WEB_TREASURYYIELD", sort_columns="SOLAR_DATE", page_size=5)
        rows = em.parse_treasury(raw)
        first = raw[0] if raw else {}
        return {"rows": len(rows), "sample": rows[-1] if rows else None,
                "missing_fields": [k for k in em.TREASURY_FIELDS if k not in first] if first else list(em.TREASURY_FIELDS)}

    async def p_bond_legacy() -> dict:
        rows = await em.treasury_yield_legacy(pages=1, page_size=5)
        return {"rows": len(rows), "sample": rows[-1] if rows else None}

    async def p_sse() -> dict:
        d, snap, src = await _etf_near(last_trade_day(), 0)
        return {"rows": len(snap), "date": d, "source": src,
                "missing_codes": [c for c, _, _ in BROAD_ETFS if c not in snap],
                "sample": snap.get("510300")}

    async def p_margin() -> dict:
        rows = await em.margin_history(5)
        return {"rows": len(rows), "sample": {k: rows[0].get(k) for k in ("DIM_DATE", "RZRQYE")} if rows else None}

    items = await asyncio.gather(
        _probe("中证指数 index-perf（PE 主源）", p_csindex()),
        _probe("蛋卷 估值列表（股息率）", p_danjuan_list()),
        _probe("蛋卷 PB 历史", p_danjuan_hist()),
        _probe("东财 国债收益率（新版）", p_bond()),
        _probe("东财 国债收益率（旧版备用）", p_bond_legacy()),
        _probe("上交所 ETF 份额", p_sse()),
        _probe("东财 两融余额", p_margin()),
    )
    return {"offline": False, "items": list(items),
            "source_stats": {k: http.SOURCE_STATS.get(k) for k in ("csindex", "danjuan", "eastmoney", "sse")}}
