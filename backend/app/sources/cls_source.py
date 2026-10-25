"""财联社电报（免费，但接口带签名校验，作为第 4 顺位备用源）。

财联社 sign 算法历史上变更过多次，这里内置 3 种候选算法逐一尝试，
全部失败也不影响系统（会自动降级到华尔街见闻 / 东财 / 新浪）。
"""
from __future__ import annotations

import hashlib
import time
import urllib.parse

from ..core import http

BASE = {"app": "CailianpressWeb", "os": "web", "sv": "7.7.5"}


def _sign_candidates(params: dict) -> list[str]:
    items = sorted(params.items())
    qs = urllib.parse.urlencode(items)
    tail = "app=CailianpressWeb&os=web&sv=7.7.5"
    md5 = hashlib.md5
    return [
        md5((md5(qs.encode()).hexdigest() + tail).encode()).hexdigest(),
        md5((qs + tail).encode()).hexdigest(),
        md5(md5(qs.encode()).hexdigest().encode()).hexdigest(),
        md5(qs.encode()).hexdigest(),
    ]


async def telegraph(limit: int = 50) -> list[dict]:
    params = dict(BASE)
    params.update({"rn": str(limit), "lastTime": str(int(time.time())), "category": "", "refresh_type": "1"})
    for sign in _sign_candidates(params):
        p = dict(params)
        p["sign"] = sign
        url = "https://www.cls.cn/nodeapi/updateTelegraphList?" + urllib.parse.urlencode(sorted(p.items()))
        data = await http.fetch_json(url, source="cls")
        rows = ((data or {}).get("data") or {}).get("roll_data") or []
        if not rows:
            continue
        out = []
        for r in rows:
            import datetime as dt

            ts = r.get("ctime") or 0
            tstr = dt.datetime.fromtimestamp(ts, dt.timezone(dt.timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S") if ts else ""
            content = r.get("content") or r.get("brief") or ""
            out.append({
                "title": (r.get("title") or content[:60]).strip(),
                "summary": content,
                "time": tstr,
                "url": f"https://www.cls.cn/detail/{r.get('id')}" if r.get("id") else "",
                "source": "财联社",
                "important": bool(r.get("level")) and str(r.get("level")) not in ("0", "B"),
            })
        if out:
            return out
    return []