#!/bin/bash

# 兼容 sh 调用：若非 bash 则自动切换到 bash 执行
if [ -z "${BASH_VERSION:-}" ]; then
    exec bash "$0" "$@"
fi

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SOURCE_DIR="$SCRIPT_DIR/deploy-all/qwenpaw/working"

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
if [ "$DELETE_MODE" = true ]; then
    info "同步模式: 严格镜像（会删除目标目录中的多余文件）"
else
    info "同步模式: 覆盖同名文件，保留目标目录中的额外文件"
fi

rsync "${RSYNC_ARGS[@]}" "$SOURCE_DIR/" "$TARGET_DIR/"

info "同步完成"
