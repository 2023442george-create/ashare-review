"""全局配置：数据源优先级、超时、缓存 TTL、离线模式等。

所有配置均可用环境变量覆盖，方便在不同网络环境（公司内网 / 家宽 / 代理）下切换。
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = Path(os.getenv("REVIEW_DATA_DIR", BASE_DIR.parent / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
STATIC_DIR = BASE_DIR / "static"


def _bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, "1" if default else "0").lower() in ("1", "true", "yes", "on")


@dataclass
class Settings:
    # 运行
    app_name: str = "复盘罗盘 · 游资版"
    version: str = "1.0.0"
    timezone: str = os.getenv("REVIEW_TZ", "Asia/Shanghai")

    # 网络
    timeout: float = float(os.getenv("REVIEW_TIMEOUT", "10"))
    max_retries: int = int(os.getenv("REVIEW_RETRIES", "2"))
    concurrency: int = int(os.getenv("REVIEW_CONCURRENCY", "12"))

    # 离线 / 演示模式：1 = 不访问外网，直接返回内置样例数据
    offline: bool = _bool("REVIEW_OFFLINE")
    # 是否允许使用 akshare 兜底（需自行 pip install akshare）
    allow_akshare: bool = _bool("REVIEW_ALLOW_AKSHARE", True)

    # 缓存 TTL（秒）
    ttl_quote: int = int(os.getenv("REVIEW_TTL_QUOTE", "20"))
    ttl_pool: int = int(os.getenv("REVIEW_TTL_POOL", "120"))
    ttl_sector: int = int(os.getenv("REVIEW_TTL_SECTOR", "180"))
    ttl_lhb: int = int(os.getenv("REVIEW_TTL_LHB", "600"))
    ttl_news: int = int(os.getenv("REVIEW_TTL_NEWS", "60"))
    ttl_global: int = int(os.getenv("REVIEW_TTL_GLOBAL", "60"))
    ttl_kline: int = int(os.getenv("REVIEW_TTL_KLINE", "1800"))
    ttl_daily: int = int(os.getenv("REVIEW_TTL_DAILY", "21600"))
    # 宏观数据（估值/国债/ETF 份额）一天只更新一次，缓存 6 小时
    ttl_macro: int = int(os.getenv("REVIEW_TTL_MACRO", "21600"))

    # 定时任务
    scheduler_enabled: bool = _bool("REVIEW_SCHEDULER", True)

    # 数据源优先级（数字越小越优先），可在 settings 页热更新
    source_priority: dict = field(
        default_factory=lambda: {
            "quote": ["tencent", "sina", "eastmoney", "akshare", "mock"],
            # 东财 K 线自带真实成交额；腾讯/新浪无成交额，仅作降级。
            "kline": ["eastmoney", "tencent", "sina", "akshare", "mock"],
            "limit_pool": ["eastmoney", "akshare", "mock"],
            "sector": ["eastmoney", "tencent", "sina", "akshare", "mock"],
            "lhb": ["eastmoney", "akshare", "mock"],
            "global": ["tencent", "sina", "eastmoney", "yahoo", "stooq", "mock"],
            "news": ["wallstcn", "eastmoney", "sina", "cls", "mock"],
            "margin": ["eastmoney", "akshare", "mock"],
            # 宏观：估值以中证官网为主（官方口径），蛋卷补 PB/股息率并作 PE 备用
            "valuation": ["csindex", "danjuan", "mock"],
            "bond": ["eastmoney", "eastmoney_legacy", "mock"],
        }
    )

    # 常用 UA 池，轮询降低被限流概率
    user_agents: list = field(
        default_factory=lambda: [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:127.0) Gecko/20100101 Firefox/127.0",
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        ]
    )

    @property
    def db_path(self) -> Path:
        return DATA_DIR / "review.db"


settings = Settings()

FRONTEND_DIR = BASE_DIR.parent / "frontend"

# 本进程的启动时刻。用来判断"跑着的服务是不是比代码还旧"。
PROCESS_START = time.time()


def backend_freshness() -> dict:
    """判断当前进程是否比 backend/app 下的源码更旧。

    为什么需要：改完后端代码却忘记重启，表现是"新接口返回 404、新字段永远是空"，
    和"代码写错了"长得一模一样，于是人会去翻代码而不是去重启。
    前端产物过期（static_freshness）与这里是同一类错误的两半：
    一个是编译产物旧了，一个是运行中的进程旧了。两者都必须能被一眼看出来。
    """
    newest = 0.0
    newest_file = ""
    app_dir = BASE_DIR / "app"
    if app_dir.exists():
        for f in app_dir.rglob("*.py"):
            if "__pycache__" in f.parts:
                continue
            m = f.stat().st_mtime
            if m > newest:
                newest, newest_file = m, str(f.relative_to(BASE_DIR))
    stale = bool(newest and newest > PROCESS_START + 1)
    return {
        "stale": stale,
        "process_started_at": round(PROCESS_START, 0),
        "uptime_seconds": round(time.time() - PROCESS_START),
        "newest_source": newest_file,
        "source_at": round(newest, 0) or None,
        "reason": (f"{newest_file} 在本进程启动之后被修改过，当前运行的是旧代码；"
                   "新接口会返回 404、新字段会一直是空。请重启后端。") if stale else "",
    }


def static_freshness() -> dict:
    """判断 backend/static 里的前端产物是否比 frontend/src 的源码旧。

    为什么需要这个：后端直接托管构建产物，而构建产物是二进制化的 JS。
    源码改了但没重新构建时，界面会安静地跑旧版本——新页面看不到、
    新字段渲染成空白，而且没有任何报错。这类"看起来正常其实是旧的"
    最难排查，所以宁可在启动时吵一句。
    """
    index = STATIC_DIR / "index.html"
    if not index.exists():
        return {"built": False, "stale": True, "built_at": None, "source_at": None,
                "reason": "尚未构建前端（backend/static/index.html 不存在）"}
    built_at = index.stat().st_mtime
    newest = 0.0
    newest_file = ""
    if FRONTEND_DIR.exists():
        for pattern in ("src/**/*", "index.html", "package.json", "vite.config.js"):
            for f in FRONTEND_DIR.glob(pattern):
                if f.is_file():
                    m = f.stat().st_mtime
                    if m > newest:
                        newest, newest_file = m, str(f.relative_to(FRONTEND_DIR))
    stale = bool(newest and newest > built_at + 1)
    return {
        "built": True, "stale": stale,
        "built_at": round(built_at, 0), "source_at": round(newest, 0) or None,
        "newest_source": newest_file,
        "reason": (f"前端源码 {newest_file} 比构建产物更新，界面可能是旧版本；"
                   "请在 frontend 目录执行 npm install && npm run build，"
                   "或运行 scripts\\start.ps1 -Rebuild") if stale else "",
    }