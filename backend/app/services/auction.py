"""次日竞价确认：把“收盘选出来的票”带到 09:15-09:25 再确认一次。

游资复盘不是收盘选完就直接买。真正缺的一步是次日集合竞价：
高开幅度是否在剧本内、竞价额是否有效放大、是否一字封死而根本买不到。
本模块只使用竞价时点已经可见的数据，不把盘中或收盘结果回填到竞价判断。
"""
from __future__ import annotations

from typing import Any

from ..core import store
from ..core.assets import Asset
from ..core.utils import code_to_symbol, fnum, is_trade_day, normalize_date, now_cn
from . import market, screener

SUPPORTED = ("first_board", "relay", "main_line", "game_money")
STRATEGY_NAMES = {
    "first_board": "首板优选",
    "relay": "二板接力",
    "main_line": "主线龙头",
    "game_money": "龙虎榜游资票",
}


def session_state(now=None) -> dict:
    """返回 A 股当前时段；时间统一使用北京时间。"""
    now = now or now_cn()
    minutes = now.hour * 60 + now.minute
    if not is_trade_day(now.date()):
        return {"key": "closed", "label": "非交易日", "actionable": False}
    if minutes < 9 * 60 + 15:
        return {"key": "pre_auction", "label": "竞价前", "actionable": False}
    if minutes < 9 * 60 + 25:
        return {"key": "auction", "label": "集合竞价", "actionable": True}
    if minutes < 9 * 60 + 30:
        return {"key": "auction_locked", "label": "竞价已结束，等待开盘", "actionable": True}
    if minutes < 11 * 60 + 30:
        return {"key": "trading", "label": "连续竞价", "actionable": False}
    if minutes < 13 * 60:
        return {"key": "lunch", "label": "午间休市", "actionable": False}
    if minutes < 15 * 60:
        return {"key": "trading", "label": "连续竞价", "actionable": False}
    return {"key": "closed", "label": "已收盘", "actionable": False}


def judge_auction(gap: float | None, sealed: bool, amount_ratio: float | None,
                  strategy: str, actionable: bool) -> dict:
    """竞价决策纯函数，阈值是纪律线而非收益承诺。"""
    if not actionable:
        return {"level": "wait", "verdict": "等待竞价",
                "action": "非 09:15-09:30 窗口，仅展示候选；竞价开始后刷新再确认"}
    if gap is None:
        return {"level": "no_data", "verdict": "无有效报价",
                "action": "不参与，等待报价恢复"}
    if sealed or gap >= 9.5:
        return {"level": "unbuyable", "verdict": "涨停排队",
                "action": "不追排板；买不到就不做，等开板换手后再看"}

    max_gap = 6.5 if strategy == "first_board" else 7.5
    min_ratio = 2.0 if strategy == "first_board" else 3.0
    if gap > max_gap:
        return {"level": "avoid", "verdict": "过度高开",
                "action": f"高开{gap:.1f}%超过剧本上限{max_gap:.1f}%，不追，防止一致转分歧"}
    if gap < -3:
        return {"level": "avoid", "verdict": "竞价放弃",
                "action": "低开超过 3%，说明承接被证伪，取消今日计划"}
    if amount_ratio is None:
        return {"level": "weak", "verdict": "待量能确认",
                "action": "价格区间可接受，但竞价额缺失；开盘后看承接再决定"}
    if amount_ratio < min_ratio:
        return {"level": "weak", "verdict": "量能不足",
                "action": f"竞价额/昨日成交仅{amount_ratio:.2f}%，低于{min_ratio:.1f}%确认线，降低预期"}
    if gap < 0:
        return {"level": "weak", "verdict": "弱转强观察",
                "action": "低开但竞价量达标，只做开盘后主动承接，不提前挂单"}
    return {"level": "pass", "verdict": "竞价确认",
            "action": f"高开{gap:.1f}%且竞价额达标；仍按打板/回踩剧本执行，不追高"}


def _quote_gap(q: dict) -> tuple[float | None, bool]:
    prev = fnum(q.get("prev_close"))
    price = fnum(q.get("price"))
    limit_up = fnum(q.get("limit_up"))
    if not prev or prev <= 0 or price is None:
        return None, False
    gap = round((price / prev - 1) * 100, 2)
    sealed = bool(limit_up and price >= limit_up * 0.999)
    return gap, sealed


async def build(strategy: str = "first_board", date: str | None = None, force: bool = False) -> dict:
    strategy = strategy if strategy in SUPPORTED else "first_board"
    # 默认取最近已收盘交易日作为候选日；显式 date 只影响候选来源，不读取未来行情。
    base_date = normalize_date(date)

    sess = session_state()
    res = await screener.run(strategy, base_date)
    seen: dict[str, dict] = {}
    for item in res.get("items") or []:
        code = str(item.get("code") or "")
        if not code:
            continue
        old = seen.get(code)
        if old is None or (item.get("score") or 0) > (old.get("score") or 0):
            seen[code] = item
    candidates = sorted(seen.values(), key=lambda x: -(x.get("score") or 0))

    assets = [Asset(key=i["code"], name=i.get("name") or i["code"], group="竞价候选",
                    tx=i.get("symbol") or code_to_symbol(i["code"]),
                    sina=i.get("symbol") or code_to_symbol(i["code"]), sina_kind="stock")
              for i in candidates]
    quote_res = await market.fetch_quotes(assets, force=force) if assets else None
    quotes: dict[str, dict] = (quote_res.data or {}) if quote_res else {}

    rows = []
    for item in candidates:
        q = quotes.get(item["code"]) or {}
        gap, sealed = _quote_gap(q)
        # 竞价窗口之外，行情是候选日或盘中的数，不是竞价匹配价/竞价额，不能当高开幅度展示
        quote_amount = fnum(q.get("amount")) if sess["actionable"] else None
        if not sess["actionable"]:
            gap, sealed = None, False
        prev_amount = fnum(item.get("amount"))
        ratio = round(quote_amount / prev_amount * 100, 2) if quote_amount and prev_amount else None
        decision = judge_auction(gap, sealed, ratio, strategy, sess["actionable"])
        rows.append({
            "code": item["code"], "name": item.get("name"), "score": item.get("score"),
            "boards": item.get("boards"), "days_board": item.get("days_board"),
            "industry": item.get("industry"), "board_type": item.get("board_type"),
            "prev_amount_yi": item.get("amount_yi"),
            "price": fnum(q.get("price")), "prev_close": fnum(q.get("prev_close")),
            "limit_up": fnum(q.get("limit_up")), "gap": gap,
            "auction_amount_yi": round(quote_amount / 1e8, 2) if quote_amount else None,
            "auction_amount_ratio": ratio, "sealed": sealed,
            "quote_time": q.get("time") or "",
            **decision,
        })

    counts = {k: len([r for r in rows if r["level"] == k])
              for k in ("pass", "weak", "avoid", "unbuyable", "no_data", "wait")}
    valid_gaps = [r["gap"] for r in rows if r["gap"] is not None]
    snap = store.load_snapshot(base_date) or {}
    snap_sent = snap.get("sentiment") or {}
    warnings = []
    if not sess["actionable"]:
        warnings.append(f"当前为{sess['label']}，页面只做盘后预案，不构成竞价确认")
    if not candidates:
        warnings.append("候选池为空：目标交易日没有可用涨停池或选股结果")
    if candidates and not quotes:
        warnings.append("逐股行情不可用，无法判断竞价强弱")
    if session_state()["key"] == "auction":
        warnings.append("09:20 前撤单频繁，竞价额和匹配价仍可能变化；09:25 后以最终撮合为准")
    if any(r["auction_amount_ratio"] is None and r["gap"] is not None for r in rows) and sess["actionable"]:
        warnings.append("部分个股缺少昨日成交额，量能确认不可用")

    return {
        "strategy": strategy,
        "strategy_name": STRATEGY_NAMES[strategy],
        "candidate_date": base_date,
        "session": sess,
        "as_of": now_cn().strftime("%Y-%m-%d %H:%M:%S"),
        "can_confirm": sess["actionable"],
        "context": {
            "sentiment_score": snap_sent.get("score"),
            "phase": ((snap_sent.get("phase") or {}).get("phase") if isinstance(snap_sent.get("phase"), dict) else None),
            "snapshot_quality": (snap.get("data_quality") or {}).get("level"),
            "note": "竞价只确认执行，不负责选股；候选来自上一份复盘。",
        },
        "summary": {
            "total": len(rows),
            "confirm": counts["pass"],
            "weak": counts["weak"],
            "avoid": counts["avoid"] + counts["unbuyable"],
            "avg_gap": round(sum(valid_gaps) / len(valid_gaps), 2) if valid_gaps else None,
            "warnings": warnings,
        },
        "items": rows,
        "meta": {
            "source": (quote_res.source if quote_res else "none"),
            "sources_tried": (quote_res.sources_tried if quote_res else []),
            "quote_time": next((r["quote_time"] for r in rows if r["quote_time"]), ""),
            "candidate_source": f"screener:{strategy}",
        },
        "method": {
            "window": "09:15-09:25 观察，09:25-09:30 确认最终撮合；09:30 后不算竞价确认",
            "gap": "竞价匹配价 / 昨收 - 1",
            "amount_ratio": "竞价成交额 / 候选日成交额；首板确认线 2%，接力 3%",
            "discipline": "涨停排队不可视为可成交；高开超上限或低开超 3% 均取消计划",
        },
    }
