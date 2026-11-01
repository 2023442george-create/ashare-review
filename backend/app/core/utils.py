"""通用工具：交易日历、日期、数字格式化、编码解析。"""
from __future__ import annotations

import datetime as dt
import re
from typing import Any, Iterable

CN_TZ = dt.timezone(dt.timedelta(hours=8))

# A股法定节假日（需人工/接口维护，未命中时按周末规则回退）
CN_HOLIDAYS: set[str] = {
    # 2026
    "2026-01-01", "2026-01-02", "2026-02-16", "2026-02-17", "2026-02-18",
    "2026-02-19", "2026-02-20", "2026-02-23", "2026-04-06", "2026-05-01", "2026-05-04",
    "2026-05-05", "2026-06-19", "2026-09-25", "2026-10-01", "2026-10-02",
    "2026-10-05", "2026-10-06", "2026-10-07",
}


def holiday_coverage(today: dt.date | None = None) -> dict[str, Any]:
    """检查节假日表是否覆盖今年和（12 月起）明年。

    为什么需要：表里没有的年份会把春节、国庆当成交易日——定时任务照跑、
    结果账本按"节日当天开盘"去结算、历史窗口多算交易日，而且这些错误都不报错。
    国务院办公厅一般在每年 11~12 月公布次年安排，公布后补进 CN_HOLIDAYS。
    """
    today = today or now_cn().date()
    years = sorted({int(d[:4]) for d in CN_HOLIDAYS})
    need = [today.year] + ([today.year + 1] if today.month == 12 else [])
    missing = [y for y in need if y not in years]
    return {
        "years": years, "missing": missing, "ok": not missing,
        "warning": (f"节假日表缺少 {'、'.join(map(str, missing))} 年，交易日历会把节假日当成交易日；"
                    "请在 backend/app/core/utils.py 的 CN_HOLIDAYS 补上国务院公布的休市日期") if missing else "",
    }


def now_cn() -> dt.datetime:
    return dt.datetime.now(CN_TZ)


def is_trade_day(d: dt.date) -> bool:
    if d.weekday() >= 5:
        return False
    return d.strftime("%Y-%m-%d") not in CN_HOLIDAYS


def last_trade_day(base: dt.date | None = None) -> dt.date:
    """最近一个已收盘的交易日（15:05 之前算前一日）。"""
    d = base or now_cn().date()
    if base is None and now_cn().hour * 60 + now_cn().minute < 15 * 60 + 5:
        d = d - dt.timedelta(days=1)
    for _ in range(30):
        if is_trade_day(d):
            return d
        d -= dt.timedelta(days=1)
    return d


def current_trade_date() -> dt.date:
    """当前「展示交易日」。

    交易日 09:15 之后就是今天（竞价开始，当天数据已可用）；更早以及周末/节假日
    回退到最近交易日。不能直接用 last_trade_day()：它按 15:05 收盘切日，盘中会
    一直停在前一天。
    """
    now = now_cn()
    minutes = now.hour * 60 + now.minute
    if is_trade_day(now.date()) and minutes >= 9 * 60 + 15:
        return now.date()
    return last_trade_day(now.date())


def prev_trade_day(d: dt.date, n: int = 1) -> dt.date:
    for _ in range(n * 5 + 10):
        d -= dt.timedelta(days=1)
        if is_trade_day(d):
            n -= 1
            if n == 0:
                return d
    return d


def next_trade_day(d: dt.date, n: int = 1) -> dt.date:
    """向后找第 n 个交易日。结果账本结算要用它定位 T+1 开盘与 T+N 收盘。"""
    for _ in range(n * 5 + 20):
        d += dt.timedelta(days=1)
        if is_trade_day(d):
            n -= 1
            if n == 0:
                return d
    return d


def yyyymmdd(d: dt.date | str | None = None) -> str:
    if d is None:
        d = last_trade_day()
    if isinstance(d, str):
        return d.replace("-", "")
    return d.strftime("%Y%m%d")


def to_date(s: str | None) -> dt.date | None:
    if not s:
        return None
    s = s.strip()[:10]
    for fmt in ("%Y-%m-%d", "%Y%m%d", "%Y/%m/%d"):
        try:
            return dt.datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def normalize_date(value: Any, fallback: dt.date | None = None) -> str:
    """统一交易日为 YYYY-MM-DD；无法解析时返回 fallback（默认最近交易日）。

    所有数据库主键、API 查询和跨日比较都应经过这里，避免 20261023 与
    2026-10-23 混存后出现错误的文本排序。
    """
    d = to_date(str(value)) if value not in (None, "") else None
    if d is None:
        d = fallback or last_trade_day()
    return d.strftime("%Y-%m-%d")


_NUM = re.compile(r"-?\d+(?:\.\d+)?")


def fnum(v: Any, default: float | None = None, scale: float = 1.0) -> float | None:
    """宽松数字解析：兼容 '3,911.87'、'--'、''、None。"""
    if v is None:
        return default
    if isinstance(v, (int, float)):
        try:
            f = float(v)
        except (TypeError, ValueError):
            return default
        return None if (f != f or f in (float("inf"), float("-inf"))) else round(f * scale, 6)
    s = str(v).strip().replace(",", "").replace("%", "")
    if s in ("", "-", "--", "—", "None", "null"):
        return default
    m = _NUM.search(s)
    if not m:
        return default
    try:
        return round(float(m.group()) * scale, 6)
    except ValueError:
        return default


def yi(v: float | None, digits: int = 2) -> float | None:
    """元 -> 亿元"""
    return None if v is None else round(v / 1e8, digits)


def decode_bytes(b: bytes, prefers: Iterable[str] = ("utf-8", "gbk", "gb18030")) -> str:
    for enc in prefers:
        try:
            return b.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return b.decode("utf-8", "ignore")


def strip_jsonp(text: str) -> str:
    """去掉 jsonp 包裹：var x=(...) / callback(...)"""
    t = text.strip()
    t = re.sub(r"^/\*.*?\*/", "", t, flags=re.S)
    m = re.search(r"[=(]\s*(\[.*\]|\{.*\})\s*\)?\s*;?\s*$", t, flags=re.S)
    if m:
        return m.group(1)
    i = t.find("(")
    if i > 0 and t.endswith(")"):
        return t[i + 1:-1]
    return t


def code_to_secid(code: str) -> str:
    """'600519'/'sh600519' -> '1.600519' （东财 secid）"""
    c = str(code).strip().lower()
    if "." in c and c.split(".")[0].isdigit():
        return c
    c = re.sub(r"^(sh|sz|bj)", "", c)
    if c.startswith(("60", "68", "11", "51", "58", "9", "000")) and not c.startswith(("00", "30")):
        return f"1.{c}"
    if c.startswith(("43", "83", "87", "92")):
        return f"0.{c}"
    if c.startswith(("00", "30")):
        return f"0.{c}"
    if c.startswith(("60", "68")):
        return f"1.{c}"
    return f"0.{c}"


def code_to_symbol(code: str) -> str:
    """'600519' -> 'sh600519'（腾讯/新浪格式）"""
    c = str(code).strip().lower()
    if c.startswith(("sh", "sz", "bj")):
        return c
    c = re.sub(r"^\d\.", "", c)
    if c.startswith(("43", "83", "87", "92")):
        return "bj" + c
    if c.startswith(("00", "30")):
        return "sz" + c
    return "sh" + c