"""对账层：用第二条独立路径重算同一个数，并检查不变量。

为什么需要它，而原有的 `cache.chain` 不够？

`cache.chain` 是 **failover**：按优先级试源，第一个通过校验的就采用。它解决的是
"源挂了还能不能出数"——可用性问题。它从来没有回答过"这个数对不对"：
第一个源返回 58 家涨停，链路就结束了，第二个源可能返回 71 家，但没人看过。

对账（reconciliation）是审计行业的标准手段：让两条**在实现上完全独立**的路径
算同一个量，再比较差异。两条路径同时错到同一个数的概率极低，所以一致意味着
很可能都对，不一致则必然至少有一个错——无论如何都比"单一来源 + 一句『数据正常』"
提供更多信息。

本模块实现三类独立路径：

1. **跨接口对账**：涨停池（push2ex 的 getTopicZTPool）与涨跌幅分布（第 11 档）
   来自东财两个不同接口、不同计算链路，家数应当一致。
2. **按价格独立判定**：不信任任何源给的"涨停池"，而是用 `core/regime` 的涨跌幅
   制度表，从收盘价与前收盘价自己判断"是否封在涨停价"。这同时检验了两件事——
   池子是否干净，以及那张人工维护的制度表是否仍然正确。
3. **不变量（property）检查**：晋级数不可能大于昨日涨停数、天梯各层求和必须等于
   涨停总数、比率必须落在值域内。这些约束不依赖任何人的判断，违反即是 bug。

**本模块只报告差异，不自动修正。** 自动"修好"会把问题藏起来；一个暴露出来的
2% 偏差比一个被静默对齐的数字有价值得多。
"""
from __future__ import annotations

from typing import Any

from ..core import regime
from ..core.utils import fnum, normalize_date
from . import limitup, sentiment

# 两条路径的家数相对偏差门槛：超过即判为不一致，必须人工查明口径
TOLERANCE_PCT = 2.0


def _prev_close_of(item: dict[str, Any]) -> float | None:
    """由收盘价与涨跌幅反推前收盘价。

    为什么反推而不是直接取：涨停池接口不返回前收盘价。反推会引入一点浮点误差，
    因此下游的涨停价比对使用相对容差而非精确相等。
    """
    price = fnum(item.get("price"))
    pct = fnum(item.get("pct"))
    if price is None or pct is None or price <= 0:
        return None
    denom = 1 + pct / 100.0
    if denom <= 0.01:
        return None
    return price / denom


def price_based_check(items: list[dict[str, Any]], date: str) -> dict[str, Any]:
    """按涨跌幅制度表独立判定池内每只票是否真的封在涨停价。

    三种结果分别对应三类不同的问题：
    - mismatched：池子里混入了没封住的票，或制度表的档位错了
    - unknown：代码无法归板 / 次新无涨跌幅限制，不计入分母（而不是当成正确）
    - matched：两条路径一致
    """
    matched, mismatched, unknown = 0, [], []
    by_board: dict[str, dict[str, int]] = {}
    st_count = 0
    for it in items:
        code = str(it.get("code") or "")
        prev = _prev_close_of(it)
        # 涨停池接口不返回风险警示标记，只能从简称识别 ST/*ST。
        # 不做这一步，主板 ST 股（5% 档）会被 10% 档判成"没封住"，制造大批假错报。
        name = str(it.get("name") or "")
        is_st = "ST" in name.upper()
        st_count += 1 if is_st else 0
        res = regime.is_limit_up_price(fnum(it.get("price")), prev, code, date, is_st=is_st)
        board = res.get("board") or "unknown"
        slot = by_board.setdefault(board, {"matched": 0, "mismatched": 0, "unknown": 0,
                                           "limit_pct": res.get("pct")})
        if res.get("matched") is None:
            unknown.append({"code": code, "name": it.get("name"), "board": board,
                            "reason": res.get("reason")})
            slot["unknown"] += 1
        elif res["matched"]:
            matched += 1
            slot["matched"] += 1
        else:
            mismatched.append({"code": code, "name": it.get("name"), "board": board,
                               "close": fnum(it.get("price")), "pct": fnum(it.get("pct")),
                               "expected_limit_price": res.get("limit_price"),
                               "limit_pct": res.get("pct")})
            slot["mismatched"] += 1
    decided = matched + len(mismatched)
    return {
        "checked": len(items), "decided": decided,
        "matched": matched, "mismatched": len(mismatched), "unknown": len(unknown),
        "match_rate": round(matched / decided * 100, 2) if decided else None,
        "by_board": by_board,
        "st_detected": st_count,
        "mismatched_sample": mismatched[:12],
        "unknown_sample": unknown[:12],
        "verdict": ("ok" if decided and matched == decided else
                    ("suspect" if decided else "no_data")),
        "st_note": "ST 标记由简称推断（名称含 ST），非官方字段；漏判会表现为 mismatch",
        "note": ("mismatch 不一定是数据源错——也可能是 core/regime 的涨跌幅档位表过期。"
                 "两种可能都必须人工确认，不得自动对齐。"),
    }


def invariants(metrics: dict[str, Any], ladder: dict[str, Any],
               zt_total: int, prev_limit_up: int | None) -> list[dict[str, Any]]:
    """不依赖任何外部数据的硬约束检查。违反即说明代码或口径有 bug。"""
    checks: list[dict[str, Any]] = []

    def add(name: str, ok: bool | None, detail: str) -> None:
        checks.append({"check": name, "ok": ok, "detail": detail})

    br = metrics.get("broken_rate")
    add("炸板率值域", None if br is None else bool(0 <= br <= 100),
        f"broken_rate={br}（必须落在 0-100）")

    sr = metrics.get("seal_rate")
    if br is not None and sr is not None:
        add("封板率+炸板率=100", abs((br + sr) - 100) < 0.2,
            f"{sr} + {br} = {round(sr + br, 2)}")

    levels = ladder.get("levels") or []
    s = sum(int(l.get("count") or 0) for l in levels)
    add("天梯分层求和=涨停总数", s == zt_total if levels else None,
        f"分层合计 {s} vs 涨停池 {zt_total}")

    promoted = metrics.get("promote_rate")
    if prev_limit_up is not None and promoted is not None:
        add("晋级率值域", bool(0 <= promoted <= 100),
            f"promote_rate={promoted}，昨日涨停 {prev_limit_up} 家")

    lb = metrics.get("lianban_count")
    fb = metrics.get("first_board_count")
    if lb is not None and fb is not None:
        add("连板+首板≤涨停总数", (lb + fb) <= zt_total,
            f"{lb} + {fb} = {lb + fb} vs {zt_total}")

    mb = metrics.get("max_boards")
    if mb is not None and levels:
        add("最高连板=天梯最高层", mb == max(int(l.get("boards") or 0) for l in levels),
            f"max_boards={mb}")

    tradable_n = (metrics.get("tradable_premium_sample") or 0)
    sample_n = (metrics.get("premium_sample") or 0)
    if sample_n:
        add("可成交样本≤总样本", tradable_n <= sample_n,
            f"可成交 {tradable_n} / 总 {sample_n}")

    return checks


async def board_crosscheck(prev_premium: float | None) -> dict[str, Any]:
    """用腾讯「昨日涨停」板块涨幅独立核对本地隔日溢价。

    本地溢价是逐股等权平均，腾讯给的是板块加权指数，口径不同，因此只校验
    数量级（差 ≤ 0.8pp）。它能抓出「取错日期 / 单位错 / 漏算样本」这类硬错误，
    不适合当精确基准——所以 ok=False 才报警。
    """
    if prev_premium is None:
        return {"ok": None, "note": "本地没有可成交溢价样本，跳过交叉验证"}
    from ..sources import tencent as tx

    rows = await tx.board_rank("gn", 80)
    if not rows:
        return {"ok": None, "note": "腾讯板块接口不可用，未做交叉验证"}
    ref = next((r for r in rows if str(r.get("name") or "") == "昨日涨停"), None)
    if not ref or ref.get("pct") is None:
        return {"ok": None, "note": "腾讯未返回「昨日涨停」板块"}
    diff = round(float(prev_premium) - float(ref["pct"]), 2)
    return {
        "ok": abs(diff) <= 0.8,
        "local": prev_premium,
        "reference": ref["pct"],
        "diff": diff,
        "source": "tencent:昨日涨停",
        "note": "本地为逐股等权平均，腾讯为板块加权指数，仅校验数量级",
    }


async def run(date: str | None = None, force: bool = False,
              senti: dict[str, Any] | None = None) -> dict[str, Any]:
    """执行一次完整对账，返回可直接贴进复盘报告的结论。

    senti 可由调用方传入已算好的情绪结果，避免复盘报告里重复计算一次。
    """
    d = normalize_date(date)
    zt = await limitup.pool("zt", d, force=force)
    zb = await limitup.pool("zb", d, force=force)
    br = await sentiment.breadth(force=force, date=d)
    lad = await limitup.ladder(d, force=force)

    zt_items = (zt.data or {}).get("items") or []
    pool_n = len(zt_items)
    breadth = br.data or {}
    breadth_n = breadth.get("limit_up")

    # --- 路径 1：跨接口家数对账
    cross: dict[str, Any] = {
        "pool_source": zt.source, "pool_count": pool_n,
        "breadth_source": br.source, "breadth_count": breadth_n,
        "tolerance_pct": TOLERANCE_PCT,
    }
    if breadth_n in (None, 0) or pool_n == 0:
        cross.update({"verdict": "no_data", "diff": None, "diff_pct": None,
                      "note": "两条路径中至少一条无数据，本次无法交叉验证（不等于数据正确）"})
    else:
        diff = pool_n - int(breadth_n)
        diff_pct = abs(diff) / max(1, int(breadth_n)) * 100
        cross.update({
            "diff": diff, "diff_pct": round(diff_pct, 2),
            "verdict": "consistent" if diff_pct <= TOLERANCE_PCT else "inconsistent",
            "note": ("涨停池与涨跌幅分布第 11 档来自东财两个独立接口；"
                     "常见差异原因：是否纳入北交所、ST 股、当日新股，以及盘中快照时点不同"),
        })

    # --- 路径 2：按价格独立判定
    price_check = price_based_check(zt_items, d)

    # --- 路径 3：不变量
    senti = senti or await sentiment.core(d, force=False, save=False)
    metrics = senti.get("metrics") or {}
    inv = invariants(metrics, lad, pool_n, metrics.get("prev_limit_up"))
    failed = [c for c in inv if c["ok"] is False]

    # --- 路径 4：跨厂商交叉验证（本地溢价 vs 腾讯「昨日涨停」板块）
    board_cross = await board_crosscheck(metrics.get("prev_premium"))

    verdicts = [cross["verdict"], price_check["verdict"]]
    if board_cross.get("ok") is False:
        verdicts.append("inconsistent")
    if failed:
        overall = "fail"
    elif "inconsistent" in verdicts or "suspect" in verdicts:
        overall = "inconsistent"
    elif "no_data" in verdicts:
        overall = "incomplete"
    else:
        overall = "consistent"

    summary_map = {"consistent": "两条独立路径一致", "inconsistent": "两条独立路径不一致，需人工查口径",
                   "fail": "不变量校验失败，存在计算错误", "incomplete": "路径缺数，本次无法交叉验证"}
    summary = summary_map.get(overall, overall)
    if cross.get("diff") is not None:
        summary += f"（涨停池 {pool_n} vs 分布档 {breadth_n}，差 {cross['diff']}）"
    if price_check.get("match_rate") is not None:
        summary += f"；按涨跌幅制度表独立判定封板一致率 {price_check['match_rate']}%"
    if board_cross.get("ok") is not None:
        summary += (f"；隔夜溢价与腾讯「昨日涨停」板块差 {board_cross['diff']}pp"
                    f"（本地 {board_cross['local']}% vs 腾讯 {board_cross['reference']}%）")

    return {
        "date": d,
        "overall": overall,
        "summary": summary,
        "cross_source": cross,
        "board_cross": board_cross,
        "price_based": price_check,
        "invariants": inv,
        "invariants_failed": failed,
        "regime": regime.regime_note(d),
        "broken_pool_count": len((zb.data or {}).get("items") or []),
        "independence": {
            "path_1": "东财 push2ex 涨停池家数",
            "path_2": "东财涨跌幅分布接口第 11 档家数（不同接口、不同计算链路）",
            "path_3": "按 core/regime 涨跌幅制度表，从收盘价/前收盘价自行判定是否封板",
            "why": ("多源 failover 只保证『有数』，不保证『数对』。"
                    "两条独立实现同时错到同一个值的概率极低，因此一致性是正确性的实证依据；"
                    "不一致则必然至少有一方错，无论如何都比单一来源信息量更大。"),
        },
        "limits": [
            "本对账全部依赖免费公开接口，未与交易所官方日报核对；"
            "要把结论升级为『对权威口径无偏差』，必须另行取交易所日报做第三方基准",
            "unknown 样本（次新无涨跌幅限制、代码无法归板）不计入分母，不得当成一致",
            "本模块只报告差异，不自动修正",
        ],
    }
