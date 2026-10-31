"""中证指数有限公司官网接口（免费、无需 token）。

为什么用它做估值主源：沪深300、中证全指、中证红利都是中证公司编制的指数，
它公布的滚动市盈率就是"官方口径"。第三方网站（蛋卷、乐咕等）的 PE 是自己
用成分股财报重算的，和官方值常有 0.1~0.5 的差距，拿来算历史分位时口径不一。

接口：
- /csindex-home/perf/index-perf  指数日行情，带滚动市盈率字段 peg（只有 PE，没有 PB）

注意：本仓库所在环境无法直连该站，字段名依据公开资料编写。
本机首次运行请打开 /api/macro/probe 确认 missing_fields 为空。
"""
from __future__ import annotations

from typing import Any

from ..core import http
from ..core.utils import fnum, to_date

HOST = "https://www.csindex.com.cn"
HEADERS = {"Referer": "https://www.csindex.com.cn/", "Accept": "application/json, text/plain, */*"}

# 日期与市盈率字段的候选名：官网改版时字段名可能变化，按顺序取第一个存在的
DATE_KEYS = ("tradeDate", "date")
PE_KEYS = ("peg", "pe", "peTtm")


class CsindexParseError(ValueError):
    """官网返回了数据但字段对不上时抛出，让 failover 链切到备用源而不是吞掉。"""


def _first_key(row: dict, keys: tuple[str, ...]) -> str | None:
    """在一行数据里按候选顺序找出实际存在的字段名，找不到返回 None。"""
    for k in keys:
        if k in row:
            return k
    return None


def parse_index_perf(payload: Any) -> list[list]:
    """把 index-perf 的响应解析成 [[YYYY-MM-DD, close, pe], ...]（按日期升序）。

    PE 缺失或非正数的行会被跳过：亏损或停算日的 PE 不能参与分位计算，
    当成 0 会把分位整体拉低，看起来像"极度低估"。
    """
    rows = (payload or {}).get("data") if isinstance(payload, dict) else None
    if not isinstance(rows, list) or not rows:
        return []
    first = rows[0] if isinstance(rows[0], dict) else {}
    dk, pk = _first_key(first, DATE_KEYS), _first_key(first, PE_KEYS)
    if not dk or not pk:
        # 有数据但字段名对不上：说明官网改版了，必须报出来而不是返回空列表装作没数据
        raise CsindexParseError(f"index-perf 字段缺失：date={dk} pe={pk}，实际字段 {sorted(first)[:20]}")
    out: list[list] = []
    for r in rows:
        d = to_date(str(r.get(dk) or ""))
        pe = fnum(r.get(pk))
        if d is None or pe is None or pe <= 0:
            continue
        out.append([d.strftime("%Y-%m-%d"), fnum(r.get("close")), round(pe, 4)])
    out.sort(key=lambda x: x[0])
    return out


async def index_perf(code: str, start: str, end: str) -> list[list]:
    """拉取指数日行情 + 滚动市盈率。

    code  : 中证指数代码，如 000300（沪深300）/ 000985（中证全指）/ 000922（中证红利）
    start : 起始日 YYYYMMDD
    end   : 结束日 YYYYMMDD
    """
    params = {"indexCode": code, "startDate": start, "endDate": end}
    # 一次请求即可取回十年日线（约 2400 行），无需分页
    data = await http.fetch_json(f"{HOST}/csindex-home/perf/index-perf", source="csindex",
                                 params=params, headers=HEADERS)
    return parse_index_perf(data)
