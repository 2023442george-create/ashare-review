"""异步 HTTP 客户端：重试、UA 轮询、GBK 解码、来源健康度统计。

所有数据源都通过这里出网，因此限流/超时/编码问题只需在一处解决。
"""
from __future__ import annotations

import asyncio
import itertools
import logging
import random
import time
from typing import Any

import httpx

from .config import settings
from .utils import decode_bytes

log = logging.getLogger("review.http")

_client: httpx.AsyncClient | None = None
_ua_cycle = itertools.cycle(settings.user_agents)
_semaphore: asyncio.Semaphore | None = None

# 来源健康度统计：{source: {"ok":n,"fail":n,"ms":x,"last_error":str}}
SOURCE_STATS: dict[str, dict[str, Any]] = {}

# ---------------- 主机级熔断 ----------------
# 某些网络环境下个别域名会被限流/阻断（例如 push2.eastmoney.com 走不通但
# push2delay.eastmoney.com 正常）。连续失败的主机会被临时跳过，避免每次都白等重试。
HOST_FAIL_THRESHOLD = 2
HOST_BLOCK_SECONDS = 240.0
_HOST_STATE: dict[str, list[float]] = {}   # host -> [连续失败次数, 解封时间戳]


def _host_of(url: str) -> str:
    try:
        from urllib.parse import urlparse

        return urlparse(url).netloc or url[:40]
    except Exception:  # noqa: BLE001
        return url[:40]


def host_blocked(url: str) -> bool:
    st = _HOST_STATE.get(_host_of(url))
    if not st:
        return False
    if st[1] and st[1] > time.time():
        return True
    if st[1] and st[1] <= time.time():
        _HOST_STATE.pop(_host_of(url), None)
    return False


def note_host(url: str, ok: bool) -> None:
    h = _host_of(url)
    st = _HOST_STATE.setdefault(h, [0.0, 0.0])
    if ok:
        st[0] = 0.0
        st[1] = 0.0
        return
    st[0] += 1
    if st[0] >= HOST_FAIL_THRESHOLD:
        st[1] = time.time() + HOST_BLOCK_SECONDS


def host_state() -> dict[str, Any]:
    now = time.time()
    return {h: {"fails": int(v[0]), "blocked_seconds_left": max(0, round(v[1] - now)) if v[1] else 0}
            for h, v in _HOST_STATE.items() if v[0] > 0}


def _sem() -> asyncio.Semaphore:
    global _semaphore
    if _semaphore is None:
        _semaphore = asyncio.Semaphore(settings.concurrency)
    return _semaphore


def get_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(
            timeout=httpx.Timeout(settings.timeout, connect=min(6.0, settings.timeout)),
            limits=httpx.Limits(max_connections=64, max_keepalive_connections=16),
            follow_redirects=True,
            http2=False,
            verify=False,  # 部分行情站点证书链不完整，行情数据无敏感性
        )
    return _client


async def close_client() -> None:
    global _client
    if _client is not None and not _client.is_closed:
        await _client.aclose()
    _client = None


def record(source: str, ok: bool, ms: float, error: str = "") -> None:
    st = SOURCE_STATS.setdefault(source, {"ok": 0, "fail": 0, "ms": 0.0, "last_error": "", "last_ok_at": None})
    if ok:
        st["ok"] += 1
        st["ms"] = round(ms, 1)
        st["last_error"] = ""
        st["last_ok_at"] = time.time()
    else:
        st["fail"] += 1
        st["last_error"] = error[:160]


async def fetch(
    url: str,
    *,
    source: str = "unknown",
    params: dict | None = None,
    headers: dict | None = None,
    encoding: str | None = None,
    retries: int | None = None,
    method: str = "GET",
    json_body: Any = None,
) -> str | None:
    """返回文本；失败返回 None（由上层 failover 到备用源）。"""
    if settings.offline:
        return None
    if host_blocked(url):
        record(source, False, 0.0, "host circuit-breaker open")
        return None
    tries = settings.max_retries + 1 if retries is None else retries + 1
    last_err = ""
    for attempt in range(tries):
        h = {"User-Agent": next(_ua_cycle), "Accept": "*/*", "Connection": "keep-alive"}
        if headers:
            h.update(headers)
        t0 = time.perf_counter()
        try:
            async with _sem():
                resp = await get_client().request(method, url, params=params, headers=h, json=json_body)
            ms = (time.perf_counter() - t0) * 1000
            if resp.status_code != 200:
                last_err = f"HTTP {resp.status_code}"
                record(source, False, ms, last_err)
                if resp.status_code in (403, 404, 401):
                    break
                await asyncio.sleep(0.25 * (attempt + 1) + random.random() * 0.15)
                continue
            raw = resp.content
            text = raw.decode(encoding) if encoding else decode_bytes(raw)
            record(source, True, ms)
            note_host(url, True)
            return text
        except Exception as exc:  # noqa: BLE001 - 网络异常统一降级
            ms = (time.perf_counter() - t0) * 1000
            last_err = f"{type(exc).__name__}: {exc}"
            record(source, False, ms, last_err)
            note_host(url, False)
            if attempt + 1 < tries:
                await asyncio.sleep(0.3 * (attempt + 1) + random.random() * 0.2)
    if last_err:
        log.debug("[%s] %s -> %s", source, url[:90], last_err)
    return None


async def fetch_json(url: str, *, source: str = "unknown", **kw: Any) -> Any | None:
    text = await fetch(url, source=source, **kw)
    if not text:
        return None
    return parse_json(text, source=source)


def parse_json(text: str, *, source: str = "unknown") -> Any | None:
    import json

    from .utils import strip_jsonp

    try:
        return json.loads(text)
    except Exception:
        try:
            return json.loads(strip_jsonp(text))
        except Exception as exc:  # noqa: BLE001
            record(source, False, 0, f"JSONDecode: {exc}")
            return None


async def shutdown() -> None:
    await close_client()