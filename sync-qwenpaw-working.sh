#!/bin/bash

# 兼容 sh 调用：若非 bash 则自动切换到 bash 执行
if [ -z "${BASH_VERSION:-}" ]; then
    exec bash "$0" "$@"
fi

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SOURCE_DIR="$SCRIPT_DIR/deploy-all/qwenpaw/working"
DEFAULT_ACTIVE_PROVIDER="${QWENPAW_DEFAULT_ACTIVE_PROVIDER:-ctyun}"
DEFAULT_ACTIVE_MODEL="${QWENPAW_DEFAULT_ACTIVE_MODEL:-GLM-5.1}"

info() {
    printf '[sync-working] %s\n' "$*"
}

error() {
    printf '[sync-working] %s\n' "$*" >&2
}

usage() {
    cat <<'EOF'
用法:
  ./sync-qwenpaw-working.sh [--delete] [target_dir]

说明:
  将 deploy-all/qwenpaw/working/ 下的文件同步到本地工作目录。
  默认目标目录为 ~/.qwenpaw/，也可通过 QWENPAW_WORKING_DIR 环境变量覆盖。
  若未配置 active 模型，会默认写入 QWENPAW_SECRET_DIR/providers/active_model.json。
  默认 active 模型为 ctyun / GLM-5.1，可通过 QWENPAW_DEFAULT_ACTIVE_PROVIDER
  和 QWENPAW_DEFAULT_ACTIVE_MODEL 覆盖。

参数:
  --delete     删除目标目录中源目录不存在的文件，执行严格镜像
  -h, --help   显示帮助

示例:
  ./sync-qwenpaw-working.sh
  ./sync-qwenpaw-working.sh --delete
  ./sync-qwenpaw-working.sh /tmp/qwenpaw-working
EOF
}

resolve_target_dir() {
    if [ $# -gt 0 ] && [ -n "$1" ]; then
        printf '%s\n' "$1"
        return
    fi
    if [ -n "${QWENPAW_WORKING_DIR:-}" ]; then
        printf '%s\n' "$QWENPAW_WORKING_DIR"
        return
    fi
    printf '%s\n' "$HOME/.qwenpaw"
}

resolve_secret_dir() {
    if [ -n "${QWENPAW_SECRET_DIR:-}" ]; then
        printf '%s\n' "$QWENPAW_SECRET_DIR"
        return
    fi
    printf '%s.secret\n' "$TARGET_DIR"
}

seed_default_active_model() {
    local secret_dir="$1"
    local providers_dir="$secret_dir/providers"
    local active_path="$providers_dir/active_model.json"

    if [ -f "$active_path" ]; then
        info "active 模型已存在，保留当前配置: $active_path"
        return
    fi

    mkdir -p "$providers_dir"
    cat >"$active_path" <<EOF
{
  "provider_id": "${DEFAULT_ACTIVE_PROVIDER}",
  "model": "${DEFAULT_ACTIVE_MODEL}"
}
EOF
    chmod 600 "$active_path" 2>/dev/null || true

    if [ ! -f "$providers_dir/builtin/${DEFAULT_ACTIVE_PROVIDER}.json" ] \
        && [ ! -f "$providers_dir/custom/${DEFAULT_ACTIVE_PROVIDER}.json" ] \
        && [ ! -f "$providers_dir/plugin/${DEFAULT_ACTIVE_PROVIDER}.json" ]; then
        info "提示: 未在 $providers_dir 下找到 provider 配置 ${DEFAULT_ACTIVE_PROVIDER}，启动前请确认对应 provider/api key 已存在"
    fi
    info "已默认 active 模型: ${DEFAULT_ACTIVE_PROVIDER} / ${DEFAULT_ACTIVE_MODEL}"
}

DELETE_MODE=false
TARGET_ARG=""

while [ $# -gt 0 ]; do
    case "$1" in
        --delete)
            DELETE_MODE=true
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        -*)
            error "未知参数: $1"
            usage
            exit 1
            ;;
        *)
            if [ -n "$TARGET_ARG" ]; then
                error "只能指定一个目标目录"
                usage
                exit 1
            fi
            TARGET_ARG="$1"
            shift
            ;;
    esac
done

TARGET_DIR="$(resolve_target_dir "$TARGET_ARG")"
SECRET_DIR="$(resolve_secret_dir)"

if [ ! -d "$SOURCE_DIR" ]; then
    error "源目录不存在: $SOURCE_DIR"
    exit 1
fi

if ! command -v rsync >/dev/null 2>&1; then
    error "未找到 rsync，请先安装 rsync"
    exit 1
fi

mkdir -p "$TARGET_DIR"

RSYNC_ARGS=(-a)
if [ "$DELETE_MODE" = true ]; then
    RSYNC_ARGS+=(--delete)
fi

info "源目录: $SOURCE_DIR/"
info "目标目录: $TARGET_DIR/"
info "密钥目录: $SECRET_DIR/"
if [ "$DELETE_MODE" = true ]; then
    info "同步模式: 严格镜像（会删除目标目录中的多余文件）"
else
    info "同步模式: 覆盖同名文件，保留目标目录中的额外文件"
fi

rsync "${RSYNC_ARGS[@]}" "$SOURCE_DIR/" "$TARGET_DIR/"
seed_default_active_model "$SECRET_DIR"

info "同步完成"
