"""交易制度与统计口径的时间线。

为什么必须有这张表？
因为"涨停"不是一个固定定义。同一句"收盘价等于涨停价"在不同板块、不同年份
指的是不同的百分比：创业板 2020-08-24 之前是 10%、之后是 20%；科创板一直是
20%；北交所是 30%；主板风险警示股是 5%；新股上市头几天根本没有涨跌幅限制。
如果不按"代码 + 日期"去查当日适用档位，而是统一按 10% 判定，那么：

- 独立重算涨停家数时，创业板/科创板的票会被整体漏掉或错判；
- 跨 2020-08-24 的回测会在同一条曲线上混用两种口径，得到的"情绪趋势"是假的；
- "封单/流通市值""封成比"这类分母无关的指标尚可，但凡是和涨跌幅挂钩的阈值
  （比如断板反包里的 pct 判据）全部失真。

同理，统计口径也会变：北向资金盘中实时净买入在 2024 年 8 月中旬起停止披露，
任何跨越该日期的"北向净买入"序列都是两段不同含义的数据拼起来的。

**这张表必须人工维护，且本文件不自认为权威。** 因此每条规则都带 confidence，
对账模块（services/reconcile.py）在发现表与行情不一致时报告差异，而不是默默
相信这张表。宁可暴露"这一天口径不确定"，也不要安静地算错。
"""
from __future__ import annotations

import datetime as dt
import re
from typing import Any

from .utils import to_date

def board_of(code: str) -> str:
    """返回板块标识：main_sh / main_sz / chinext / star / bse / unknown。"""
    c = re.sub(r"^(sh|sz|bj)", "", str(code).strip().lower())
    c = re.sub(r"^\d\.", "", c)
    if c.startswith("688"):
        return "star"
    if c.startswith("30"):
        return "chinext"
    if c.startswith(("43", "83", "87", "88", "920")):
        return "bse"
    if c.startswith(("60",)):
        return "main_sh"
    if c.startswith(("00",)):
        return "main_sz"
    return "unknown"


# 每个板块的涨跌幅档位变更历史：(生效日, 普通股%, 风险警示股%, confidence, 依据)
# 生效日为 None 表示"自该板块设立起"。
LIMIT_HISTORY: dict[str, list[dict[str, Any]]] = {
    "main_sh": [
        {"from": None, "normal": 10.0, "st": 5.0, "confidence": "high",
         "basis": "沪市主板长期制度"},
    ],
    "main_sz": [
        {"from": None, "normal": 10.0, "st": 5.0, "confidence": "high",
         "basis": "深市主板长期制度（含原中小板并入后）"},
    ],
    "chinext": [
        {"from": None, "normal": 10.0, "st": 5.0, "confidence": "high",
         "basis": "创业板注册制改革前"},
        {"from": "2020-08-24", "normal": 20.0, "st": 20.0, "confidence": "high",
         "basis": "创业板注册制改革，涨跌幅由 10% 放宽至 20%，风险警示股同步 20%"},
    ],
    "star": [
        {"from": None, "normal": 20.0, "st": 20.0, "confidence": "high",
         "basis": "科创板自 2019-07-22 开市即为 20%"},
    ],
    "bse": [
        {"from": None, "normal": 30.0, "st": 30.0, "confidence": "medium",
         "basis": "北交所（及其前身精选层）30%；个别品种与新股首日另有规则"},
    ],
    "unknown": [
        {"from": None, "normal": None, "st": None, "confidence": "none",
         "basis": "代码无法归板，涨跌幅档位未知，不得假设 10%"},
    ],
}

# 新股上市初期不设涨跌幅限制的交易日数（0 = 首日即有限制）
# 注意：这是"最少需要排除"的天数，用于避免把无限制涨幅当成涨停。
NEW_LISTING_FREE_DAYS: dict[str, list[dict[str, Any]]] = {
    "star": [{"from": None, "days": 5, "confidence": "high"}],
    "chinext": [{"from": None, "days": 1, "confidence": "low",
                 "basis": "注册制前首日有临时停牌机制而非标准涨跌幅，按 1 日保守排除"},
                {"from": "2020-08-24", "days": 5, "confidence": "high"}],
    "main_sh": [{"from": None, "days": 1, "confidence": "low"},
                {"from": "2023-04-10", "days": 5, "confidence": "medium",
                 "basis": "主板全面注册制后新股前 5 日不设涨跌幅限制"}],
    "main_sz": [{"from": None, "days": 1, "confidence": "low"},
                {"from": "2023-04-10", "days": 5, "confidence": "medium"}],
    "bse": [{"from": None, "days": 1, "confidence": "low"}],
    "unknown": [{"from": None, "days": 5, "confidence": "none"}],
}

# 统计口径变更事件：跨越这些日期的任何时间序列都不是同一种数据
CALIBER_EVENTS: list[dict[str, Any]] = [
    {"date": "2019-07-22", "scope": "star",
     "what": "科创板开市，市场新增一类 20% 涨跌幅标的",
     "breaks": "此前的『涨停家数』与此后不同口径，不可直接比较斜率"},
    {"date": "2020-08-24", "scope": "chinext",
     "what": "创业板注册制改革，涨跌幅 10% → 20%",
     "breaks": "涨停判定、情绪分中的涨停家数、连板高度定义全部断裂；跨该日的回测必须分段"},
    {"date": "2021-11-15", "scope": "bse",
     "what": "北交所开市（30% 涨跌幅）",
     "breaks": "涨停池是否纳入北交所会显著改变家数，需确认数据源口径"},
    {"date": "2023-04-10", "scope": "main",
     "what": "主板全面注册制，新股前 5 日不设涨跌幅限制",
     "breaks": "次新股涨幅不再受限，若未排除会污染涨停家数与最高连板"},
    {"date": "2024-08-19", "scope": "northbound",
     "what": "沪深港通盘中实时净买入/额度数据停止披露",
     "breaks": "此后『北向净买入』只能用成交额口径；跨该日的北向序列含义不同，不可拼接"},
    {"date": "2024-10-08", "scope": "market",
     "what": "本项目未逐条收录的其它交易机制与费率调整",
     "breaks": "提示性条目：跨年度回测前应人工复核该区间的制度公告",
     "confidence": "low"},
]


def _pick(history: list[dict[str, Any]], d: dt.date) -> dict[str, Any]:
    """在按时间排序的规则列表里，取生效日 <= d 的最后一条。"""
    chosen = history[0]
    for row in history:
        f = row.get("from")
        if f is None:
            chosen = row
            continue
        fd = to_date(f)
        if fd and d >= fd:
            chosen = row
    return chosen


def limit_pct(code: str, date: Any, *, is_st: bool = False,
              listed_days: int | None = None) -> dict[str, Any]:
    """查询某只股票在某交易日适用的涨跌幅档位。

    返回 {"pct": float|None, "board": str, "confidence": str, "reason": str}。
    pct 为 None 表示"当日无涨跌幅限制或无法确定"——调用方必须据此跳过该票的
    涨停判定，而不是退回默认 10%。退回默认值就是制造静默错误。
    """
    d = to_date(str(date)) or dt.date.today()
    board = board_of(code)
    rule = _pick(LIMIT_HISTORY.get(board, LIMIT_HISTORY["unknown"]), d)
    free = _pick(NEW_LISTING_FREE_DAYS.get(board, NEW_LISTING_FREE_DAYS["unknown"]), d)

    if listed_days is not None and listed_days <= int(free.get("days") or 0):
        return {"pct": None, "board": board, "confidence": free.get("confidence", "low"),
                "reason": f"上市第 {listed_days} 个交易日，该板块前 {free.get('days')} 日不设涨跌幅限制"}

    pct = rule.get("st") if is_st else rule.get("normal")
    if pct is None:
        return {"pct": None, "board": board, "confidence": rule.get("confidence", "none"),
                "reason": rule.get("basis", "档位未知")}
    return {"pct": float(pct), "board": board, "confidence": rule.get("confidence", "medium"),
            "reason": rule.get("basis", "")}


def is_limit_up_price(close: float | None, prev_close: float | None, code: str, date: Any,
                      *, is_st: bool = False, listed_days: int | None = None,
                      tolerance: float = 0.004) -> dict[str, Any]:
    """独立判定『收盘是否封在涨停价』，不依赖任何数据源提供的涨停池。

    这是对账（reconciliation）用的第二条独立路径：涨停价按交易所四舍五入到分，
    因此用 tolerance 容忍最后一分钱的进位差异，而不是要求浮点完全相等。
    返回 matched=None 表示"该票当日口径不确定，不计入分母"。
    """
    info = limit_pct(code, date, is_st=is_st, listed_days=listed_days)
    if info["pct"] is None or not prev_close or prev_close <= 0 or close is None:
        return {"matched": None, **info}
    theoretical = round(prev_close * (1 + info["pct"] / 100.0) + 1e-9, 2)
    hit = abs(close - theoretical) <= max(0.01, theoretical * tolerance)
    return {"matched": bool(hit), "limit_price": theoretical, **info}


def caveats_for(start: Any, end: Any = None) -> list[dict[str, Any]]:
    """列出 [start, end] 区间内发生的口径变更，供回测/长周期图表显式声明。"""
    s = to_date(str(start))
    e = to_date(str(end)) if end else dt.date.today()
    if not s:
        return []
    out = []
    for ev in CALIBER_EVENTS:
        d = to_date(ev["date"])
        if d and s <= d <= e:
            out.append(ev)
    return out


def regime_note(date: Any) -> dict[str, Any]:
    """给定交易日，返回当日适用的各板块涨跌幅档位，用于报告脚注。"""
    d = to_date(str(date)) or dt.date.today()
    rows = {}
    for board in ("main_sh", "main_sz", "chinext", "star", "bse"):
        rule = _pick(LIMIT_HISTORY[board], d)
        rows[board] = {"normal": rule.get("normal"), "st": rule.get("st"),
                       "confidence": rule.get("confidence")}
    return {"date": d.strftime("%Y-%m-%d"), "limits": rows,
            "maintained_by": "human",
            "warning": "本表人工维护，可能滞后于最新公告；对账模块发现冲突时以实际行情为准并报告差异"}
