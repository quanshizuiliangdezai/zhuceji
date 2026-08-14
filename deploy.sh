#!/usr/bin/env bash
# =============================================================================
# zhuceji (grok-register) 一键部署脚本
# 适用: Git Bash (Windows) / Linux / macOS
#
# 用法:
#   bash deploy.sh              # 默认监听 127.0.0.1:8092
#   PORT=8080 bash deploy.sh     # 自定义端口
#   HOST=0.0.0.0 bash deploy.sh  # 允许局域网/外网访问
#   bash deploy.sh update        # 部署前先 git pull 最新代码
#
# 做了什么:
#   1. 选择 python3 / python
#   2. 创建 .venv 虚拟环境 (已存在则跳过)
#   3. 安装 requirements-web.txt (含 WebUI 依赖 + 基础依赖)
#   4. 若不存在 config.json, 从 config.example.json 复制
#   5. 释放被占用的端口 (fuser/lsof)
#   6. 后台启动 web.server, 日志写入 web-deploy.log
# =============================================================================
set -euo pipefail

cd "$(dirname "$0")"

# ---- 1. 选择 Python ----
if command -v python3 >/dev/null 2>&1; then
  PY=python3
elif command -v python >/dev/null 2>&1; then
  PY=python
else
  echo "错误: 未找到 Python, 请先安装 Python 3.9+" >&2
  exit 1
fi

PYVER=$("$PY" -c "import sys; print('%d.%d' % sys.version_info[:2])")
echo "[*] 使用 Python $PYVER"

# ---- 可选: 更新代码 ----
if [ "${1:-}" = "update" ]; then
  if [ -d .git ]; then
    echo "[*] 更新代码 (git pull) ..."
    git pull --ff-only || echo "    (git pull 失败, 继续用当前代码)"
  fi
fi

# ---- 2. 虚拟环境 ----
if [ ! -d .venv ]; then
  echo "[1/4] 创建虚拟环境 .venv ..."
  "$PY" -m venv .venv
fi

if [ -f .venv/bin/activate ]; then
  source .venv/bin/activate
elif [ -f .venv/Scripts/activate ]; then
  source .venv/Scripts/activate
else
  echo "错误: 虚拟环境激活脚本缺失" >&2
  exit 1
fi

# 激活后强制使用 venv 内的 python (避免 Windows 上 python3 绕过 venv)
if [ -x .venv/bin/python ]; then
  PY=.venv/bin/python
elif [ -x .venv/Scripts/python.exe ]; then
  PY=.venv/Scripts/python.exe
fi

# ---- 3. 依赖 ----
echo "[2/4] 安装 / 更新依赖 ..."
pip install --upgrade pip -q
pip install -r requirements-web.txt

# ---- 4. 配置 ----
if [ ! -f config.json ]; then
  if [ -f config.example.json ]; then
    echo "[3/4] 复制示例配置 config.example.json -> config.json"
    cp config.example.json config.json
    echo "      提示: 可直接在 WebUI 中填写配置, 或编辑 config.json"
  else
    echo "[3/4] 未找到 config.example.json, 跳过配置复制"
  fi
else
  echo "[3/4] config.json 已存在, 跳过"
fi

# ---- 5. 释放端口 ----
PORT="${PORT:-8092}"
HOST="${HOST:-127.0.0.1}"
echo "[4/4] 启动 WebUI (http://$HOST:$PORT) ..."

release_port() {
  local port="$1"
  if command -v fuser >/dev/null 2>&1; then
    fuser -k "${port}/tcp" 2>/dev/null || true
  elif command -v lsof >/dev/null 2>&1; then
    local p
    p=$(lsof -ti "tcp:${port}" 2>/dev/null || true)
    [ -n "$p" ] && kill $p 2>/dev/null || true
  elif command -v netstat >/dev/null 2>&1; then
    # Windows (Git Bash): 仅杀真正 LISTENING 该端口的进程, 避免误杀客户端(chrome 等)
    local pids
    pids=$(netstat -ano 2>/dev/null | awk -v port="${port}" '$2 ~ (":" port "$") && $4 == "LISTENING" {print $5}' | grep -E '^[0-9]+$' | sort -u)
    for p in $pids; do
      cmd //c "taskkill /F /PID $p" >/dev/null 2>&1 || true
    done
  fi
}

release_port "$PORT"
sleep 1

# ---- 6. 后台启动 ----
nohup "$PY" -m web.server --host "$HOST" --port "$PORT" > web-deploy.log 2>&1 &
NEW_PID=$!
sleep 2
if kill -0 "$NEW_PID" 2>/dev/null; then
  echo "[OK] 已启动, PID=$NEW_PID"
  echo "     访问: http://$HOST:$PORT"
  echo "     日志: web-deploy.log"
else
  echo "[失败] 启动后进程退出, 请查看 web-deploy.log:"
  tail -n 20 web-deploy.log 2>/dev/null || true
  exit 1
fi
