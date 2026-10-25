"""游资选股器：把复盘数据直接翻译成「明天能看哪些票」。

策略全部基于当日已抓取的池子数据，不做全市场扫描，速度快、可盘中反复刷新。
"""
from __future__ import annotations

from typing import Any

from ..core.utils import fnum, to_date
from . import lhb as lhb_svc
from . import limitup, sectors

STRATEGIES = {
    "first_board": "首板优选：非一字、封成比高、流通市值适中（次日溢价期望最好）",
    "relay": "二板接力：梯队健康、封单大、无炸板，主线板块优先",
    "rebound": "断板反包：昨日涨停今日未涨停但强势收红，情绪修复期胜率高",
    "game_money": "龙虎榜游资票：知名游资净买入且非散户大本营对手盘",
    "main_line": "主线板块龙头：主线内连板高度最高、封单最大的票",
    "risk": "风险池：炸板次数多/尾盘板/拉萨席位接盘，次日核按钮概率高",
}


def _row(it: dict, score: float, why: list[str]) -> dict:
    return {
        "code": it["code"], "symbol": it.get("symbol"), "name": it["name"],
        "price": it.get("price"), "pct": it.get("pct"), "boards": it.get("boards"),
        "days_board": it.get("days_board"), "industry": it.get("industry"),
        "fund_yi": round((it.get("fund") or 0) / 1e8, 2),
        "amount_yi": round((it.get("amount") or 0) / 1e8, 2),
        "float_mv_yi": round((it.get("float_mv") or 0) / 1e8, 1),
        "seal_ratio": it.get("seal_ratio"), "turnover": it.get("turnover"),
        "board_type": it.get("board_type"), "first_time": it.get("first_time"),
        "broken_times": it.get("broken_times"), "score": round(score, 1), "why": why,
    }


async def _first_board(date: str | None) -> tuple[list[dict], str]:
    res = await limitup.pool("zt", date)
    items = (res.data or {}).get("items") or []
    historical = not limitup.history_depth_ok(date)
    hot: set[str] = set()
    if not historical:
        ml = await sectors.main_line()
        hot = {m["name"] for m in (ml.get("main_lines") or [])[:5]}
    out = []
    for it in items:
        if (it.get("boards") or 1) != 1:
            continue
        why, score = [], 0.0
        if it.get("board_type") in ("一字板", "T字板"):
            continue  # 一字板买不进，无操作价值
        sr = it.get("seal_ratio") or 0
        if sr >= 30:
            score += 30; why.append(f"封成比{sr:.0f}%极强")
        elif sr >= 10:
            score += 20; why.append(f"封成比{sr:.0f}%良好")
        elif sr < 3:
            score -= 15; why.append(f"封成比仅{sr:.1f}%偏弱")
        mv = (it.get("float_mv") or 0) / 1e8
        if 20 <= mv <= 120:
            score += 20; why.append(f"流通市值{mv:.0f}亿(游资甜区)")
        elif mv > 300:
            score -= 10; why.append(f"流通市值{mv:.0f}亿偏大")
        hs = it.get("turnover") or 0
        if 5 <= hs <= 20:
            score += 15; why.append(f"换手{hs:.1f}%充分")
        elif hs > 35:
            score -= 10; why.append(f"换手{hs:.1f}%过高")
        if 0 < (it.get("first_min") or 0) <= 10 * 60:
            score += 15; why.append("上午封板")
        if (it.get("broken_times") or 0) == 0:
            score += 10; why.append("未炸板")
        else:
            score -= 10 * (it.get("broken_times") or 0); why.append(f"炸板{it['broken_times']}次")
        if it.get("industry") in hot:
            score += 20; why.append(f"主线板块({it['industry']})")
        out.append(_row(it, score + 40, why))
    out.sort(key=lambda x: -x["score"])
    note = f"共筛出{len(out)}只首板，优先看主线板块+封成比高+上午封板的票"
    if historical:
        note += "；历史模式不含当前主线归属，避免回填"
    return out, note


async def _relay(date: str | None) -> tuple[list[dict], str]:
    res = await limitup.pool("zt", date)
    items = (res.data or {}).get("items") or []
    historical = not limitup.history_depth_ok(date)
    hot: set[str] = set()
    if not historical:
        ml = await sectors.main_line()
        hot = {m["name"] for m in (ml.get("main_lines") or [])[:5]}
    out = []
    for it in items:
        b = it.get("boards") or 1
        if b < 2:
            continue
        why, score = [], float(b * 12)
        if (it.get("broken_times") or 0) == 0:
            score += 20; why.append("无炸板一致性强")
        else:
            score -= 15; why.append(f"炸板{it['broken_times']}次分歧")
        if (it.get("fund") or 0) >= 1e8:
            score += 18; why.append(f"封单{it['fund']/1e8:.1f}亿")
        if it.get("industry") in hot:
            score += 20; why.append(f"主线({it['industry']})")
        if it.get("board_type") == "一字板":
            score -= 5; why.append("一字板难买")
        if 0 < (it.get("first_min") or 0) <= 9 * 60 + 40:
            score += 12; why.append("早盘封板")
        why.insert(0, f"{b}连板")
        out.append(_row(it, score, why))
    out.sort(key=lambda x: (-x["boards"], -x["score"]))
    note = "接力核心看梯队是否完整（有无断层）与龙头一致性，断层日不做接力"
    if historical:
        note += "；历史模式不含当前主线归属，避免回填"
    return out, note


async def _rebound(date: str | None) -> tuple[list[dict], str]:
    if not limitup.history_depth_ok(date):
        return [], "历史日期缺少逐股 OHLC，禁止用当前行情回填断板反包结果"

    from ..core.utils import normalize_date, prev_trade_day
    target = normalize_date(date)
    prev_d = str(prev_trade_day(to_date(target)))
    prev = await limitup.pool("zt", prev_d)
    today = await limitup.pool("zt", target)
    today_codes = {i["code"] for i in ((today.data or {}).get("items") or [])}
    prev_items = (prev.data or {}).get("items") or []
    cand = [i for i in prev_items if i["code"] not in today_codes]
    if not cand:
        return [], "无数据（需前一交易日涨停池）"

    from ..core.assets import Asset
    from . import market as mkt

    assets = [Asset(key=i["code"], name=i["name"], group="个股", tx=i.get("symbol"),
                    sina=i.get("symbol"), sina_kind="stock") for i in cand]
    q = await mkt.fetch_quotes(assets)
    quotes: dict[str, dict] = q.data or {}
    out = []
    for it in cand:
        d = quotes.get(it["code"]) or {}
        pct = fnum(d.get("pct"))
        if pct is None:
            continue
        why = [f"昨{(it.get('boards') or 1)}连板", f"今{pct:+.2f}%"]
        score = 40 + pct * 6
        if pct >= 5:
            score += 20; why.append("强势未涨停，反包概率高")
        elif pct < -3:
            score -= 30; why.append("已破位，规避")
        if (it.get("broken_times") or 0) == 0:
            score += 8
        out.append({**_row(it, score, why), "today_pct": pct, "today_price": d.get("price")})
    out.sort(key=lambda x: -x["score"])
    return [o for o in out if (o.get("today_pct") or -99) > -2], \
        "断板反包只在情绪修复/发酵期做，退潮期一律回避"


async def _game_money(date: str | None) -> tuple[list[dict], str]:
    res = await lhb_svc.daily(date)
    items = (res.data or {}).get("items") or []
    out = []
    for it in items:
        known = it.get("known_seats") or []
        if not known:
            continue
        net = it.get("known_net_yi") or 0
        tags = [k.get("tag") for k in known]
        score = 40 + net * 25
        why = [f"{it.get('game_tag')}", f"知名资金净买{net:.2f}亿"]
        if "顶级游资" in tags:
            score += 20
        if "散户大本营" in tags and net < 0:
            score -= 25; why.append("拉萨席位出货，警惕")
        if "机构" in tags:
            score += 10; why.append("机构参与，持续性好")
        out.append({
            "code": it["code"], "symbol": it.get("symbol"), "name": it["name"], "price": it.get("close"),
            "pct": it.get("pct"), "industry": "", "fund_yi": net, "amount_yi": it.get("amount_yi"),
            "float_mv_yi": it.get("float_mv_yi"), "seal_ratio": None, "turnover": it.get("turnover"),
            "board_type": "", "first_time": "", "broken_times": 0, "boards": None, "days_board": "",
            "score": round(score, 1), "why": why,
            "seats": known[:6], "reason": it.get("reason"),
        })
    out.sort(key=lambda x: -x["score"])
    return out, "龙虎榜看「谁买」比看「买多少」更重要：顶级游资+机构=可跟踪，拉萨天团=风险"


async def _main_line(date: str | None) -> tuple[list[dict], str]:
    if not limitup.history_depth_ok(date):
        return [], "历史板块成分和资金流未入库，不能用当前主线回填历史日期"
    ml = await sectors.main_line()
    # 只有通过四维确认的板块才算主线；涨停扎堆但板块没涨、资金没进，不是主线。
    lines = (ml.get("confirmed_lines") or [])[:3]
    if not lines:
        return [], "今日无通过四维确认的主线（涨停集中 ≠ 主线成立），不做主线龙头"
    res = await limitup.pool("zt", date)
    items = (res.data or {}).get("items") or []
    out = []
    for line in lines:
        members = [i for i in items if i.get("industry") == line["name"]]
        members.sort(key=lambda x: (-(x.get("boards") or 0), -(x.get("fund") or 0)))
        for it in members[:4]:
            score = 60 + (it.get("boards") or 1) * 10 + line["score"] / 5
            out.append({**_row(it, score, [f"主线:{line['name']}", line["reason"][:40]]),
                        "line": line["name"], "line_score": line["score"]})
    out.sort(key=lambda x: -x["score"])
    return out, "只做主线，不做杂毛：主线内选高度最高或封单最大的龙头"


async def _risk(date: str | None) -> tuple[list[dict], str]:
    zb = await limitup.pool("zb", date)
    zt = await limitup.pool("zt", date)
    out = []
    for it in (zb.data or {}).get("items") or []:
        why = [f"炸板{(it.get('broken_times') or 0)}次", f"收盘{it.get('pct'):+.2f}%" if it.get("pct") is not None else "炸板未回封"]
        out.append({**_row(it, 10 - (it.get("broken_times") or 0) * 5, why), "risk": "炸板"})
    for it in (zt.data or {}).get("items") or []:
        if it.get("board_type") == "尾盘板" or (it.get("seal_ratio") or 100) < 2:
            why = []
            score = 20
            if it.get("board_type") == "尾盘板":
                why.append("尾盘偷袭板，次日溢价差"); score -= 15
            if (it.get("seal_ratio") or 0) < 2:
                why.append(f"封成比仅{it.get('seal_ratio')}%"); score -= 15
            out.append({**_row(it, score, why), "risk": "弱封板"})
    return out, "风险池用于次日竞价排除：这些票高开不追、低开不接"


# 每个策略对外展示/实际跟踪的名额。
# 为什么要把名额单独写出来：被跟踪的"选中组"必须有明确边界，
# 否则置换检验里的 selected 与 universe 就没有客观分界线，结论可以随口调整。
SELECT_LIMIT = {
    "first_board": 30, "relay": 25, "rebound": 25,
    "game_money": 25, "main_line": 20, "risk": 30,
}
# 跟踪前瞻结果时只取头部 N 名，避免"选 30 只"等于"几乎全选"从而失去排序含义。
TRACK_TOP_N = {"first_board": 10, "relay": 8, "main_line": 8, "game_money": 8}

_FUNCS = {
    "first_board": _first_board,
    "relay": _relay,
    "rebound": _rebound,
    "game_money": _game_money,
    "main_line": _main_line,
    "risk": _risk,
}


async def run(strategy: str = "first_board", date: str | None = None,
              include_universe: bool = False) -> dict:
    """执行策略。

    include_universe=True 时额外返回 `universe`：该策略在当日**决策时点真实可选的
    全部标的**（已打分但未截断）。这是置换检验的零假设池，没有它就无法回答
    "规则是否优于在同一池里乱选"。展示用的 items 行为保持不变。
    """
    strategy = strategy if strategy in _FUNCS else "first_board"
    fn = _FUNCS[strategy]
    full, note = await fn(date)
    limit = SELECT_LIMIT.get(strategy, 30)
    out = {"strategy": strategy, "desc": STRATEGIES.get(strategy, ""), "note": note,
           "count": len(full[:limit]), "universe_size": len(full), "items": full[:limit]}
    if include_universe:
        out["universe"] = full
        out["track_top_n"] = TRACK_TOP_N.get(strategy, 10)
    return out
