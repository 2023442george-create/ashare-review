"""Yahoo Finance（免费，海外指数第 4 顺位备用；国内网络可能需要代理）。"""
from __future__ import annotations

from ..core import http
from ..core.utils import fnum


async def quote(symbols: list[str]) -> list[dict]:
    if not symbols:
        return []
    url = "https://query1.finance.yahoo.com/v7/finance/quote"
    data = await http.fetch_json(url, source="yahoo", params={"symbols": ",".join(symbols)})
    rows = ((data or {}).get("quoteResponse") or {}).get("result") or []
    out = []
    for r in rows:
        out.append({
            "code": r.get("symbol"),
            "name": r.get("shortName") or r.get("longName") or r.get("symbol"),
            "price": fnum(r.get("regularMarketPrice")),
            "change": fnum(r.get("regularMarketChange")),
            "pct": fnum(r.get("regularMarketChangePercent")),
            "prev_close": fnum(r.get("regularMarketPreviousClose")),
            "open": fnum(r.get("regularMarketOpen")),
            "high": fnum(r.get("regularMarketDayHigh")),
            "low": fnum(r.get("regularMarketDayLow")),
            "amount": fnum(r.get("regularMarketVolume"), 0.0),
            "time": r.get("regularMarketTime"),
        })
    return out


async def chart(symbol: str, rng: str = "5d", interval: str = "1d") -> list[list]:
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
    data = await http.fetch_json(url, source="yahoo", params={"range": rng, "interval": interval})
    res = ((data or {}).get("chart") or {}).get("result") or []
    if not res:
        return []
    ts = res[0].get("timestamp") or []
    q = ((res[0].get("indicators") or {}).get("quote") or [{}])[0]
    out = []
    import datetime as dt

    for i, t in enumerate(ts):
        d = dt.datetime.fromtimestamp(t, dt.timezone.utc).strftime("%Y-%m-%d")
        out.append([d, fnum((q.get("open") or [])[i] if i < len(q.get("open") or []) else None, 0.0),
                    fnum((q.get("close") or [])[i] if i < len(q.get("close") or []) else None, 0.0),
                    fnum((q.get("high") or [])[i] if i < len(q.get("high") or []) else None, 0.0),
                    fnum((q.get("low") or [])[i] if i < len(q.get("low") or []) else None, 0.0),
                    fnum((q.get("volume") or [])[i] if i < len(q.get("volume") or []) else None, 0.0)])
    return out


async def stooq_quote(symbols: list[str]) -> list[dict]:
    """Stooq CSV（完全免费、无鉴权，最后兜底）"""
    url = "https://stooq.com/q/l/"
    text = await http.fetch(url, source="stooq", params={"s": " ".join(symbols), "f": "sd2t2ohlcv", "h": "1", "e": "csv"})
    if not text:
        return []
    out = []
    for line in text.strip().splitlines()[1:]:
        p = line.split(",")
        if len(p) < 7:
            continue
        out.append({
            "code": p[0], "name": p[0], "date": p[1], "time": p[2],
            "open": fnum(p[3]), "high": fnum(p[4]), "low": fnum(p[5]),
            "price": fnum(p[6]), "volume": fnum(p[7] if len(p) > 7 else None, 0.0),
        })
    return out