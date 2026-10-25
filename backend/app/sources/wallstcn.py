"""华尔街见闻（免费公开接口，海外/宏观资讯质量高，游资看外围消息常用）。"""
from __future__ import annotations

from ..core import http

CHANNELS = {
    "global": "global-channel",      # 全球
    "a股": "a-stock-channel",         # A股
    "us": "us-stock-channel",         # 美股
    "macro": "macro-channel",         # 宏观
}


async def lives(channel: str = "global", limit: int = 60) -> list[dict]:
    ch = CHANNELS.get(channel, channel)
    url = f"https://api-one.wallstcn.com/apiv1/content/lives?channel={ch}&client=pc&limit={limit}"
    data = await http.fetch_json(url, source="wallstcn")
    rows = ((data or {}).get("data") or {}).get("items") or []
    out = []
    for r in rows:
        import datetime as dt

        ts = r.get("display_time") or 0
        tstr = dt.datetime.fromtimestamp(ts, dt.timezone(dt.timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S") if ts else ""
        content = r.get("content_text") or r.get("content") or ""
        out.append({
            "title": (r.get("title") or content[:60]).strip(),
            "summary": content,
            "time": tstr,
            "url": f"https://wallstreetcn.com/livenews/{r.get('id')}" if r.get("id") else "",
            "source": "华尔街见闻",
            "important": bool(r.get("is_important")),
        })
    return out