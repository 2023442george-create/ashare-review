"""腾讯行情（免费、稳定性高，HTTP 即可访问，是 A 股行情首选源）。

- qt.gtimg.cn/q=            实时行情（GBK 编码）
- web.ifzq.gtimg.cn         日/周/月 K 线
"""
from __future__ import annotations

import re

from ..core import http
from ..core.utils import code_to_symbol, fnum

_LINE = re.compile(r'v_(\w+)="([^"]*)"')


def _parse_line(code: str, body: str) -> dict | None:
    f = body.split("~")
    if len(f) < 40:
        return None
    price = fnum(f[3])
    prev = fnum(f[4])
    if price is None or price == 0:
        return None
    amount_wan = fnum(f[37], 0.0)
    return {
        "code": code,
        "symbol": f[2],
        "name": f[1],
        "price": price,
        "prev_close": prev,
        "open": fnum(f[5]),
        "high": fnum(f[33]),
        "low": fnum(f[34]),
        "change": fnum(f[31]),
        "pct": fnum(f[32]),
        "volume": fnum(f[36], 0.0),               # 手
        "amount": (amount_wan or 0) * 10000,      # 元
        "turnover": fnum(f[38]),
        "pe": fnum(f[39]),
        "amplitude": fnum(f[43]),
        "float_mv": (fnum(f[44]) or 0) * 1e8,
        "total_mv": (fnum(f[45]) or 0) * 1e8,
        "pb": fnum(f[46]),
        "limit_up": fnum(f[47]),
        "limit_down": fnum(f[48]),
        "time": f[30] if len(f) > 30 else "",
    }


async def quote(codes: list[str]) -> list[dict]:
    """codes 支持 'sh000001' / '000001' / 'hkHSI' / 'usDJI'"""
    syms = []
    for c in codes:
        s = c if re.match(r"^(sh|sz|bj|hk|us)", str(c), re.I) else code_to_symbol(c)
        syms.append(s)
    if not syms:
        return []
    out: list[dict] = []
    # 腾讯单次最多约 60 个代码，分批
    for i in range(0, len(syms), 50):
        batch = syms[i:i + 50]
        text = await http.fetch("http://qt.gtimg.cn/q=" + ",".join(batch), source="tencent", encoding="gbk")
        if not text:
            continue
        for code, body in _LINE.findall(text):
            parsed = _parse_line(code, body)
            if parsed:
                out.append(parsed)
    return out


async def kline(symbol: str, period: str = "day", count: int = 120, fq: str = "qfq") -> list[list]:
    """返回 [[date, open, close, high, low, volume, amount(元)], ...]；symbol 支持 sh/sz/bj/hk 前缀。

    newfqkline 比 fqkline 多带成交额（第 9 列，万元），不需要再按成交量推算。
    """
    sym = symbol if re.match(r"^(sh|sz|bj|hk)", str(symbol)) else code_to_symbol(symbol)
    url = f"https://web.ifzq.gtimg.cn/appstock/app/newfqkline/get?param={sym},{period},,,{count},{fq}"
    data = await http.fetch_json(url, source="tencent")
    if not data:
        return []
    node = ((data.get("data") or {}).get(sym) or {})
    rows = node.get(period) or node.get(f"{fq}{period}") or []
    out = []
    for r in rows:
        if isinstance(r, list) and len(r) >= 6:
            amount_wan = fnum(r[8]) if len(r) > 8 else None
            out.append([r[0]] + [fnum(x, 0.0) for x in r[1:6]] + [amount_wan * 1e4 if amount_wan else None])
    return out


async def stock_flow(limit: int = 50) -> list[dict] | None:
    """全 A 个股主力净流入榜（zljlr、turnover 单位都是万元）。东财不可用时的备用源。"""
    data = await http.fetch_json(
        "https://proxy.finance.qq.com/cgi/cgi-bin/rank/hs/getBoardRankList", source="tencent",
        params={"_appver": "11.17.0", "board_code": "aStock", "sort_type": "netMainIn",
                "direct": "down", "offset": 0, "count": limit},
    )
    rows = ((data or {}).get("data") or {}).get("rank_list") or []
    out = []
    for r in rows:
        flow_wan, amount_wan = fnum(r.get("zljlr")), fnum(r.get("turnover"))
        out.append({
            "code": str(r.get("code") or "")[2:], "name": r.get("name"), "price": fnum(r.get("zxj")),
            "pct": fnum(r.get("zdf")),
            "main_flow": flow_wan * 1e4 if flow_wan is not None else None,
            "main_flow_yi": round(flow_wan / 1e4, 2) if flow_wan is not None else None,
            "main_flow_ratio": round(flow_wan / amount_wan * 100, 2) if flow_wan is not None and amount_wan else None,
            "super_flow_yi": None, "big_flow_yi": None,   # 腾讯不拆超大单/大单
            "turnover": fnum(r.get("hsl")), "total_mv_yi": fnum(r.get("zsz")),
        })
    return out or None


# ---------------- 板块排行（行业 / 概念） ----------------
# proxy.finance.qq.com 在国内直连可用，且带主力净流入，是东财 push2 不可用时
# 唯一能拿到「板块涨幅 + 资金」的免费源。zljlr 单位是万元。
BOARD_URL = "https://proxy.finance.qq.com/cgi/cgi-bin/rank/pt/getRank"


async def board_rank(kind: str = "hy", limit: int = 60) -> list[dict] | None:
    """板块排行。kind: hy=申万一级行业, gn=概念题材。"""
    data = await http.fetch_json(
        BOARD_URL, source="tencent",
        params={"board_type": kind, "sort_type": "price", "direct": "down",
                "offset": 0, "count": max(40, limit)},
    )
    rows = ((data or {}).get("data") or {}).get("rank_list") or []
    if not rows:
        return None
    out: list[dict] = []
    for r in rows:
        lead = r.get("lzg") or {}
        flow_wan = fnum(r.get("zljlr"))
        out.append({
            "code": r.get("code"),
            "name": r.get("name"),
            "pct": fnum(r.get("zdf")),
            "change": fnum(r.get("zd")),
            "price": fnum(r.get("zxj")),
            "main_flow": round(flow_wan * 1e4, 2) if flow_wan is not None else None,
            "main_flow_yi": round(flow_wan / 1e4, 2) if flow_wan is not None else None,
            # 腾讯 zgb「上涨/下跌」语义无法核实（银行返回 13/42=55，但申万银行仅 42 只），
            # 按「取不到可信数据就不做」的原则不采用。
            "up_count": None,
            "down_count": None,
            "lead_stock": lead.get("name"),
            "lead_code": lead.get("code"),
            "lead_pct": fnum(lead.get("zdf")),
            "turnover": fnum(r.get("hsl")),
            "float_mv_yi": fnum(r.get("ltsz")),
            "total_mv_yi": fnum(r.get("zsz")),
            "pct_5d": fnum(r.get("zdf_d5")),
            "pct_20d": fnum(r.get("zdf_d20")),
            "amount_yi": None,
            "taxonomy": "申万一级" if kind == "hy" else "腾讯概念",
        })
    return out
