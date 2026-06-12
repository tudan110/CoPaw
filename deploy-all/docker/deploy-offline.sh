#!/usr/bin/env bash
# =========================================================
# QwenPaw 离线一键部署脚本 (docker load + 容器重建)
# =========================================================
# 用法：把本脚本和镜像 tar 放在同一目录，在离线服务器上执行：
#
#   ./deploy-offline.sh              # load 两个镜像 + 重建两个容器
#   ./deploy-offline.sh --skip-load  # 镜像已 load 过，只重建容器
#
# 所有参数都可用环境变量覆盖，默认值与 deploy-all/docker/README.md
# 的 docker run 方案保持一致（容器名 qwenpaw 不要改，Portal 的
# nginx 写死了 http://qwenpaw:8088）。
# =========================================================
set -euo pipefail

# --- 配置区（环境变量可覆盖） ---
QWENPAW_TAR="${QWENPAW_TAR:-qwenpaw-amd64.tar}"
PORTAL_TAR="${PORTAL_TAR:-digital-workforce-portal-amd64.tar}"
QWENPAW_IMAGE="${QWENPAW_IMAGE:-qwenpaw:latest}"
PORTAL_IMAGE="${PORTAL_IMAGE:-digital-workforce-portal:0.1.0}"
NETWORK="${NETWORK:-qwenpaw-net}"
QWENPAW_HOST_PORT="${QWENPAW_HOST_PORT:-30088}"
PORTAL_HOST_PORT="${PORTAL_HOST_PORT:-30083}"
DATA_ROOT="${DATA_ROOT:-/data/qwenpaw}"
PORTAL_APP_TITLE="${PORTAL_APP_TITLE:-数字员工门户}"
TZ_VALUE="${TZ_VALUE:-Asia/Shanghai}"

cd "$(dirname "$0")"

# --- 1. 加载镜像 ---
if [[ "${1:-}" != "--skip-load" ]]; then
  for tar in "$QWENPAW_TAR" "$PORTAL_TAR"; do
    if [[ -f "$tar" ]]; then
      echo "📦 docker load -i $tar"
      docker load -i "$tar"
    else
      echo "⚠️  未找到 $tar，跳过（如镜像已在本机可忽略）"
    fi
  done
fi

# --- 2. 持久化目录 + 网络 ---
mkdir -p "$DATA_ROOT/working" "$DATA_ROOT/working.secret"
docker network inspect "$NETWORK" >/dev/null 2>&1 \
  || docker network create "$NETWORK"

# --- 3. 重建后端容器（load 只导入镜像，必须重建容器才生效） ---
echo "🔄 重建容器 qwenpaw ..."
docker stop qwenpaw >/dev/null 2>&1 || true
docker rm   qwenpaw >/dev/null 2>&1 || true
docker run -d \
  --name qwenpaw \
  --restart unless-stopped \
  --network "$NETWORK" \
  -p "$QWENPAW_HOST_PORT:8088" \
  -e TZ="$TZ_VALUE" \
  -e QWENPAW_PORT=8088 \
  -e QWENPAW_DISABLED_CHANNELS=imessage \
  -v "$DATA_ROOT/working:/app/working" \
  -v "$DATA_ROOT/working.secret:/app/working.secret" \
  "$QWENPAW_IMAGE"

# --- 4. 重建前端容器 ---
echo "🔄 重建容器 portal ..."
docker stop portal >/dev/null 2>&1 || true
docker rm   portal >/dev/null 2>&1 || true
docker run -d \
  --name portal \
  --restart unless-stopped \
  --network "$NETWORK" \
  -p "$PORTAL_HOST_PORT:80" \
  -e TZ="$TZ_VALUE" \
  -e PORTAL_APP_TITLE="$PORTAL_APP_TITLE" \
  "$PORTAL_IMAGE"

# --- 5. 验证 ---
echo ""
echo "⏳ 等待后端就绪 ..."
for _ in $(seq 1 30); do
  if curl -fsS "http://127.0.0.1:$QWENPAW_HOST_PORT/" >/dev/null 2>&1; then
    break
  fi
  sleep 2
done
docker ps --filter name=qwenpaw --filter name=portal \
  --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'
echo ""
echo "✅ 部署完成："
echo "   后端  http://<本机IP>:$QWENPAW_HOST_PORT"
echo "   门户  http://<本机IP>:$PORTAL_HOST_PORT"
echo ""
echo "💡 提醒：挂载卷 $DATA_ROOT/working 里的旧技能代码不会被镜像自动"
echo "   覆盖（仅空卷会从镜像初始化）。升级技能请按 SYNC_GUIDE 同步卷内"
echo "   文件，或备份后清空卷让其重新初始化。"
