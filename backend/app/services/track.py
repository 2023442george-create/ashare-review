"""结果账本：把今天的信号冻住，等未来把结果填回来。

为什么这个模块是整个研究体系的地基？

一个每天产出候选股、但从不记录候选股后来怎么样的系统，不管界面做得多好，
都不是研究工具——它没有产生任何可被检验的东西。而前瞻样本有三个性质决定了
它必须**最先**被建立：

1. **它是免费的**：只要每天收盘后写一行记录，不需要买任何历史数据库。
2. **它无法被事后篡改**：冻结时间戳 + 参数指纹写进去之后，就不能再回头
   "换个阈值重算一遍"。这恰恰是回测最容易作弊的地方（事后调参）。
3. **它不能补**：历史行情可以买，但"当时这套规则会选哪些票"永远无法重建——
   因为当时的板块成分、主线判定、龙虎榜披露状态都已经变了。今天不冻，
   这一天的样本就永久消失。

因此本模块只做三件事：
- `freeze()`  收盘后冻结当日全部可选标的（含未选中的，供置换检验做零分布）
- `settle()`  用次一交易日开盘价入场、T+N 收盘价出场，扣费后与基准相减
- `record()`  汇总成带样本量、区间、p 值与不可成交率的战绩表

两个刻意的设计选择：
- 入场价**固定为次日开盘**，不用候选日收盘价。候选日收盘价是做决策时已知的
  价格，但那一刻市场已经关门，买不到。用它算收益是最常见的前视偏差。
- 开盘即封死涨停的样本标为 `tradable=0`，并在汇总时从正文统计里剔除、单独
  报告剔除比例。买不到的收益不是收益。
"""
from __future__ import annotations

import asyncio
import datetime as dt
from typing import Any

from ..core import cache, params, regime, store
from ..core.config import settings
from ..core.utils import code_to_symbol, is_trade_day, normalize_date, now_cn, to_date
from . import market, screener, validate as V

RULE_VERSION = "track-v1"
HORIZONS = (1, 2, 5, 10)
TRACKED_STRATEGIES = ("first_board", "relay", "main_line", "game_money")

# 基准：题材/小盘股的真实 beta 对标。
# 用上证指数做基准会系统性高估短线策略——权重股和游资票根本不是一个风险敞口。
PRIMARY_BENCHMARK = "sz399303"      # 国证2000
FALLBACK_BENCHMARK = "sh000852"     # 中证1000

# 结果可报的最低积累量（交易日数）。低于此值只允许称"正在积累"，不得给出结论。
MIN_DAYS_PRELIMINARY = 20
MIN_DAYS_EVIDENCE = 60


def total_cost_pct() -> float:
    """单次完整买卖的成本（百分比）。参数来自 core/params.COST，可版本化、可压力测试。"""
    c = params.COST
    bps = (c["commission_bps"] * 2 + c["transfer_bps"] * 2
           + c["stamp_duty_bps"] + c["slippage_bps"] * 2)
    return round(bps / 100.0, 4)


def _is_closed(d: str) -> bool:
    """目标交易日是否已收盘。盘中禁止冻结，否则冻的是半天的数据。"""
    now = now_cn()
    target = to_date(normalize_date(d))
    if not target:
        return False
    if target < now.date():
        return True
    return target == now.date() and now.hour * 60 + now.minute >= 15 * 60 + 5


# ---------------------------------------------------------------- 冻结
def _payload_of(item: dict[str, Any]) -> dict[str, Any]:
    """只保留做决策时真实可见的字段，避免把后验信息一起冻进去。"""
    keys = ("symbol", "boards", "days_board", "industry", "board_type", "first_time",
            "seal_ratio", "turnover", "fund_yi", "amount_yi", "float_mv_yi",
            "broken_times", "pct", "price", "why", "line", "risk")
    return {k: item.get(k) for k in keys if item.get(k) is not None}


async def freeze(date: str | None = None, strategies: tuple[str, ...] | None = None) -> dict[str, Any]:
    """冻结某交易日的信号。幂等：重跑只更新内容，不改写首次 frozen_at。"""
    target = normalize_date(date)
    if not _is_closed(target):
        return {"ok": False, "date": target, "frozen": 0,
                "reason": "目标交易日尚未收盘（15:05 前），盘中冻结会把未定型的数据写进账本"}
    if not is_trade_day(to_date(target) or dt.date.today()):
        return {"ok": False, "date": target, "frozen": 0, "reason": "非交易日"}

    pv, pd_ = params.PARAM_VERSION, params.digest()
    out: dict[str, Any] = {"ok": True, "date": target, "param_version": pv,
                           "param_digest": pd_, "rule_version": RULE_VERSION, "strategies": {}}
    total = 0
    for s in (strategies or TRACKED_STRATEGIES):
        try:
            res = await screener.run(s, target, include_universe=True)
        except Exception as exc:  # noqa: BLE001
            out["strategies"][s] = {"error": f"{type(exc).__name__}: {exc}"[:160]}
            continue
        uni = res.get("universe") or []
        top_n = int(res.get("track_top_n") or 10)
        if not uni:
            out["strategies"][s] = {"universe": 0, "selected": 0,
                                    "note": "当日该策略无可选标的，不写入账本"}
            continue
        rows = []
        for i, it in enumerate(uni):
            code = str(it.get("code") or "")
            if not code:
                continue
            rows.append({"code": code, "name": it.get("name") or "",
                         "selected": i < top_n, "rank": i + 1,
                         "score": it.get("score"), "payload": _payload_of(it)})
        n = store.freeze_signals(target, s, rows, pv, pd_, RULE_VERSION)
        total += n
        out["strategies"][s] = {"universe": len(rows), "selected": min(top_n, len(rows))}
    out["frozen"] = total
    out["note"] = ("已冻结当日『规则可见的全部标的』并标记选中与否。"
                   "未选中的记录是置换检验的零分布来源，不可省略。")
    return out


# ---------------------------------------------------------------- 结算
def _index_by_date(rows: list[list]) -> dict[str, int]:
    return {str(r[0])[:10]: i for i, r in enumerate(rows)}


async def _klines_for(codes: list[str], days: int) -> dict[str, list[list]]:
    """并发拉取逐股日线，带并发上限，避免把源打挂。"""
    sem = asyncio.Semaphore(max(2, min(8, settings.concurrency)))

    async def one(code: str):
        async with sem:
            try:
                res = await market.kline(code_to_symbol(code), days)
                return code, (res.data or []), res.source
            except Exception:  # noqa: BLE001
                return code, [], "none"

    got = await asyncio.gather(*(one(c) for c in codes))
    return {c: rows for c, rows, _src in got if rows}


async def settle(date: str | None = None, horizons: tuple[int, ...] = HORIZONS,
                 max_dates: int = 30, strategy: str | None = None) -> dict[str, Any]:
    """用真实的次日开盘/T+N 收盘回填结果。

    已结算的记录会被重算覆盖（价格源可能先缺后有），但 `frozen_at` 不受影响，
    因此"信号是什么时候定下的"始终可审计。

    strategy 可限定只结算某一个策略。用途：改了成本模型后只重算受影响的那部分，
    而不是把整个账本推倒重来。
    """
    dates = [normalize_date(date)] if date else store.signal_dates()[-max_dates:]
    if not dates:
        return {"ok": False, "settled": 0, "reason": "账本为空，先执行 freeze"}

    sigs: list[dict[str, Any]] = []
    for d in dates:
        sigs.extend(store.load_signals(d, strategy))
    if not sigs:
        return {"ok": False, "settled": 0, "reason": "这些日期没有冻结记录"}

    oldest = to_date(min(s["trade_date"] for s in sigs)) or dt.date.today()
    span = (dt.date.today() - oldest).days
    days = max(60, min(500, span + max(horizons) * 3 + 30))

    codes = sorted({str(s["code"]) for s in sigs})
    bench = await market.kline(PRIMARY_BENCHMARK, days)
    bench_rows = bench.data or []
    bench_name = PRIMARY_BENCHMARK
    if not bench_rows:
        bench = await market.kline(FALLBACK_BENCHMARK, days)
        bench_rows = bench.data or []
        bench_name = FALLBACK_BENCHMARK
    bidx = _index_by_date(bench_rows)

    kl = await _klines_for(codes, days)
    cost = total_cost_pct()
    cost_digest = params.digest({"cost": params.COST})
    out_rows: list[dict[str, Any]] = []
    skipped = {"no_kline": 0, "date_missing": 0, "not_due": 0}

    for s in sigs:
        code = str(s["code"])
        rows = kl.get(code)
        if not rows:
            skipped["no_kline"] += 1
            continue
        idx = _index_by_date(rows)
        d = s["trade_date"]
        i = idx.get(d)
        if i is None:
            skipped["date_missing"] += 1
            continue
        if i + 1 >= len(rows):
            skipped["not_due"] += 1
            continue
        entry_row = rows[i + 1]
        entry_date, entry_open = str(entry_row[0])[:10], entry_row[1]
        prev_close = rows[i][2]
        lim = regime.is_limit_up_price(entry_open, prev_close, code, entry_date)
        tradable = not (lim.get("matched") is True)
        reason = "" if tradable else f"次日开盘即封死涨停（{lim.get('pct')}% 档），开盘无法成交"
        if lim.get("matched") is None:
            reason = f"涨跌幅档位不确定（{lim.get('reason','')}），可成交性未知"

        bi = bidx.get(d)
        for h in horizons:
            j = i + h
            if j >= len(rows):
                continue
            exit_row = rows[j]
            if not entry_open or entry_open <= 0:
                continue
            gross = (exit_row[2] / entry_open - 1) * 100
            net = gross - cost
            base = None
            if bi is not None and bi + 1 < len(bench_rows) and bi + h < len(bench_rows):
                b_entry = bench_rows[bi + 1][1]
                b_exit = bench_rows[bi + h][2]
                if b_entry and b_entry > 0:
                    base = (b_exit / b_entry - 1) * 100
            out_rows.append({
                "trade_date": d, "strategy": s["strategy"], "code": code, "horizon": h,
                "entry_date": entry_date, "entry_price": round(entry_open, 4),
                "exit_date": str(exit_row[0])[:10], "exit_price": round(exit_row[2], 4),
                "ret_pct": round(gross, 4), "ret_net_pct": round(net, 4),
                "base_ret_pct": round(base, 4) if base is not None else None,
                "excess_pct": round(net - base, 4) if base is not None else None,
                "tradable": None if lim.get("matched") is None else tradable,
                "reason": reason, "benchmark": bench_name,
                "price_source": f"kline:{bench.source}:qfq", "cost_digest": cost_digest,
            })

    n = store.save_outcomes(out_rows) if out_rows else 0
    return {
        "ok": True, "dates": dates, "strategy": strategy or "all",
        "codes": len(codes), "settled": n,
        "skipped": skipped, "benchmark": bench_name,
        "cost_pct": cost, "cost_digest": cost_digest,
        "method": {
            "entry": "候选日次一交易日开盘价（决策后第一个真实可成交价）",
            "exit": "候选日 + N 个交易日的收盘价",
            "cost": f"买卖合计 {cost}%（佣金/过户费/印花税/滑点，见 params.COST）",
            "benchmark": f"{bench_name} 同期同口径收益，逐样本相减",
            "price_basis": "前复权日线；若入场与出场之间发生分红除权，复权口径一致不影响收益，但涨停价判定可能偏差",
            "untradable": "次日开盘即封死涨停的样本标 tradable=0，汇总时从正文剔除并单独报告比例",
        },
    }


# ---------------------------------------------------------------- 汇总
def _split(rows: list[dict[str, Any]], field: str = "excess_pct") -> tuple[list[float], list[float]]:
    sel = [r[field] for r in rows if r.get("selected") and r.get(field) is not None]
    uni = [r[field] for r in rows if r.get(field) is not None]
    return sel, uni


def record(strategy: str = "first_board", horizon: int = 1,
           include_untradable: bool = False, force: bool = False) -> dict[str, Any]:
    """战绩表：样本量、中位数、Bootstrap 区间、分层单调性、分层置换 p 值、不可成交率。

    注意报的是**扣费后的超额收益**（excess_pct），不是毛收益。
    毛收益在短线策略里几乎总是正的（小盘股 beta + 普涨），没有判别力。
    """
    # 置换检验是 CPU 密集的（默认 5000 次重抽样），账本一天只变一次，必须缓存。
    ck = f"track:record:{strategy}:{horizon}:{int(include_untradable)}:{params.digest()}"
    if not force:
        hit = cache.cache_get(ck)
        if hit is not None:
            return hit

    rows = store.load_outcomes(strategy, horizon)
    if not rows:
        empty = {"strategy": strategy, "horizon": horizon, "n": 0, "n_selected": 0,
                 "days": 0, "stage": "no_ledger",
                 "note": "该策略该持有期尚无结算记录；先 freeze 再 settle"}
        cache.cache_set(ck, empty, settings.ttl_daily)
        return empty

    untradable = [r for r in rows if r.get("tradable") == 0]
    unknown = [r for r in rows if r.get("tradable") is None]
    usable = rows if include_untradable else [r for r in rows if r.get("tradable") == 1]

    sel, uni = _split(usable)
    dates = sorted({r["trade_date"] for r in usable})
    by_date: dict[str, dict[str, list[float]]] = {}
    for r in usable:
        if r.get("excess_pct") is None:
            continue
        g = by_date.setdefault(r["trade_date"], {"selected": [], "universe": []})
        g["universe"].append(r["excess_pct"])
        if r.get("selected"):
            g["selected"].append(r["excess_pct"])
    groups = [g for g in by_date.values() if g["selected"] and len(g["universe"]) > len(g["selected"])]

    perm = V.stratified_permutation_test(groups)
    quint = V.quintile_spread([(r.get("score"), r.get("excess_pct")) for r in usable])
    sel_stat = V.describe(sel, label="选中组·扣费后超额")
    uni_stat = V.describe(uni, label="同日可选池·扣费后超额")
    gross_stat = V.describe([r["ret_net_pct"] for r in usable if r.get("selected")],
                            label="选中组·扣费后毛收益（未扣基准）")

    days = len(dates)
    if days < MIN_DAYS_PRELIMINARY:
        stage, stage_cn = "collecting", f"积累中（{days}/{MIN_DAYS_PRELIMINARY} 个交易日）"
    elif days < MIN_DAYS_EVIDENCE:
        stage, stage_cn = "preliminary", f"初步样本（{days}/{MIN_DAYS_EVIDENCE} 个交易日）"
    elif perm.get("p_value") is not None and perm["p_value"] < 0.05:
        stage, stage_cn = "signal_not_rejected", "样本内未被否证（仍需预注册 holdout 与独立复现）"
    else:
        stage, stage_cn = "no_evidence", "样本足够但未显示出优于随机选择的证据"

    out = {
        "strategy": strategy, "horizon": horizon,
        "stage": stage, "stage_cn": stage_cn,
        "days": days, "first_date": dates[0] if dates else None,
        "last_date": dates[-1] if dates else None,
        "n_selected": len(sel), "n_universe": len(uni),
        "cost_pct": total_cost_pct(),
        "untradable_rate": round(len(untradable) / len(rows) * 100, 1) if rows else None,
        "unknown_tradable_rate": round(len(unknown) / len(rows) * 100, 1) if rows else None,
        "selected": sel_stat,
        "universe": uni_stat,
        "selected_net_return": gross_stat,
        "permutation": perm,
        "quintile": quint,
        "param_digests": sorted({r.get("param_digest") for r in rows if r.get("param_digest")}),
        "caveats": [
            "报告的是扣费后相对基准的超额收益；毛收益包含小盘股 beta，不具判别力",
            "次日开盘即封死涨停的样本已剔除" + ("（本次按要求包含在内）" if include_untradable else ""),
            "参数指纹若出现多个值，说明区间内改过阈值，该段样本不可合并解读",
            "p 值未经多重检验校正；横跨多个策略/持有期比较时须用 BH 校正",
        ],
    }
    cache.cache_set(ck, out, settings.ttl_daily)
    return out


def multi_record(strategies: tuple[str, ...] | None = None,
                 horizons: tuple[int, ...] = HORIZONS) -> dict[str, Any]:
    """跨策略 × 持有期的总表，并对全部 p 值做 BH 校正。

    这一步是"诚实"的技术实现：一次性看 4 策略 × 4 持有期 = 16 个检验，
    必然会有一个 p<0.05。不做校正就等于自欺。
    """
    cells = []
    for s in (strategies or TRACKED_STRATEGIES):
        for h in horizons:
            r = record(s, h)
            if r.get("n_selected"):
                cells.append(r)
    ps = [c["permutation"].get("p_value") for c in cells]
    bh = V.benjamini_hochberg([p for p in ps if p is not None])
    adj_iter = iter(bh["adjusted"])
    for c, p in zip(cells, ps):
        c["p_value_raw"] = p
        c["p_value_bh"] = next(adj_iter) if p is not None else None
        c["discovery_after_bh"] = bool(c["p_value_bh"] is not None and c["p_value_bh"] <= 0.05)
    return {
        "cells": [{k: c[k] for k in ("strategy", "horizon", "stage", "days", "n_selected",
                                     "untradable_rate", "p_value_raw", "p_value_bh",
                                     "discovery_after_bh")} for c in cells],
        "detail": cells,
        "multiple_testing": {**bh, "tests_run": len(cells)},
        "trials_logged": len(store.list_trials(1000)),
        "note": ("同时检验多个策略×持有期时，只有 BH 校正后仍显著的格子才算发现；"
                 "未校正的 p<0.05 在 16 次检验里属于预期中的噪音"),
    }


def status() -> dict[str, Any]:
    """研究状态——由账本算出来，而不是写死的字符串。

    这是对原先 report.py 里硬编码 `strategy_validation: "not_backtested"` 的替换：
    一句声明会忘记更新，一个从数据库算出来的状态不会。

    刻意只做轻量统计（计数与日期），不在这里跑置换检验：复盘报告每次生成都会调用
    本函数，而重抽样是 CPU 密集的。显著性结论走 /api/track/record 单独取，有缓存。
    """
    dates = store.signal_dates()
    summary = store.outcome_summary(horizon=1)
    digests = summary["param_digests"]
    n = summary["days"]
    if not dates:
        stage, stage_cn = "no_ledger", "账本为空：尚未冻结任何一天的信号"
    elif n == 0:
        stage, stage_cn = "frozen_only", f"已冻结 {len(dates)} 天，但尚无一天完成前瞻结算"
    elif n < MIN_DAYS_PRELIMINARY:
        stage, stage_cn = "collecting", f"积累中（已结算 {n}/{MIN_DAYS_PRELIMINARY} 个交易日）"
    elif n < MIN_DAYS_EVIDENCE:
        stage, stage_cn = "preliminary", f"初步样本（已结算 {n}/{MIN_DAYS_EVIDENCE} 个交易日）"
    else:
        stage, stage_cn = "sample_sufficient", f"样本量已达门槛（{n} 个交易日），显著性见战绩页"

    by_name = {p["strategy"]: p for p in summary["per_strategy"]}
    per = []
    for s_name in TRACKED_STRATEGIES:
        row = by_name.get(s_name) or {}
        per.append({"strategy": s_name, "days": row.get("days") or 0,
                    "selected": row.get("selected") or 0,
                    "untradable_rate": row.get("untradable_rate")})

    return {
        "methodology_version": f"{params.PARAM_VERSION}/{RULE_VERSION}",
        "param_digest": params.digest(),
        "param_digests_in_ledger": digests,
        "params_stable": len(digests) <= 1,
        "frozen_days": len(dates),
        "settled_days": n,
        "first_frozen": dates[0] if dates else None,
        "last_frozen": dates[-1] if dates else None,
        "stage": stage,
        "stage_cn": stage_cn,
        "per_strategy": per,
        "cost_pct": total_cost_pct(),
        "benchmark": PRIMARY_BENCHMARK,
        "validated": False,
        "statement": (
            "策略验证状态由前瞻结果账本计算得出，不是手写的字段。"
            f"当前已冻结 {len(dates)} 个交易日、已结算 {n} 个交易日，"
            f"参数指纹 {params.digest()}"
            + ("（区间内参数未变动）。" if len(digests) <= 1 else
               f"；账本中出现 {len(digests)} 个不同指纹，说明期间改过阈值，该段样本不可合并解读。")
            + " 无论账本积累到什么程度，本系统都不会把状态置为『已验证』："
            "样本内未被否证不等于有效，还需要预注册的 holdout 区间、"
            "独立第三方在同一快照上的复现、以及真实或模拟成交记录的印证。"
        ),
        "what_would_change_this": [
            f"连续冻结并结算 ≥{MIN_DAYS_EVIDENCE} 个交易日，期间不修改 params（指纹保持不变）",
            "分层置换 p 值经 BH 校正后仍 ≤0.05，且评分分层单调性成立",
            "扣费后超额收益的 Bootstrap 95% 区间下界 > 0",
            "成本×2、入场延迟一个交易日等压力测试下结论不翻转",
            "独立复现者在同一数据快照上得到同一输出哈希",
        ],
        "where_to_look": {
            "战绩与显著性": "GET /api/track/record?strategy=first_board&horizon=1",
            "跨策略多重检验": "GET /api/track/matrix",
            "数据对账": "GET /api/reconcile",
        },
    }
