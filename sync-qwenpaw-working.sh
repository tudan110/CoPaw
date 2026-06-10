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

# 按条目合并 workspaces/*/skill.json（技能注册表）：
#   - 源里登记的技能条目（含 enabled 启用状态）以源为准写入目标
#   - 目标端运行时自装的技能条目（源里没有的）一律保留
#   - 目标缺失该文件时整份 seed
# 写入时复用应用同款的 .skill.json.lock 文件锁 + 临时文件原子替换 +
# version 递增（max(version+1, 当前毫秒时间戳)），运行中的应用可安全感知。
merge_workspace_skill_manifests() {
    local source_dir="$1"
    local target_dir="$2"
    local quiet_flag="$3"
    local workspaces_dir="$source_dir/workspaces"
    local src_manifest=""
    local ws_name=""

    [ -d "$workspaces_dir" ] || return 0

    if ! command -v python3 >/dev/null 2>&1; then
        error "未找到 python3，无法合并 workspaces/*/skill.json（技能启用状态未同步）"
        return 1
    fi

    for src_manifest in "$workspaces_dir"/*/skill.json; do
        [ -f "$src_manifest" ] || continue
        ws_name="$(basename "$(dirname "$src_manifest")")"
        SYNC_QUIET="$quiet_flag" python3 - "$src_manifest" \
            "$target_dir/workspaces/$ws_name/skill.json" "$ws_name" <<'PYEOF'
import contextlib
import json
import os
import sys
import tempfile
import time
from pathlib import Path

src_path, dst_path = Path(sys.argv[1]), Path(sys.argv[2])
ws = sys.argv[3]
quiet = os.environ.get("SYNC_QUIET") == "true"


def info(msg):
    print(f"[sync-working] {msg}")


src = json.loads(src_path.read_text(encoding="utf-8"))
src_skills = src.get("skills", {}) or {}

# 源里有技能目录但没在源 skill.json 登记的，提醒维护者补登记，
# 否则目标端只能按"新发现技能"默认禁用入库。
src_skills_dir = src_path.parent / "skills"
if src_skills_dir.is_dir():
    for p in sorted(src_skills_dir.iterdir()):
        if (
            p.is_dir()
            and (p / "SKILL.md").exists()
            and p.name not in src_skills
        ):
            info(
                f"警告: {ws}/skills/{p.name} 未在源 skill.json 登记，"
                "同步后目标端将默认禁用；请先在源端登记（含 enabled 状态）"
            )


def write_atomic(path, payload):
    payload = dict(payload)
    payload["version"] = max(
        int(payload.get("version", 0)) + 1,
        int(time.time() * 1000),
    )
    fd, tmp = tempfile.mkstemp(
        dir=str(path.parent), prefix=f".{path.stem}_", suffix=path.suffix
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, indent=2, ensure_ascii=False))
        os.replace(tmp, path)
        tmp = None
    finally:
        if tmp and os.path.exists(tmp):
            os.unlink(tmp)


@contextlib.contextmanager
def manifest_lock(path):
    lock_path = path.with_name(f".{path.name}.lock")
    with open(lock_path, "a+", encoding="utf-8") as lf:
        try:
            import fcntl

            fcntl.flock(lf.fileno(), fcntl.LOCK_EX)
        except ImportError:  # 非 POSIX 平台退化为无锁
            fcntl = None
        try:
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(lf.fileno(), fcntl.LOCK_UN)


dst_path.parent.mkdir(parents=True, exist_ok=True)
with manifest_lock(dst_path):
    if not dst_path.exists():
        write_atomic(dst_path, src)
        info(f"{ws}/skill.json 目标缺失，整份 seed（{len(src_skills)} 个技能条目）")
        sys.exit(0)

    try:
        dst = json.loads(dst_path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        dst = {}
    if not isinstance(dst, dict):
        dst = {}
    dst.setdefault(
        "schema_version",
        src.get("schema_version", "workspace-skill-manifest.v1"),
    )
    dst_skills = dst.setdefault("skills", {})
    if not isinstance(dst_skills, dict):
        dst_skills = dst["skills"] = {}

    added, updated = [], []
    for name, entry in src_skills.items():
        if name not in dst_skills:
            added.append(name)
        elif dst_skills[name] != entry:
            updated.append(name)
        else:
            continue
        dst_skills[name] = entry

    kept = [n for n in dst_skills if n not in src_skills]
    if added or updated:
        write_atomic(dst_path, dst)
        info(
            f"{ws}/skill.json 合并: 新增 {len(added)}、更新 {len(updated)}、"
            f"保留目标自有 {len(kept)}"
        )
        if not quiet:
            for n in added:
                info(f"  + {ws}/{n} (enabled={dst_skills[n].get('enabled')})")
            for n in updated:
                info(f"  ~ {ws}/{n} (enabled={dst_skills[n].get('enabled')})")
    elif not quiet:
        info(f"{ws}/skill.json 无变化（保留目标自有 {len(kept)}）")
PYEOF
    done
}

usage() {
    cat <<'EOF'
用法:
  ./sync-qwenpaw-working.sh [--delete] [target_dir]

说明:
   将 deploy-all/qwenpaw/working/ 下的文件同步到本地工作目录。
   默认目标目录为 ~/.qwenpaw/，也可通过 QWENPAW_WORKING_DIR 环境变量覆盖。

同步规则:
  - 源里有、目标里没有的文件: 直接拷贝过去
  - 两边都有的文件: 以源为准，按内容（checksum）比较后覆盖更新
  - 目标里有、源里没有的文件: 默认保留，加 --delete 才会清理
  - workspaces/*/skill.json（技能注册表）: 按条目合并——源里登记的技能条目
    （含 enabled 启用状态）以源为准写入目标，目标端运行时自装的技能条目保留；
    目标缺失该文件时整份 seed。也就是说出厂技能同步过去后就是启用的，
    无需再进 portal 手动启用。
  - 例外保护: workspaces/*/agent.json（含渠道 token / 自定义 description）
    只在目标缺失时 seed，已存在的不覆盖，避免把渠道凭据回滚到出厂态。

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

# workspaces/<agent>/agent.json 可能含 channel token / 自定义 description，
# 只在目标缺失时 seed 一遍当作 bootstrap，已经存在的一律保留 ——
# 避免重新跑 sync 时把配好的渠道凭据回滚到出厂态。
PROTECTED_INCLUDES=(
    --include='*/'
    --include='workspaces/*/agent.json'
    --exclude='*'
)
info "保护文件: workspaces/*/agent.json（仅当目标缺失时 seed，已存在的保留）"
rsync -a --ignore-existing "${PROTECTED_INCLUDES[@]}" "$SOURCE_DIR/" "$TARGET_DIR/"

# skill.json 不走 rsync，由下面的 merge_workspace_skill_manifests 按条目合并
rsync "${RSYNC_ARGS[@]}" \
    --exclude='workspaces/*/skill.json' \
    --exclude='workspaces/*/agent.json' \
    "$SOURCE_DIR/" "$TARGET_DIR/"
merge_workspace_skill_manifests "$SOURCE_DIR" "$TARGET_DIR" "$QUIET_MODE"

info "同步完成"
