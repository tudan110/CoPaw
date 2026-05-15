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

sync_workspace_skills_to_pool() {
    local source_dir="$1"
    local target_dir="$2"
    local quiet_flag="$3"
    local pool_dir="$target_dir/skill_pool"
    local workspaces_dir="$source_dir/workspaces"
    local seen_file=""
    local synced_count=0
    local skipped_count=0
    local workspace_dir=""
    local skills_dir=""
    local skill_dir=""
    local skill_name=""
    local target_skill_dir=""
    local ordered_workspaces=()

    mkdir -p "$pool_dir"
    if [ ! -d "$workspaces_dir" ]; then
        return
    fi

    seen_file="$(mktemp)"
    trap 'rm -f "$seen_file"' RETURN

    if [ -d "$workspaces_dir/gateway" ]; then
        ordered_workspaces+=("$workspaces_dir/gateway")
    fi
    for workspace_dir in "$workspaces_dir"/*; do
        [ -d "$workspace_dir" ] || continue
        [ "$workspace_dir" = "$workspaces_dir/gateway" ] && continue
        ordered_workspaces+=("$workspace_dir")
    done

    for workspace_dir in "${ordered_workspaces[@]}"; do
        skills_dir="$workspace_dir/skills"
        [ -d "$skills_dir" ] || continue

        for skill_dir in "$skills_dir"/*; do
            [ -d "$skill_dir" ] || continue
            [ -f "$skill_dir/SKILL.md" ] || continue

            skill_name="$(basename "$skill_dir")"
            if grep -Fqx "$skill_name" "$seen_file"; then
                skipped_count=$((skipped_count + 1))
                if [ "$quiet_flag" != true ]; then
                    info "  skip $(basename "$workspace_dir")/$skill_name"
                fi
                continue
            fi

            printf '%s\n' "$skill_name" >>"$seen_file"
            target_skill_dir="$pool_dir/$skill_name"
            mkdir -p "$target_skill_dir"
            rsync -a --delete \
                --exclude "__pycache__" \
                --exclude "__MACOSX" \
                --exclude ".DS_Store" \
                --exclude "Thumbs.db" \
                --exclude "desktop.ini" \
                "$skill_dir/" "$target_skill_dir/"
            synced_count=$((synced_count + 1))
            if [ "$quiet_flag" != true ]; then
                info "  pool $skill_name <- $(basename "$workspace_dir")"
            fi
        done
    done

    rm -f "$seen_file"
    trap - RETURN

    if [ "$synced_count" -gt 0 ] || [ "$skipped_count" -gt 0 ]; then
        info "技能池已同步: ${synced_count} 个自定义技能，跳过 ${skipped_count} 个同名技能"
    fi
}

usage() {
    cat <<'EOF'
用法:
  ./sync-qwenpaw-working.sh [--delete] [target_dir]

说明:
   将 deploy-all/qwenpaw/working/ 下的文件同步到本地工作目录。
   同时会把各 workspace 里维护的自定义 skill 复制到目标 skill_pool。
   默认目标目录为 ~/.qwenpaw/，也可通过 QWENPAW_WORKING_DIR 环境变量覆盖。

同步规则:
  - 源里有、目标里没有的文件: 直接拷贝过去
  - 两边都有的文件: 以源为准，按内容（checksum）比较后覆盖更新
  - 目标里有、源里没有的文件: 默认保留，加 --delete 才会清理
  - 同步到 skill_pool 时，gateway 工作区优先；同名 skill 只保留一份，后续重复项直接跳过
  - 例外保护: workspaces/*/skill.json（二开技能注册表）和 workspaces/*/agent.json
    （含渠道 token / 自定义 description）只在目标缺失时 seed，已存在的不覆盖，
    避免把二开技能 / 渠道凭据回滚到出厂态。新装的出厂技能仍会被主 rsync 把
    目录拷过来，进 portal 点「刷新技能」即可重新入库。

参数:
  --delete     删除目标目录中源目录不存在的文件，执行严格镜像
  --quiet, -q  只打印汇总，不输出每个被改动文件的明细
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
QUIET_MODE=false
TARGET_ARG=""

while [ $# -gt 0 ]; do
    case "$1" in
        --delete)
            DELETE_MODE=true
            shift
            ;;
        --quiet|-q)
            QUIET_MODE=true
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

# -a：保留属性 / 递归 / 软链
# -c：按内容 checksum 比较，避免 mtime 错位时漏掉已被修改的文件
# 不带 -u：源端永远赢，目标端如果被手工改过也会被覆盖（这是有意的）
RSYNC_ARGS=(-a -c)
if [ "$QUIET_MODE" != true ]; then
    # 列出每个被新增 / 更新 / 删除的文件，便于排查"为什么没更新"
    RSYNC_ARGS+=(-i)
fi
if [ "$DELETE_MODE" = true ]; then
    RSYNC_ARGS+=(--delete)
fi

info "源目录: $SOURCE_DIR/"
info "目标目录: $TARGET_DIR/"
info "比较方式: checksum（内容比对，与 mtime 无关）"
if [ "$DELETE_MODE" = true ]; then
    info "同步模式: 严格镜像（会删除目标目录中的多余文件）"
else
    info "同步模式: 以源为准覆盖更新，目标目录中源没有的文件保留"
fi

# 「运行时注册表」类文件：workspaces/<agent>/skill.json 记录二开技能注册；
# workspaces/<agent>/agent.json 可能含 channel token / 自定义 description。
# 这两类只在目标缺失时 seed 一遍当作 bootstrap，已经存在的一律保留 ——
# 避免重新跑 sync 时把用户已经装好的二开技能 / 配好的渠道凭据回滚到出厂态。
# 新装的出厂技能仍会经过主 rsync 把目录拷过来，进 portal 点「刷新」即可入库。
PROTECTED_INCLUDES=(
    --include='*/'
    --include='workspaces/*/skill.json'
    --include='workspaces/*/agent.json'
    --exclude='*'
)
info "保护文件: workspaces/*/skill.json + workspaces/*/agent.json（仅当目标缺失时 seed，已存在的保留）"
rsync -a --ignore-existing "${PROTECTED_INCLUDES[@]}" "$SOURCE_DIR/" "$TARGET_DIR/"

rsync "${RSYNC_ARGS[@]}" \
    --exclude='workspaces/*/skill.json' \
    --exclude='workspaces/*/agent.json' \
    "$SOURCE_DIR/" "$TARGET_DIR/"
sync_workspace_skills_to_pool "$SOURCE_DIR" "$TARGET_DIR" "$QUIET_MODE"

info "同步完成"
