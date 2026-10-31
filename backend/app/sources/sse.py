"""上海证券交易所公开查询接口（免费、无需 token）。

用途：ETF 每日基金份额。宽基 ETF 份额突然放大，是"国家队"（汇金等）托底买入
最直接的公开痕迹——成交额会被做市和 T+0 回转放大，份额不会。

接口：query.sse.com.cn/commonQuery.do，sqlId=COMMON_SSE_ZQPZ_ETFZL_XXPL_ETFGM_SEARCH_L
- 必须带 Referer: https://www.sse.com.cn/ ，否则返回 403
- TOT_VOL 单位是"万份"
- 当日数据一般在收盘后至次日上午公布，所以取数时要允许往前回退几天

深交所 ETF（159919 嘉实300、159915 创业板等）份额只有 xlsx 下载或逐页 JSON，
本项目没有 Excel 解析依赖，暂不接入，界面会注明覆盖范围。
"""
from __future__ import annotations

from typing import Any

from ..core import http
from ..core.utils import fnum, to_date

URL = "https://query.sse.com.cn/commonQuery.do"
HEADERS = {"Referer": "https://www.sse.com.cn/"}
SQL_ETF_SCALE = "COMMON_SSE_ZQPZ_ETFZL_XXPL_ETFGM_SEARCH_L"


def parse_etf_scale(payload: Any) -> dict[str, dict]:
    """解析 ETF 份额响应 → {基金代码: {name, date, shares_yi}}，份额单位换算为"亿份"。"""
    rows = (payload or {}).get("result") if isinstance(payload, dict) else None
    out: dict[str, dict] = {}
    for r in rows or []:
        code = str(r.get("SEC_CODE") or "").strip()
        vol = fnum(r.get("TOT_VOL"))
        if not code or vol is None:
            continue
        d = to_date(str(r.get("STAT_DATE") or ""))
        out[code] = {
            "name": r.get("SEC_NAME"),
            "date": d.strftime("%Y-%m-%d") if d else None,
            "shares_yi": round(vol / 1e4, 4),   # 万份 → 亿份
        }
    return out


async def etf_scale(date: str) -> dict[str, dict]:
    """某一统计日（YYYY-MM-DD）全部上交所 ETF 的份额。非交易日或未公布时返回空字典。"""
    params = {
        "isPagination": "true", "pageHelp.pageSize": "10000", "pageHelp.pageNo": "1",
        "pageHelp.beginPage": "1", "pageHelp.cacheSize": "1", "pageHelp.endPage": "1",
        "sqlId": SQL_ETF_SCALE, "STAT_DATE": date,
    }
    data = await http.fetch_json(URL, source="sse", params=params, headers=HEADERS)
    return parse_etf_scale(data)
