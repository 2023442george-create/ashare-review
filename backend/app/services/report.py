"""一键复盘报告：把所有模块的数据收敛成一份「今天怎么打、明天怎么打」的作战文档。

输出同时提供 JSON（前端渲染）与 Markdown（可直接粘贴到笔记/公众号/雪球）。
"""
from __future__ import annotations

import asyncio
import datetime as dt
from typing import Any

from ..core import params, regime, store
from ..core.utils import current_trade_date, last_trade_day, normalize_date, now_cn
from . import (globalmarket, lhb as lhb_svc, limitup, market, news as news_svc, screener,
               reconcile as reconcile_svc, sectors, sentiment, track)

POSITION_MAP = [
    (85, "4-5成（高潮减仓）", "情绪透支，兑现为主，只留龙头底仓"),
    (70, "6-8成（进攻）", "赚钱效应扩散，打板/半路/低吸都可上"),
    (55, "4-6成（积极参与）", "主线明确时集中持仓，避免撒胡椒面"),
    (40, "2-4成（谨慎）", "分歧期，只做龙头与低吸，不做接力"),
    (25, "0-2成（防守）", "退潮期，保命第一，等待冰点反转信号"),
    (-1, "空仓/试错1成", "冰点期，用极小仓位试首板，等情绪修复"),
]


def _position(score: float) -> tuple[str, str]:
    for th, pos, tip in POSITION_MAP:
        if score >= th:
            return pos, tip
    return POSITION_MAP[-1][1], POSITION_MAP[-1][2]


def _weighted(parts: dict[str, float], weights: dict[str, float]) -> float:
    wsum = sum(weights.get(k, 0.0) for k in parts) or 1.0
    return sum((parts.get(k) or 0.0) * weights.get(k, 0.0) for k in parts) / wsum


def _composite_band(parts: dict[str, float], senti_band: dict) -> dict:
    """综合分的不确定区间。

    两个不确定来源叠加：
    1. 情绪分本身的阈值扰动区间（来自 sentiment.score_band）；
    2. 综合评分那四个权重 0.5/0.2/0.15/0.15 同样是拍出来的先验，一起扰动。

    为什么要把它显式印在报告里：`综合分 68.4` 这种写法在暗示小数位有判别力，
    于是"今天 68.4 比昨天 66.1 好"看起来像结论。给出区间后，如果区间宽度
    大于两日分差，这句比较就自动失效——读者不必自己去推。
    """
    f = float(params.STATS["perturb"])
    senti_pts = [v for v in (senti_band.get("lo"), senti_band.get("point"), senti_band.get("hi"))
                 if v is not None] or [parts.get("sentiment") or 0.0]
    vals = []
    for factor in (1 - f, 1.0, 1 + f):
        w = params.perturb_weights(params.COMPOSITE, factor)
        for sv in senti_pts:
            vals.append(_weighted({**parts, "sentiment": sv}, w))
    lo, hi = round(min(vals), 1), round(max(vals), 1)
    return {"point": round(_weighted(parts, params.COMPOSITE), 1), "lo": lo, "hi": hi,
            "width": round(hi - lo, 1), "perturb_pct": round(f * 100, 1),
            "param_digest": params.digest(),
            "note": ("区间同时扰动情绪因子阈值与综合权重 ±"
                     f"{round(f * 100)}%。若区间宽度超过两日分差，日间比较不成立。")}


def assess_data_quality(senti: dict, ml: dict, gl: dict, turn: dict) -> dict:
    """决定这份复盘能否支持仓位决策，而不是简单展示“数据源正常”。"""
    blockers: list[dict] = []
    warnings: list[dict] = []
    ss = senti.get("sources") or {}
    for key in ("limit_up", "broken", "limit_down", "breadth"):
        src = ss.get(key)
        if src in (None, "", "none", "mock"):
            blockers.append({"code": f"sentiment.{key}", "message": f"{key} 数据缺失或来自样例"})
    if not (senti.get("data_quality") or {}).get("premium_available"):
        blockers.append({"code": "sentiment.premium", "message": "逐股行情缺失，隔日溢价不可计算"})

    sector_sources = ml.get("sources") or {}
    for key in ("industry", "concept"):
        src = sector_sources.get(key)
        if src == "mock":
            blockers.append({"code": f"sector.{key}", "message": f"{key} 板块数据来自样例"})
        elif src in (None, "", "none"):
            # 板块只是主线判定的权重项。缺失时把主线分按中性处理并降级结论，
            # 而不是判整份报告无效 —— 板块接口抖动不该废掉当天所有决策。
            warnings.append({"code": f"sector.{key}.missing",
                             "message": f"{key} 板块数据缺失，主线与板块分按中性处理"})

    if not turn.get("total_yi"):
        # 成交额缺失不能按 0 计分，否则量能分凭空归零
        warnings.append({"code": "market.turnover.missing",
                         "message": "两市成交额缺失，量能分按中性处理"})
    elif turn.get("estimated"):
        warnings.append({"code": "market.turnover.estimated", "message": "历史成交额由量比法估算，量能分需降权"})

    excluded = (gl.get("signal") or {}).get("excluded") or []
    if excluded:
        warnings.append({"code": "global.excluded",
                         "message": "外围评分已排除样例/陈旧品种：" + "、".join(excluded[:8])})
    if (gl.get("meta") or {}).get("source") in (None, "", "none"):
        warnings.append({"code": "global.missing", "message": "外围行情不可用，外围分按中性处理"})

    level = "invalid" if blockers else ("limited" if warnings else "complete")
    return {
        "level": level,
        "decision_enabled": level != "invalid",
        "blockers": blockers,
        "warnings": warnings,
        "as_of": now_cn().strftime("%Y-%m-%d %H:%M:%S"),
    }


def apply_reconcile_gate(quality: dict, recon: dict, senti: dict | None = None) -> dict:
    """把对账结果与低置信因子接进决策闸门。

    为什么必须接进闸门而不是只显示：一个发现了计算错误却照常给出仓位建议的系统，
    等于把检查做成了装饰。不变量失败意味着代码或口径确实算错了——这比数据缺失
    更严重，因为缺失是看得见的，算错是看不见的。所以它直接禁用决策。
    跨源不一致则降级为警告：它可能只是口径差异（是否含北交所/ST/新股），
    需要人看一眼，但不必然代表错。
    """
    q = {**quality, "blockers": list(quality.get("blockers") or []),
         "warnings": list(quality.get("warnings") or [])}
    overall = (recon or {}).get("overall")
    failed = (recon or {}).get("invariants_failed") or []
    if overall == "fail":
        q["blockers"].append({
            "code": "reconcile.invariant",
            "message": "不变量校验失败（" + "；".join(c.get("check", "") for c in failed[:3])
                       + "），说明指标计算本身有误，禁止据此决策",
        })
    elif overall in ("inconsistent", "error"):
        q["warnings"].append({
            "code": "reconcile.mismatch",
            "message": (recon or {}).get("summary") or "数据对账未通过，请到对账页确认口径",
        })
    elif overall == "incomplete":
        q["warnings"].append({
            "code": "reconcile.incomplete",
            "message": "交叉验证路径缺数，本次只验证了单一来源（不等于数据正确）",
        })

    low = ((senti or {}).get("low_confidence_factors") or [])
    if low:
        q["warnings"].append({
            "code": "sentiment.low_confidence",
            "message": "样本量不足已退回中性分的因子：" + "、".join(low) + "，情绪分判别力下降",
        })

    if q["blockers"]:
        q["level"], q["decision_enabled"] = "invalid", False
    elif q["warnings"] and q["level"] == "complete":
        q["level"] = "limited"
    return q


def _is_final_snapshot(d: str) -> bool:
    """只有已收盘的交易日快照可冻结，盘中反复刷新不得覆盖成历史。"""
    now = now_cn()
    target = dt.date.fromisoformat(normalize_date(d))
    if target < now.date():
        return True
    return target == now.date() and now.hour * 60 + now.minute >= 15 * 60 + 5


async def build(date: str | None = None, force: bool = False) -> dict:
    # 盘中「今天」的实时快照本身就是当前视角，不能用 last_trade_day（15:05 才切日）
    # 判历史，否则盘中请求当天报告会被当成历史。
    target = normalize_date(date or current_trade_date())
    today = normalize_date(current_trade_date())
    if target != today:
        frozen = store.load_snapshot(target)
        if not frozen or not (frozen.get("data_quality") or {}).get("point_in_time"):
            raise ValueError(f"{target} 没有已冻结的历史快照；禁止用当前行情重建历史报告")
        frozen = dict(frozen)
        frozen["historical"] = True
        frozen["markdown"] = to_markdown(frozen)
        return frozen

    d = target
    ov, senti, ml, gl, nw, lad = await asyncio.gather(
        market.overview(force=force),
        sentiment.core(d, force=force),
        sectors.main_line(force=force),
        globalmarket.overview(force=force),
        news_svc.feed(limit=60, force=force),
        limitup.ladder(d, force=force),
    )
    first_board = await screener.run("first_board", d)
    relay = await screener.run("relay", d)
    risk = await screener.run("risk", d)
    game = await screener.run("game_money", d)
    lhb_res = await lhb_svc.daily(d)

    score = senti.get("score") or 0
    turn = (ov.get("turnover") or {})
    vol_score = (turn.get("level") or {}).get("score") if turn.get("total_yi") else None
    vol_score_used = 50.0 if vol_score is None else vol_score
    g_score = (gl.get("signal") or {}).get("score") or 0
    global_score = max(0, min(100, 50 + g_score * 6))
    lines = ml.get("main_lines") or []
    confirmed = ml.get("confirmed_lines") or []
    sector_src = ml.get("sources") or {}
    has_sector = any(sector_src.get(k) not in (None, "", "none", "mock")
                     for k in ("industry", "concept"))
    # 板块数据缺失时主线分按中性 50 计，不能按 0（等于凭空扣掉权重，把「没数据」
    # 伪装成「没有主线」）。拿到板块但无一通过四维确认时给低分。
    if not has_sector or not lines:
        line_score = None
    elif confirmed:
        line_score = min(100, sum(min(30, (l.get("zt_count") or 0) * 6 + (l.get("max_boards") or 0) * 4)
                                  for l in confirmed[:3]) / 1.2)
    else:
        line_score = min(30, sum(min(30, (l.get("zt_count") or 0) * 6 + (l.get("max_boards") or 0) * 4)
                                 for l in lines[:3]) / 4)
    line_score_used = 50.0 if line_score is None else line_score

    raw_parts = {"sentiment": score, "turnover": vol_score_used,
                 "global": global_score, "main_line": line_score_used}
    composite = round(_weighted(raw_parts, params.COMPOSITE), 1)
    band = _composite_band(raw_parts, senti.get("score_band") or {})
    quality = assess_data_quality(senti, ml, gl, turn)
    # 对账：用第二条独立路径复算涨停家数并跑不变量。失败不阻塞报告，但必须如实呈现。
    try:
        recon = await reconcile_svc.run(d, senti=senti)
    except Exception as exc:  # noqa: BLE001
        recon = {"overall": "error", "summary": f"对账未能执行：{type(exc).__name__}",
                 "error": str(exc)[:160]}
    quality = apply_reconcile_gate(quality, recon, senti)
    if quality["decision_enabled"]:
        pos, pos_tip = _position(composite)
    else:
        pos, pos_tip = "不生成仓位", "关键数据缺失，今天只能看结构，不能据此决定仓位"

    metrics = senti.get("metrics") or {}
    idx = {i["key"]: i for i in (ov.get("indices") or [])}
    sh = idx.get("sh000001") or {}
    cyb = idx.get("sz399006") or {}
    zz1000 = idx.get("sh000852") or {}
    gz2000 = idx.get("sz399303") or {}

    style = _style_judge(sh, cyb, zz1000, gz2000)

    payload: dict[str, Any] = {
        "date": d,
        "generated_at": now_cn().strftime("%Y-%m-%d %H:%M:%S"),
        # 研究状态直接读结果账本算出来，不再是手写字符串
        "research_status": track.status(),
        "regime": regime.regime_note(d),
        "historical": False,
        "is_final": _is_final_snapshot(d),
        "data_quality": {**quality, "point_in_time": True},
        "reconcile": recon,
        "composite": {
            "score": composite,
            "band": band,
            "decision_enabled": quality["decision_enabled"],
            "parts": [
                {"name": "市场情绪", "score": round(score, 1), "weight": params.COMPOSITE["sentiment"],
                 "source": "涨停/连板/炸板/可成交溢价"},
                {"name": "成交量能", "score": round(vol_score_used, 1), "weight": params.COMPOSITE["turnover"],
                 "neutral": vol_score is None,
                 "source": ("成交额缺失，按中性50计" if vol_score is None
                            else f"{turn.get('total_yi') or 0}亿 · {(turn.get('level') or {}).get('label','')}")},
                {"name": "外围环境", "score": round(global_score, 1), "weight": params.COMPOSITE["global"],
                 "source": (gl.get("signal") or {}).get("overall", "")},
                {"name": "主线清晰度", "score": round(line_score_used, 1), "weight": params.COMPOSITE["main_line"],
                 "neutral": line_score is None,
                 "source": ("板块数据缺失，按中性50计" if line_score is None
                            else ("、".join(l["name"] for l in confirmed[:3])
                                  or "、".join(l["name"] for l in lines[:3]) + "（均未通过四维确认）"))},
            ],
            "position": pos,
            "position_tip": pos_tip,
        },
        "market": {
            "indices": [sh, cyb, zz1000, gz2000, idx.get("sh000688") or {}, idx.get("bj899050") or {}],
            "turnover": turn,
            "breadth": {"up": metrics.get("up"), "down": metrics.get("down"), "flat": metrics.get("flat"),
                        "up_ratio": metrics.get("up_ratio"), "histogram": metrics.get("histogram")},
            "style": style,
        },
        "sentiment": {
            "score": score, "label": senti.get("label"), "phase": senti.get("phase"),
            "advice": senti.get("advice"), "metrics": metrics, "components": senti.get("components"),
            "score_history": senti.get("score_history"),
            # 下面三项是报告里"证据边界"一节要用的：分数区间、因子有效自由度、
            # 低置信因子，以及可成交溢价的完整统计画像（n/中位数/区间）
            "score_band": senti.get("score_band"),
            "factor_independence": senti.get("factor_independence"),
            "low_confidence_factors": senti.get("low_confidence_factors"),
            "prev_premium_detail": senti.get("prev_premium_detail"),
        },
        "ladder": {"max_boards": lad.get("max_boards"), "levels": lad.get("levels"),
                   "gaps": lad.get("gaps"), "comment": lad.get("comment")},
        "main_lines": lines,
        "confirmed_lines": confirmed,
        "main_line_warnings": ml.get("warnings") or [],
        "sector_taxonomy_ok": ml.get("taxonomy_ok"),
        "hot_concepts": (ml.get("hot_concepts") or [])[:10],
        "flow_in_top": (ml.get("flow_in_top") or [])[:10],
        "flow_out_top": (ml.get("flow_out_top") or [])[:8],
        "global": {"signal": gl.get("signal"), "items": [i for i in (gl.get("items") or []) if i.get("price") is not None]},
        "news": {"hot_words": (nw.get("hot_words") or [])[:15],
                 "important": ([i for i in (nw.get("items") or []) if i.get("important")][:10]
                               or [i for i in (nw.get("items") or []) if "政策" in (i.get("tags") or [])][:6]
                               or (nw.get("items") or [])[:6]),
                 "latest": (nw.get("items") or [])[:12],
                 "sources_ok": nw.get("sources_ok")},
        "lhb": {"top_net": (lhb_res.data or {}).get("items", [])[:8] if lhb_res.data else [],
                "game_stocks": (game.get("items") or [])[:8],
                "seat_rank": ((lhb_res.data or {}).get("seat_rank") or [])[:12] if lhb_res.data else []},
        "picks": {"first_board": (first_board.get("items") or [])[:10],
                  "relay": (relay.get("items") or [])[:8],
                  "risk": (risk.get("items") or [])[:10]},
        "action_plan": _action_plan(composite, senti, lad, lines, gl, metrics, turn, quality),
        "note": store.load_note(d),
        "sources": {"market": (ov.get("meta") or {}).get("source"), "sentiment": senti.get("sources"),
                    "sectors": ml.get("sources"), "global": gl.get("meta", {}).get("source"),
                    "news": nw.get("sources_ok"), "lhb": (lhb_res.meta() or {}).get("source") if hasattr(lhb_res, "meta") else lhb_res.source},
    }
    payload["markdown"] = to_markdown(payload)
    if payload["is_final"]:
        store.save_snapshot(d, {k: v for k, v in payload.items() if k != "markdown"})
    return payload


def _style_judge(sh: dict, cyb: dict, zz1000: dict, gz2000: dict) -> dict:
    def p(d: dict) -> float:
        return d.get("pct") or 0
    small = (p(zz1000) + p(gz2000)) / 2
    big = p(sh)
    diff = small - big
    if p(cyb) - big > 0.8 and diff > 0.5:
        return {"label": "成长/小盘占优", "desc": "创业板+小盘明显强于上证，题材股环境好，游资可积极进攻",
                "play": "打板、连板接力、题材首板"}
    if big - small > 0.8:
        return {"label": "权重/大盘占优", "desc": "上证强于中小盘，通常是银行/石油护盘或机构调仓，题材容易失血",
                "play": "降低题材仓位，或做权重搭台后的补涨小票"}
    if abs(diff) <= 0.5 and abs(p(cyb) - big) <= 0.5:
        return {"label": "均衡/普涨普跌", "desc": "大小盘同步，看成交量决定是普涨还是普跌",
                "play": "跟随主线，避免逆势"}
    return {"label": "结构分化", "desc": "指数分化明显，需精选板块", "play": "只做当日最强主线的龙头"}


def _action_plan(composite: float, senti: dict, lad: dict, lines: list, gl: dict, metrics: dict,
                 turn: dict, quality: dict | None = None) -> list[dict]:
    pos, tip = _position(composite)
    quality = quality or {"decision_enabled": True, "level": "complete", "blockers": [], "warnings": []}
    if not quality["decision_enabled"]:
        pos, tip = "不生成仓位", "关键数据缺失，禁止用这份报告决定仓位"
    phase = (senti.get("phase") or {}).get("phase", "")
    plan = [
        {"step": "0. 数据体检", "detail": (
            "数据完整，可进入决策。" if quality["level"] == "complete"
            else ("存在警告：" + "；".join(x["message"] for x in quality["warnings"])) if quality["level"] == "limited"
            else ("禁止决策：" + "；".join(x["message"] for x in quality["blockers"]))
        )},
        {"step": "1. 定仓位", "detail": f"综合分{composite} → {pos}。{tip}"},
        {"step": "2. 定方向", "detail": ("主线：" + "、".join(f"{l['name']}({l['zt_count']}家涨停/{l['max_boards']}板)"
                                                            for l in lines[:3])) if lines else "无明确主线，降低预期，只做超跌反抽"},
        {"step": "3. 定高度", "detail": f"空间板{lad.get('max_boards') or 0}板，{lad.get('comment','')}。"
                                        f"断层：{lad.get('gaps') or '无'}"},
        {"step": "4. 看外围", "detail": f"{(gl.get('signal') or {}).get('overall','')}："
                                       + "；".join(s["text"] for s in ((gl.get("signal") or {}).get("signals") or [])[:3])},
        {"step": "5. 看情绪", "detail": f"涨停{metrics.get('limit_up')}家/跌停{metrics.get('limit_down')}家，"
                                       f"炸板率{metrics.get('broken_rate')}%，昨涨停今溢价{metrics.get('prev_premium')}%，"
                                       f"晋级率{metrics.get('promote_rate')}%"},
        {"step": "6. 看量能", "detail": f"两市{turn.get('total_yi')}亿（{(turn.get('level') or {}).get('label','')}），"
                                       f"较昨日{(('%+d亿' % turn['delta_yi']) if turn.get('delta_yi') is not None else '—')}"
                                       f" → {(turn.get('level') or {}).get('tip','')}"},
        {"step": "7. 明日预案", "detail": _tomorrow(phase, composite, lad, metrics)},
        {"step": "8. 风控纪律", "detail": "单票不超过总仓30%；打板失败次日竞价不及预期直接砍；"
                                         "跌停家数>10家当日不开新仓；亏损达5%强制减半仓"},
    ]
    return plan


def _tomorrow(phase: str, composite: float, lad: dict, metrics: dict) -> str:
    max_b = lad.get("max_boards") or 0
    if phase == "冰点":
        return "冰点后第一天重点看：①竞价是否有票高开5%以上 ②首板数量能否>30家 ③跌停是否清零。三者满足即情绪修复，可上2-3成打首板"
    if phase == "修复":
        return f"修复期做首板与低位反包，目标{max_b + 1}板能否打开空间；若最高板断板则退回防守"
    if phase == "发酵":
        return f"发酵期主攻主线二板三板接力，龙头{max_b}板若一字则做同板块补涨；关注上午10点前的封板速度"
    if phase == "高潮":
        return "高潮期最危险：龙头一致但跟风开始炸板，逐步兑现，只留最强龙头；警惕「涨停家数创新高但炸板率同步上升」的顶部信号"
    if phase == "退潮":
        return "退潮期禁止接力，只做超跌反弹与错杀龙头的反抽，仓位不超过2成"
    return "分歧期以观望和小仓试错为主，等待方向明确（成交量与涨停家数同步放大）再加仓"


def to_markdown(p: dict) -> str:
    c = p["composite"]
    m = p["sentiment"]["metrics"]
    ph = p["sentiment"]["phase"]
    t = p["market"]["turnover"]
    lines: list[str] = []
    A = lines.append
    A(f"# A股复盘报告 · {p['date']}")
    A("")
    _b = c.get("band") or {}
    _bt = f"（±{_b.get('perturb_pct', 20)}% 参数扰动区间 {_b.get('lo')}–{_b.get('hi')}）" if _b.get("lo") is not None else ""
    A(f"> 生成时间：{p['generated_at']}　综合评分：**{c['score']}**{_bt}　建议仓位：**{c['position']}**")
    A("")
    A("## 一、结论先行")
    q = p.get("data_quality") or {}
    qlabel = {"complete": "完整", "limited": "有限", "invalid": "不足"}.get(q.get("level"), "未知")
    A(f"- 数据体检：**{qlabel}**（{q.get('as_of', '—')}）")
    rs = p.get("research_status") or {}
    A(f"- 结果账本：已冻结 **{rs.get('frozen_days', 0)}** 个交易日 / 已结算 **{rs.get('settled_days', 0)}** 个交易日"
      f"（{rs.get('stage_cn', '未知')}）")
    A(f"- 方法版本：{rs.get('methodology_version', 'unknown')}　参数指纹：`{rs.get('param_digest', '-')}`"
      f"　{'区间内参数未变动' if rs.get('params_stable') else '⚠ 账本内出现多个参数指纹，分段样本不可合并'}")
    A(f"- 验证状态：**{'未验证' if not rs.get('validated') else '已验证'}**（本系统在任何积累程度下都不会自行置为已验证）")
    for issue in (q.get("blockers") or []) + (q.get("warnings") or []):
        A(f"  - {issue.get('message')}")
    A(f"- 情绪周期：**{ph.get('phase')}**（{ph.get('desc')}），情绪分 {p['sentiment']['score']}，{p['sentiment'].get('label')}")
    A(f"- 仓位建议：{c['position']} —— {c['position_tip']}")
    A(f"- 风格判断：{p['market']['style'].get('label')} —— {p['market']['style'].get('desc')}；打法：{p['market']['style'].get('play')}")
    A(f"- 外围环境：{(p['global'].get('signal') or {}).get('overall')} —— {(p['global'].get('signal') or {}).get('tip')}")
    A("")
    A("## 二、结论证据与验证边界")
    A("| 项目 | 当前状态 |")
    A("|---|---|")
    A(f"| 前瞻结果账本 | 冻结 {rs.get('frozen_days', 0)} 日 / 结算 {rs.get('settled_days', 0)} 日 |")
    A(f"| 入场口径 | 候选日次一交易日**开盘价**（不使用候选日收盘价，那是买不到的价格） |")
    A(f"| 交易成本 | 买卖合计 {rs.get('cost_pct', '—')}%（佣金/过户费/印花税/滑点，见 `core/params.COST`） |")
    A(f"| 收益基准 | {rs.get('benchmark', '—')} 同期同口径，逐样本相减 |")
    A(f"| 不可成交样本 | 次日开盘即封死涨停者标记并从统计正文剔除 |")
    A(f"| 显著性检验 | 按交易日分层置换检验 + BH 多重检验校正，见 `/api/track/record` |")
    _si = (p.get("sentiment") or {}).get("factor_independence") or {}
    A(f"| 因子有效自由度 | {_si.get('effective_factors') or '样本不足'} / 名义 {_si.get('nominal_factors', 7)} 个因子"
      f"{'（' + _si['verdict'] + '）' if _si.get('verdict') else ''} |")
    _rc = p.get("reconcile") or {}
    A(f"| 数据对账 | {_rc.get('summary') or '本次未执行（见 /api/reconcile）'} |")
    A("")
    A("能被严格证明的只有两件事：**计算正确**（跨接口对账、按涨跌幅制度表独立判定、不变量测试、"
      "同输入复算哈希一致）和**没有前视偏差**（入场价晚于信号时点、冻结时间戳不可篡改）。")
    A("**策略有效性无法被证明**，只能处于「在某个区间、某套成本假设下尚未被否证」的状态。"
      "下面这些条件全部满足之前，综合分数不代表胜率、预期收益或可直接执行的仓位：")
    for _w in (rs.get("what_would_change_this") or []):
        A(f"- {_w}")
    A("")
    A("## 三、大盘与量能")
    A("| 指数 | 收盘 | 涨跌幅 | 成交额(亿) |")
    A("|---|---|---|---|")
    for i in p["market"]["indices"]:
        if not i.get("name"):
            continue
        A(f"| {i.get('name')} | {i.get('price')} | {i.get('pct')}% | {i.get('amount_yi')} |")
    A("")
    _dy = t.get("delta_yi")
    _ma = t.get("ma5_yi")
    A(f"- 两市成交 **{t.get('total_yi')}亿**（{t.get('level',{}).get('label')}），"
      f"较昨日 {('%+d亿' % _dy) if _dy is not None else '—'}，5日均量 {('%d亿' % _ma) if _ma is not None else '—'}"
      f"{'（估算值，仅供趋势参考）' if t.get('estimated') else ''}")
    A(f"- 量能解读：{t.get('level',{}).get('tip')}")
    b = p["market"]["breadth"]
    A(f"- 涨跌家数：上涨 {b.get('up')} / 下跌 {b.get('down')} / 平盘 {b.get('flat')}，上涨占比 {b.get('up_ratio')}%")
    A("")
    A("## 四、情绪结构（核心）")
    A(f"- 涨停 {m.get('limit_up')} 家｜跌停 {m.get('limit_down')} 家｜炸板 {m.get('broken')} 家（炸板率 {m.get('broken_rate')}%）")
    A(f"- 最高 **{m.get('max_boards')} 板**｜连板 {m.get('lianban_count')} 家｜首板 {m.get('first_board_count')} 家｜一字板 {m.get('one_word_count')} 家")
    _ps = ((p["sentiment"].get("prev_premium_detail") or {}).get("stats") or {})
    _tr = _ps.get("tradable") or {}
    _trci = _tr.get("ci") or {}
    A(f"- **昨涨停可成交溢价（评分口径）{m.get('tradable_premium') if m.get('tradable_premium') is not None else '—'}%**"
      f"｜样本 {m.get('tradable_premium_sample') or 0}/{m.get('premium_sample') or 0}"
      f"｜中位数 {_tr.get('median') if _tr.get('median') is not None else '—'}%"
      f"｜95% 区间 [{_trci.get('lo') if _trci.get('lo') is not None else '—'}, "
      f"{_trci.get('hi') if _trci.get('hi') is not None else '—'}]"
      f"｜胜率 {_tr.get('win_rate') if _tr.get('win_rate') is not None else '—'}%"
      + ("" if _tr.get("reportable") else f"　⚠ {_tr.get('note', '样本量不足，均值不可作结论')}"))
    A(f"- 开盘即封死（买不到）比例 {m.get('unbuyable_rate') if m.get('unbuyable_rate') is not None else '—'}%"
      f"；参考口径：收盘溢价 {m.get('prev_premium')}%（含买不到的样本，不参与评分）、"
      f"隔夜高开 {m.get('open_premium') if m.get('open_premium') is not None else '—'}%")
    A(f"- 晋级率 {m.get('promote_rate')}%｜首板→二板晋级率（代码交集）{m.get('first_promote_rate')}%")
    A(f"- 涨停封单合计 {m.get('fund_total_yi')}亿｜平均封成比 {m.get('avg_seal_ratio')}%")
    A(f"- 天梯：{p['ladder'].get('comment')}")
    A("")
    _sb = (p["sentiment"].get("score_band") or {})
    if _sb.get("lo") is not None:
        A(f"- 情绪分 **{_sb.get('point')}**，±{_sb.get('perturb_pct')}% 参数扰动区间 "
          f"**{_sb.get('lo')}–{_sb.get('hi')}**（宽度 {_sb.get('width')}）。"
          "区间宽度超过两日分差时，日间比较不成立。")
    _lc = p["sentiment"].get("low_confidence_factors") or []
    if _lc:
        A(f"- ⚠ 低置信因子（样本不足已退回中性分）：{'、'.join(_lc)}")
    A("")
    A("| 情绪因子 | 数值 | 得分 | 权重 | 置信 |")
    A("|---|---|---|---|---|")
    for comp in p["sentiment"]["components"]:
        A(f"| {comp['name']} | {comp['value']}{comp.get('unit','')} | {comp['score']} "
          f"| {round(comp['weight']*100, 1)}% | {'低' if comp.get('low_confidence') else '—'} |")
    A("")
    A("## 五、主线与板块")
    if p["main_lines"]:
        for _w in (p.get("main_line_warnings") or []):
            A(f"> ⚠ {_w}")
        if p.get("main_line_warnings"):
            A("")
        A("| 主线 | 涨停家数 | 最高板 | 板块涨幅 | 主力净流入(亿) | 四维确认 | 判定理由 |")
        A("|---|---|---|---|---|---|---|")
        for l in p["main_lines"][:5]:
            _pct = "—" if l.get("pct") is None else f"{l['pct']}%"
            _flow = "—" if l.get("main_flow_yi") is None else l["main_flow_yi"]
            _mark = "✅通过" if l.get("confirmed") else "待确认：" + "、".join(l.get("confirm_gaps") or [])
            A(f"| {l['name']} | {l['zt_count']} | {l['max_boards']} | {_pct} | {_flow} | {_mark} | {l['reason']} |")
        A("")
        A("**主线龙头：**")
        for l in p["main_lines"][:3]:
            names = "、".join(f"{s['name']}({s['boards']}板)" for s in l["stocks"][:4])
            A(f"- {l['name']}：{names}")
    else:
        A("- 今日无明确主线，题材散乱，建议降低仓位")
    A("")
    A("## 六、连板天梯")
    for lv in (p["ladder"].get("levels") or [])[:8]:
        names = "、".join(f"{s['name']}" for s in lv["stocks"][:6])
        A(f"- **{lv['boards']}板**（{lv['count']}家）：{names}")
    A("")
    A("## 七、龙虎榜与资金")
    if p["lhb"].get("game_stocks"):
        A("| 代码 | 名称 | 涨幅 | 知名资金净买(亿) | 资金属性 |")
        A("|---|---|---|---|---|")
        for s in p["lhb"]["game_stocks"][:8]:
            A(f"| {s['code']} | {s['name']} | {s.get('pct')}% | {s.get('fund_yi')} | {'、'.join(s.get('why', [])[:2])} |")
        A("")
    if p["lhb"].get("seat_rank"):
        A("**活跃席位：** " + "；".join(f"{s['dept'][:16]}(净{s['net_yi']}亿)" for s in p["lhb"]["seat_rank"][:6]))
        A("")
    A("## 八、外围市场")
    A("| 品种 | 最新 | 涨跌幅 |")
    A("|---|---|---|")
    for it in p["global"]["items"][:16]:
        A(f"| {it['name']} | {it['price']} | {it['pct']}% |")
    A("")
    for s in ((p["global"].get("signal") or {}).get("signals") or [])[:8]:
        A(f"- [{s['level']}] {s['text']}")
    A("")
    A("## 九、消息面")
    hw = p["news"].get("hot_words") or []
    if hw:
        A("**消息面热词：** " + "、".join(f"{w['word']}({w['count']})" for w in hw[:12]))
        A("")
    for n in (p["news"].get("important") or [])[:6]:
        A(f"- [{n.get('source')}] {n.get('title')}")
    A("")
    A("## 十、明日关注池")
    A("**首板优选：** " + ("、".join(f"{i['name']}{i['code']}({i['score']}分)" for i in (p["picks"]["first_board"] or [])[:8]) or "无"))
    A("")
    A("**接力候选：** " + ("、".join(f"{i['name']}{i['code']}({i['days_board']})" for i in (p["picks"]["relay"] or [])[:6]) or "无"))
    A("")
    A("**风险回避：** " + ("、".join(f"{i['name']}{i['code']}({i.get('risk','')})" for i in (p["picks"]["risk"] or [])[:8]) or "无"))
    A("")
    A("## 十一、作战计划")
    for step in p["action_plan"]:
        A(f"- **{step['step']}**：{step['detail']}")
    A("")
    A("---")
    A(f"*数据来源：东方财富 / 腾讯财经 / 新浪财经 / 华尔街见闻（多源自动切换）。"
      f"样例数据不会进入评分；历史报告只读取已冻结快照。"
      f"参数版本 {rs.get('methodology_version', '-')}，指纹 `{rs.get('param_digest', '-')}`；"
      f"复现方式：固定随机种子 {params.STATS['seed']}，同一输入快照必须复算出同一结果。"
      f"本报告为数据整理与经验规则输出，不构成投资建议。*")
    return "\n".join(lines)