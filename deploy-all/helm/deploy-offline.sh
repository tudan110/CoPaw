#!/usr/bin/env bash
# =========================================================
# QwenPaw k3s/k8s 离线一键部署（镜像导入 + helm 升级 + 自动更新 Pod）
# =========================================================
# 用法：把本脚本、两个镜像 tar、chart 包（目录或 .tgz）放在离线
# 服务器同一目录，执行：
#
#   ./deploy-offline.sh                 # 导入镜像 + helm upgrade + 自动更新 Pod
#   ./deploy-offline.sh --skip-import   # 镜像已导入过，只升级并自动更新 Pod
#
# 镜像导入方式自动探测：k3s ctr > ctr(k8s.io) > docker load。
# k3s 用 containerd 而不是 docker，`docker load` 对 k3s 不生效 ——
# 这是离线升级"明明 load 了还是旧镜像"的最常见原因。
#
# 所有参数可用环境变量覆盖：
#   NAMESPACE=cnos-iomp RELEASE=cnos-inoe-agent ./deploy-offline.sh
#   EXTRA_VALUES=my-values.yaml ./deploy-offline.sh
# =========================================================
set -euo pipefail

QWENPAW_TAR="${QWENPAW_TAR:-qwenpaw-amd64.tar}"
PORTAL_TAR="${PORTAL_TAR:-digital-workforce-portal-amd64.tar}"
RELEASE="${RELEASE:-cnos-inoe-agent}"
NAMESPACE="${NAMESPACE:-cnos-iomp}"
EXTRA_VALUES="${EXTRA_VALUES:-}"
HELM_TIMEOUT="${HELM_TIMEOUT:-10m}"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# --- chart 位置：优先同目录 .tgz，其次仓库内 chart 目录 ---
if [[ -z "${CHART:-}" ]]; then
  CHART="$(ls -1 cnos-inoe-agent-*.tgz 2>/dev/null | sort -V | tail -1 || true)"
  [[ -z "$CHART" && -d "$SCRIPT_DIR/cnos-inoe-agent" ]] \
    && CHART="$SCRIPT_DIR/cnos-inoe-agent"
fi
if [[ -z "$CHART" ]]; then
  echo "❌ 未找到 chart（cnos-inoe-agent-*.tgz 或 cnos-inoe-agent/ 目录）。"
  echo "   可用 CHART=/path/to/chart 指定。"
  exit 1
fi

# --- 1. 导入镜像（自动探测容器运行时） ---
import_image() {
  local tar="$1"
  if [[ ! -f "$tar" ]]; then
    echo "❌ 未找到 $tar，无法按固定 tag 部署。"
    return 1
  fi
  if command -v k3s >/dev/null 2>&1; then
    echo "📦 k3s ctr images import $tar"
    k3s ctr images import "$tar"
  elif command -v ctr >/dev/null 2>&1; then
    echo "📦 ctr -n k8s.io images import $tar"
    ctr -n k8s.io images import "$tar"
  elif command -v docker >/dev/null 2>&1; then
    echo "📦 docker load -i $tar （注意：仅 docker 运行时的 k8s 有效）"
    docker load -i "$tar"
  else
    echo "❌ 未找到 k3s/ctr/docker，无法导入镜像"
    exit 1
  fi
}

if [[ "${1:-}" != "--skip-import" ]]; then
  import_image "$QWENPAW_TAR"
  import_image "$PORTAL_TAR"
  echo "💡 多节点集群注意：镜像须在每个可能调度到的节点上导入，"
  echo "   或改用内网镜像仓库。"
fi

# --- 2. helm upgrade --install ---
HELM_ARGS=(upgrade --install "$RELEASE" "$CHART"
  --namespace "$NAMESPACE" --create-namespace --wait --timeout "$HELM_TIMEOUT")
[[ -n "$EXTRA_VALUES" ]] && HELM_ARGS+=(-f "$EXTRA_VALUES")
echo "⛵ helm ${HELM_ARGS[*]}"
helm "${HELM_ARGS[@]}"

# --- 3. 等待 Pod 更新完成 ---
kubectl -n "$NAMESPACE" rollout status deployment/qwenpaw --timeout=300s
kubectl -n "$NAMESPACE" rollout status deployment/cnos-iomp-digital-workforce-portal --timeout=120s

NODE_IP="$(kubectl get nodes -o jsonpath='{.items[0].status.addresses[?(@.type=="InternalIP")].address}' 2>/dev/null || echo '<节点IP>')"
echo ""
echo "✅ 部署完成："
echo "   后端  http://$NODE_IP:30088"
echo "   门户  http://$NODE_IP:30083"
echo ""
echo "💡 受管 Agent/Skill 会由新 Pod 的 managed-seed-sync initContainer 从"
echo "   /app/share/qwenpaw-seed 安全同步到 PVC；不会触碰 jobs、secret、"
echo "   knowledge-base data、sessions、设置数据库或用户自装 Skill。"
echo "   可在 Pod 中执行 python3 /usr/local/bin/sync_managed_seed.py --seed /app/share/qwenpaw-seed --target /app/working 查看报告。"
