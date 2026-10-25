"""新浪财经（免费）。

- hq.sinajs.cn/list=       A股/指数实时（必须带 Referer，GBK）
- quotes.sina.cn           日 K 线（jsonp）
- zhibo.sina.com.cn        7x24 财经直播（快讯）
- 全球指数/外盘期货/外汇   gb_$dji、int_nikkei、znb_KOSPI、hf_CL、fx_susdcnh
"""
from __future__ import annotations

import re

from ..core import http
from ..core.utils import fnum

REFERER = {"Referer": "https://finance.sina.com.cn"}
_LINE = re.compile(r'var hq_str_(\S+?)="([^"]*)"')


async def quote_raw(codes: list[str]) -> dict[str, list[str]]:
    """返回 {code: [字段...]}，由上层按资产类型解析。"""
    if not codes:
        return {}
    out: dict[str, list[str]] = {}
    for i in range(0, len(codes), 60):
        batch = codes[i:i + 60]
        text = await http.fetch(
            "https://hq.sinajs.cn/list=" + ",".join(batch),
            source="sina", headers=REFERER, encoding="gbk",
        )
        if not text:
            continue
        for code, body in _LINE.findall(text):
            if body.strip():
                out[code] = body.split(",")
    return out


def parse_stock(f: list[str], code: str) -> dict | None:
    """A股/指数完整行情格式"""
    if len(f) < 32:
        return None
    price = fnum(f[3])
    if not price:
        return None
    return {
        "code": code,
        "name": f[0],
        "open": fnum(f[1]),
        "prev_close": fnum(f[2]),
        "price": price,
        "high": fnum(f[4]),
        "low": fnum(f[5]),
        "volume": fnum(f[8], 0.0),   # 股
        "amount": fnum(f[9], 0.0),   # 元
        "change": round(price - (fnum(f[2]) or 0), 4),
        "pct": round((price / fnum(f[2]) - 1) * 100, 4) if fnum(f[2]) else None,
        "date": f[30] if len(f) > 30 else "",
        "time": f[31] if len(f) > 31 else "",
    }


async def quote(codes: list[str]) -> list[dict]:
    raw = await quote_raw(codes)
    out = []
    for code, f in raw.items():
        p = parse_stock(f, code)
        if p:
            out.append(p)
    return out


async def kline(symbol: str, scale: int = 240, count: int = 120) -> list[list]:
    """日K：scale=240(日)/1200(周)/...  返回 [[date,open,high,low,close,volume],...]"""
    url = (
        "https://quotes.sina.cn/cn/api/jsonp_v2.php/var%20_k=/CN_MarketDataService.getKLineData"
        f"?symbol={symbol}&scale={scale}&ma=no&datalen={count}"
    )
    data = await http.fetch_json(url, source="sina")
    if not isinstance(data, list):
        return []
    out = []
    for r in data:
        out.append([
            r.get("day"), fnum(r.get("open"), 0.0), fnum(r.get("close"), 0.0),
            fnum(r.get("high"), 0.0), fnum(r.get("low"), 0.0), fnum(r.get("volume"), 0.0),
        ])
    return out


async def news(limit: int = 60) -> list[dict]:
    """新浪 7x24 财经直播"""
    url = f"https://zhibo.sina.com.cn/api/zhibo/feed?page=1&page_size={limit}&zhibo_id=152&tag_id=0"
    data = await http.fetch_json(url, source="sina")
    rows = ((((data or {}).get("result") or {}).get("data") or {}).get("feed") or {}).get("list") or []
    out = []
    for r in rows:
        rich = r.get("rich_text") or r.get("text") or ""
        out.append({
            "title": rich[:60],
            "summary": rich,
            "time": r.get("create_time") or "",
            "url": "",
            "source": "新浪财经",
            "tags": [t.get("name") for t in (r.get("tag") or []) if isinstance(t, dict)],
        })
    return out

# ---------------- 行业板块（新浪旧版分类，49 个） ----------------
# 该接口返回 GBK 的 JS 变量，一行一个板块。作为腾讯板块的交叉源：
# 它没有主力资金，只有涨幅与成交额，所以资金字段留 None 而不是 0。
HY_URL = "http://vip.stock.finance.sina.com.cn/q/view/newSinaHy.php"


async def industry_rank() -> list[dict] | None:
    text = await http.fetch(HY_URL, source="sina", encoding="gbk", headers=REFERER)
    if not text:
        return None
    m = re.search(r"=\s*\{", text)
    if not m:
        return None
    out: list[dict] = []
    for key, val in re.findall(r'"([^"]+)"\s*:\s*"([^"]*)"', text[m.start():]):
        f = val.split(",")
        if len(f) < 8:
            continue
        amount = fnum(f[7])
        out.append({
            "code": f[0] or key,
            "name": f[1],
            "stock_count": int(fnum(f[2]) or 0),
            "price": fnum(f[3]),
            "change": fnum(f[4]),
            "pct": fnum(f[5]),
            "volume": fnum(f[6]),
            "amount": amount,
            "amount_yi": round(amount / 1e8, 2) if amount else None,
            "lead_code": f[8] if len(f) > 8 else None,
            "lead_pct": fnum(f[9]) if len(f) > 9 else None,
            "lead_stock": None,
            "main_flow": None,
            "main_flow_yi": None,
            "up_count": None,
            "down_count": None,
            "turnover": None,
            "float_mv_yi": None,
            "total_mv_yi": None,
            "taxonomy": "新浪行业",
        })
    return out or None
