"""FastAPI 应用入口。

- 挂载 Vue 构建产物（frontend/dist 复制到 backend/static）
- 启动定时任务
- 首次请求前做一次预热（可关闭）
"""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .api.routes import router
from .core import http, scheduler
from .core.config import STATIC_DIR, backend_freshness, settings, static_freshness

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s :: %(message)s",
)
log = logging.getLogger("review")


async def warmup() -> None:
    """预热缓存：把首页要用的数据先拉一遍，前端首屏更快。"""
    from .services import globalmarket, market, sentiment

    try:
        await market.overview()
        await sentiment.core()
        await globalmarket.overview()
        log.info("cache warmup done")
    except Exception as exc:  # noqa: BLE001
        log.warning("warmup failed: %s", exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("%s v%s 启动（offline=%s）", settings.app_name, settings.version, settings.offline)
    fresh = static_freshness()
    if fresh["stale"]:
        # 旧产物会让新页面"不存在"、新字段渲染成空白，而且不报错，必须吵一句
        log.warning("前端产物过期：%s", fresh["reason"])
    from .core.utils import holiday_coverage

    cal = holiday_coverage()
    if not cal["ok"]:
        # 节假日表过期不会报错，只会让交易日历悄悄算错，所以启动时必须吵一句
        log.warning(cal["warning"])
    scheduler.start()
    import asyncio

    if settings.scheduler_enabled and not settings.offline:
        # 晚上才开程序时，补跑今天错过的收盘快照 / 账本冻结 / 宏观快照
        asyncio.create_task(scheduler.catch_up())
    if os.getenv("REVIEW_WARMUP", "1") == "1":
        asyncio.create_task(warmup())
    yield
    scheduler.stop()
    await http.shutdown()


app = FastAPI(title=settings.app_name, version=settings.version, lifespan=lifespan,
              docs_url="/api/docs", openapi_url="/api/openapi.json")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


@app.exception_handler(Exception)
async def unhandled(request, exc):  # noqa: ANN001
    log.exception("unhandled error on %s", request.url.path)
    return JSONResponse(status_code=500, content={"detail": str(exc), "path": request.url.path})


if STATIC_DIR.exists():
    app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")

    @app.get("/")
    async def index():  # noqa: ANN202
        f = STATIC_DIR / "index.html"
        return FileResponse(f) if f.exists() else JSONResponse({"detail": "前端未构建，请执行 npm run build 或使用 npm run dev"})

    @app.get("/{full_path:path}")
    async def spa(full_path: str):  # noqa: ANN202
        if full_path.startswith("api/"):
            # 未知 /api 路径最常见的原因不是"写错了地址"，而是进程还在跑旧代码。
            # 直接把这个判断写进 404 里，省掉一轮"为什么接口不存在"的排查。
            fresh = backend_freshness()
            body = {"detail": "not found", "path": "/" + full_path}
            if fresh["stale"]:
                body["likely_cause"] = "服务进程比代码旧，该接口在本进程启动时还不存在"
                body["fix"] = "重启后端（Ctrl+C 后重新执行 python backend\\run.py 或 scripts\\start.ps1）"
                body["backend"] = fresh
            return JSONResponse(body, status_code=404)
        candidate = STATIC_DIR / full_path
        if candidate.is_file():
            return FileResponse(candidate)
        f = STATIC_DIR / "index.html"
        return FileResponse(f) if f.exists() else JSONResponse({"detail": "前端未构建"}, status_code=404)
else:
    @app.get("/")
    async def root():  # noqa: ANN202
        return {"app": settings.app_name, "version": settings.version,
                "docs": "/api/docs", "hint": "前端未构建：cd frontend && npm install && npm run build"}