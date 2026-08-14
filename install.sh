#!/usr/bin/env bash
# =============================================================================
# zhuceji (grok-register) 一键安装 + 部署脚本
#
# 用法（任意目录，需要 git 和 bash）:
#   curl -fsSL https://raw.githubusercontent.com/quanshizuiliangdezai/zhuceji/main/install.sh | bash
#
# 自定义端口 / 监听地址:
#   curl ... | PORT=8080 HOST=0.0.0.0 bash
#
# 脚本逻辑:
#   1. 检测当前目录是否已是仓库根（存在 deploy.sh）
#   2. 若不是，则 git clone 到 ./zhuceji
#   3. 调用仓库内的 deploy.sh 完成 venv/依赖/配置/启动
# =============================================================================
set -euo pipefail

REPO_URL="https://github.com/quanshizuiliangdezai/zhuceji.git"
INSTALL_DIR="${INSTALL_DIR:-zhuceji}"

if [ -f "deploy.sh" ]; then
  echo "[*] 检测到当前目录已是仓库根，直接执行 deploy.sh ..."
  exec bash deploy.sh
fi

if [ -d "$INSTALL_DIR" ]; then
  echo "[*] 目录 $INSTALL_DIR 已存在，进入更新 ..."
  cd "$INSTALL_DIR"
  if [ -d .git ]; then
    git pull --ff-only || echo "    (git pull 失败，继续使用当前代码)"
  fi
else
  echo "[*] 克隆仓库到 ./$INSTALL_DIR ..."
  git clone "$REPO_URL" "$INSTALL_DIR"
  cd "$INSTALL_DIR"
fi

echo "[*] 调用 deploy.sh 完成部署 ..."
exec bash deploy.sh
