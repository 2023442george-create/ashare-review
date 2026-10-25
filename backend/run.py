"""启动入口：python run.py

端口选择策略：**优先 REVIEW_PORT，否则自动挑一个能真正 bind 的端口**。
Windows 的 Hyper-V/WSL 会不断把 1024-15000 里的随机区段划进「TCP 排除端口范围」
（netsh int ipv4 show excludedportrange protocol=tcp），此时 bind 会报
WinError 10013「以访问权限不允许的方式做了套接字尝试」——看起来像权限问题，
其实是端口被系统预约了。写死任何端口都会在某次开机后失效，所以这里逐个探测。

候选端口刻意选在动态端口范围（默认 1024-15000）之外，避免再被吞。
"""
import os
import socket
import sys

import uvicorn

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 动态端口范围之外，且避开常见开发端口
CANDIDATES = [18080, 18081, 18888, 19090, 28080, 9090, 8088, 8080]


def _bindable(host: str, port: int) -> bool:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind((host, port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def pick_port(host: str, preferred: int | None) -> int:
    for p in ([preferred] if preferred else []) + CANDIDATES:
        if p and _bindable(host, p):
            return p
    raise SystemExit(
        "找不到可用端口：候选 %s 全部被占用。请设置 REVIEW_PORT 指定其它端口。" % CANDIDATES
    )


def main() -> None:
    host = os.getenv("REVIEW_HOST", "127.0.0.1")
    preferred = int(os.getenv("REVIEW_PORT", "0") or 0)
    port = pick_port(host, preferred)
    reload = os.getenv("REVIEW_RELOAD", "0") == "1"
    print(f"[ashare-review] http://{host}:{port}  (docs: /api/docs)", flush=True)
    uvicorn.run("app.main:app", host=host, port=port, reload=reload, log_level="info")


if __name__ == "__main__":
    main()
