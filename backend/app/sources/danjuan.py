"""蛋卷基金（雪球旗下）指数估值接口（免费、无需 token）。

为什么需要它：中证官网只给 PE，不给 PB 和股息率；蛋卷同时给出 PE、PB、
股息率及其历史序列，用作 PE 的备用源和 PB / 股息率的主源。

接口：
- /djapi/index_eva/dj                       全部指数的当前估值（pe/pb/yeild/roe/分位）
- /djapi/index_eva/pe_history/{code}?day=all PE 历史
- /djapi/index_eva/pb_history/{code}?day=all PB 历史

口径提醒：蛋卷的 PE 是自算值，和中证官方值有差异。本模块只返回原始序列，
分位统一由 services/macro.py 用同一套算法计算，不直接采用蛋卷给的分位。

注意：本仓库所在环境无法直连该站，字段名依据公开资料编写，
首次运行请打开 /api/macro/probe 核对。
"""
from __future__ import annotations

import datetime as dt
from typing import Any

from ..core import http
from ..core.utils import CN_TZ, fnum

HOST = "https://danjuanfunds.com"
HEADERS = {"Referer": "https://danjuanfunds.com/djmodule/value-center", "Accept": "application/json"}


def _ms_to_date(ts: Any) -> str | None:
    """蛋卷的时间戳是毫秒；转成北京时间日期字符串。"""
    v = fnum(ts)
    if v is None:
        return None
    if v > 1e11:          # 毫秒
        v = v / 1000
    return dt.datetime.fromtimestamp(v, CN_TZ).strftime("%Y-%m-%d")


def normalize_yield(v: Any) -> float | None:
    """股息率统一成百分数（5.2 表示 5.2%）。

    蛋卷有时给小数（0.052），有时给百分数（5.2）。宽基和红利指数的股息率
    都在 1%~8% 之间，所以 <1 的值按小数处理乘以 100。
    这条启发式只适用于指数级股息率，不要用于个股。
    """
    x = fnum(v)
    if x is None:
        return None
    return round(x * 100, 4) if x < 1 else round(x, 4)


def parse_eva_list(payload: Any) -> dict[str, dict]:
    """解析当前估值列表 → {index_code: {name, pe, pb, dividend_yield, roe, date}}。"""
    items = (((payload or {}).get("data") or {}).get("items")) if isinstance(payload, dict) else None
    out: dict[str, dict] = {}
    for r in items or []:
        code = str(r.get("index_code") or "").upper()
        if not code:
            continue
        out[code] = {
            "name": r.get("name"),
            "pe": fnum(r.get("pe")),
            "pb": fnum(r.get("pb")),
            # 蛋卷接口里的拼写就是 yeild（不是 yield）
            "dividend_yield": normalize_yield(r.get("yeild", r.get("yield"))),
            "roe": normalize_yield(r.get("roe")),
            "date": _ms_to_date(r.get("ts")) or r.get("date"),
        }
    return out


def parse_history(payload: Any, kind: str) -> list[list]:
    """解析 pe_history / pb_history → [[YYYY-MM-DD, value], ...]（升序，剔除非正值）。"""
    data = (payload or {}).get("data") if isinstance(payload, dict) else None
    rows = (data or {}).get(f"index_eva_{kind}_growths") or []
    out: list[list] = []
    for r in rows:
        d = _ms_to_date(r.get("ts"))
        v = fnum(r.get(kind))
        if d and v is not None and v > 0:
            out.append([d, round(v, 4)])
    out.sort(key=lambda x: x[0])
    return out


async def eva_list() -> dict[str, dict]:
    """全部指数的当前估值快照。"""
    data = await http.fetch_json(f"{HOST}/djapi/index_eva/dj", source="danjuan", headers=HEADERS)
    return parse_eva_list(data)


async def history(code: str, kind: str = "pe") -> list[list]:
    """单个指数的 PE 或 PB 全历史。code 形如 SH000300，kind 为 pe / pb。"""
    data = await http.fetch_json(f"{HOST}/djapi/index_eva/{kind}_history/{code}", source="danjuan",
                                 params={"day": "all"}, headers=HEADERS)
    return parse_history(data, kind)
