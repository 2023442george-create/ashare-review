"""TTL 内存缓存 + 多源 failover 链路。

failover 是本项目「多数据源备用」的核心：每个业务动作给出一组按优先级排序的
候选源，依次尝试，第一个成功即返回，并记录实际命中的来源，前端会显示数据来自哪家。
"""
from __future__ import annotations

import asyncio
import inspect
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Iterable

log = logging.getLogger("review.cache")

_STORE: dict[str, tuple[float, Any]] = {}
_LOCKS: dict[str, asyncio.Lock] = {}


def cache_get(key: str) -> Any | None:
    hit = _STORE.get(key)
    if not hit:
        return None
    exp, val = hit
    if exp and exp < time.time():
        _STORE.pop(key, None)
        return None
    return val


def cache_set(key: str, value: Any, ttl: int) -> None:
    _STORE[key] = (time.time() + ttl if ttl > 0 else 0, value)


def cache_clear(prefix: str | None = None) -> int:
    if prefix is None:
        n = len(_STORE)
        _STORE.clear()
        return n
    keys = [k for k in _STORE if k.startswith(prefix)]
    for k in keys:
        _STORE.pop(k, None)
    return len(keys)


def cache_stats() -> dict[str, Any]:
    return {"entries": len(_STORE), "keys": sorted(_STORE.keys())[:200]}


def _lock_for(key: str) -> asyncio.Lock:
    lk = _LOCKS.get(key)
    if lk is None:
        lk = _LOCKS.setdefault(key, asyncio.Lock())
    return lk


@dataclass
class Sourced:
    """带来源信息的数据包装。"""
    data: Any = None
    source: str = "mock"
    sources_tried: list[str] = field(default_factory=list)
    elapsed_ms: float = 0.0
    cached: bool = False
    error: str = ""

    def meta(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "sources_tried": self.sources_tried,
            "elapsed_ms": round(self.elapsed_ms, 1),
            "cached": self.cached,
            "error": self.error,
        }


Provider = Callable[..., Awaitable[Any]]


async def chain(
    providers: Iterable[tuple[str, Provider]],
    *args: Any,
    cache_key: str | None = None,
    ttl: int = 0,
    force: bool = False,
    validator: Callable[[Any], bool] | None = None,
    **kwargs: Any,
) -> Sourced:
    """按顺序尝试多个数据源，返回第一个通过校验的结果。

    providers: [("tencent", coro_fn), ("sina", coro_fn), ...]
    validator: 判断数据是否可用（例如非空列表），不可用则继续尝试下一个源。
    """
    if cache_key and not force:
        hit = cache_get(cache_key)
        if hit is not None:
            out = Sourced(data=hit[0], source=hit[1], sources_tried=hit[2], cached=True)
            return out

    if cache_key:
        async with _lock_for(cache_key):
            hit = cache_get(cache_key)
            if hit is not None and not force:
                return Sourced(data=hit[0], source=hit[1], sources_tried=hit[2], cached=True)
            return await _run_chain(providers, args, kwargs, cache_key, ttl, validator)
    return await _run_chain(providers, args, kwargs, cache_key, ttl, validator)


def filter_providers(providers: Iterable[tuple[str, Provider]], offline: bool) -> list[tuple[str, Provider]]:
    """样例源只在显式离线模式下启用。

    在线模式下抓取失败必须返回缺失，绝不能把 mock 当成真实行情继续参与
    评分、主线判断或仓位建议。离线模式下则只允许 mock，保证演示结果可复现。
    """
    rows = [(name, fn) for name, fn in providers if fn is not None]
    if offline:
        return [row for row in rows if row[0] == "mock"]
    return [row for row in rows if row[0] != "mock"]


async def _run_chain(providers, args, kwargs, cache_key, ttl, validator) -> Sourced:
    from .config import settings

    providers = filter_providers(providers, settings.offline)
    tried: list[str] = []
    errors: list[str] = []
    t0 = time.perf_counter()
    for name, fn in providers:
        if fn is None:
            continue
        tried.append(name)
        try:
            res = fn(*args, **kwargs)
            if inspect.isawaitable(res):
                res = await res
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{name}:{type(exc).__name__}:{exc}"[:120])
            log.warning("source %s failed: %s", name, exc)
            continue
        ok = True if validator is None else bool(validator(res))
        if not ok:
            errors.append(f"{name}:invalid")
            continue
        el = (time.perf_counter() - t0) * 1000
        if cache_key and ttl:
            cache_set(cache_key, (res, name, tried), ttl)
        return Sourced(data=res, source=name, sources_tried=tried, elapsed_ms=el)
    el = (time.perf_counter() - t0) * 1000
    return Sourced(data=None, source="none", sources_tried=tried, elapsed_ms=el, error="; ".join(errors)[:300])


def order_providers(kind: str, registry: dict[str, Provider]) -> list[tuple[str, Provider]]:
    """按 settings.source_priority 排序，并追加未配置的源作为兜底。"""
    from .config import settings

    prio = settings.source_priority.get(kind, [])
    out: list[tuple[str, Provider]] = []
    for name in prio:
        fn = registry.get(name)
        if fn:
            out.append((name, fn))
    for name, fn in registry.items():
        if name not in prio and fn:
            out.append((name, fn))
    return out