#!/usr/bin/env bash
# 复盘罗盘 · 一键启动（macOS / Linux）
set -e
root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$root"

PY="$(command -v python3 || command -v python)"
[ -z "$PY" ] && { echo "[x] 未找到 Python3"; exit 1; }
echo "[ok] Python: $PY ($($PY --version 2>&1))"

if ! $PY -c "import fastapi, uvicorn, httpx, apscheduler" 2>/dev/null; then
  echo "[..] 安装后端依赖..."
  $PY -m pip install -r backend/requirements.txt --quiet
fi
echo "[ok] 后端依赖就绪"

# 产物不存在、或 frontend 源码比产物更新时都要重建。
# 只判断"产物存不存在"会让改过源码的人一直看旧界面，而且没有任何报错。
need_build=0
[ ! -f backend/static/index.html ] && need_build=1
if [ -f backend/static/index.html ]; then
  newer="$(find frontend/src frontend/index.html frontend/package.json frontend/vite.config.js \
           -newer backend/static/index.html -type f 2>/dev/null | head -1 || true)"
  if [ -n "$newer" ]; then
    echo "[..] 前端源码（$newer）比构建产物新，重新构建"
    need_build=1
  fi
fi
if [ "$need_build" = "1" ]; then
  if command -v npm >/dev/null; then
    echo "[..] 构建前端（1-2 分钟；Ctrl+C 跳过，服务仍会启动）..."
    # 构建失败绝不能中断启动：界面旧只是难看，服务起不来会被当成数据全丢。
    if (cd frontend && npm install --no-audit --no-fund && npm run build); then
      echo "[ok] 前端已重建"
    else
      echo "[!] 前端未重建，界面仍是上一版产物；稍后执行 cd frontend && npm install && npm run build"
      echo "[i] 后端与全部接口不受影响，照常启动"
    fi
  else
    echo "[!] 未找到 npm，跳过前端构建（API 仍可用，但界面是旧版本）"
  fi
else
  echo "[ok] 前端产物是最新的"
fi

export REVIEW_PORT="${REVIEW_PORT:-18080}"
echo "== 服务启动中，浏览器打开 http://127.0.0.1:$REVIEW_PORT （若该端口被系统占用会自动顺延，实际端口见下一行）=="
exec $PY backend/run.py