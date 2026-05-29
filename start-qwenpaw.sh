#!/bin/sh
# QwenPaw 项目启动脚本 (使用 uv)

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

TMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/qwenpaw-start.XXXXXX")"
cleanup() {
    if [ -n "${TMP_DIR:-}" ] && [ -d "$TMP_DIR" ]; then
        rm -rf "$TMP_DIR"
    fi
}
trap cleanup EXIT HUP INT TERM

APP_ARGS_FILE="$TMP_DIR/app-args.txt"
SKILL_REQS_FILE="$TMP_DIR/skill-reqs.txt"
: > "$APP_ARGS_FILE"
: > "$SKILL_REQS_FILE"

resolve_working_dir() {
    if [ -n "${QWENPAW_WORKING_DIR:-}" ]; then
        printf '%s\n' "$QWENPAW_WORKING_DIR"
        return
    fi
    printf '%s\n' "$HOME/.qwenpaw"
}

WORKING_DIR="$(resolve_working_dir)"
export QWENPAW_WORKING_DIR="$WORKING_DIR"

# Knowledge-base retrieval defaults. Set in env before launch to override.
export KNOWLEDGE_BASE_RERANKER="${KNOWLEDGE_BASE_RERANKER:-llm}"
export KNOWLEDGE_BASE_HYDE_ENABLED="${KNOWLEDGE_BASE_HYDE_ENABLED:-true}"

# NB: the security posture (skill_scanner mode, domain_guard, delete_ops_disabled,
# tool_guard auto_denied_rules) lives in config.json -> "security" (it travels
# with WORKING_DIR, so it survives any deployment method). The QWENPAW_*_MODE /
# QWENPAW_DELETE_OPS_DISABLED env vars are only emergency overrides — don't pin
# them here.
VENV_DIR=".venv"
PYTHON_BIN="$SCRIPT_DIR/$VENV_DIR/bin/python"
UV_LOCAL_BIN="$HOME/.local/bin/uv"
DEPS_STAMP_FILE="$SCRIPT_DIR/$VENV_DIR/.qwenpaw-deps-stamp"

REBUILD_FRONTEND=false
while [ "$#" -gt 0 ]; do
    if [ "$1" = "--rebuild" ]; then
        REBUILD_FRONTEND=true
    else
        printf '%s\n' "$1" >> "$APP_ARGS_FILE"
    fi
    shift
done

echo "=========================================="
echo "  QwenPaw 启动脚本"
echo "=========================================="

# 优先补齐 uv 默认安装目录，避免 PATH 未加载时重复安装
export PATH="$HOME/.local/bin:$PATH"

# 检查并安装 uv
if command -v uv > /dev/null 2>&1; then
    UV_BIN="$(command -v uv)"
    echo "[1/5] uv 已安装"
elif [ -x "$UV_LOCAL_BIN" ]; then
    UV_BIN="$UV_LOCAL_BIN"
    echo "[1/5] uv 已安装"
else
    echo "[1/5] 安装 uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
    UV_BIN="$UV_LOCAL_BIN"
fi

UV_VERSION=$("$UV_BIN" --version 2>&1)
echo "      $UV_VERSION"

# 创建虚拟环境（如果不存在）
if [ ! -d "$VENV_DIR" ] || [ ! -x "$PYTHON_BIN" ]; then
    echo "[2/5] 创建虚拟环境..."
    "$UV_BIN" venv "$VENV_DIR"
else
    echo "[2/5] 虚拟环境已存在，跳过创建"
fi

# 发现所有 skill 自带的 requirements.txt（未来新加 skill 带 deps 也会自动生效）
SKILL_WORKSPACES_DIR="$SCRIPT_DIR/deploy-all/qwenpaw/working/workspaces"
if [ -d "$SKILL_WORKSPACES_DIR" ]; then
    find "$SKILL_WORKSPACES_DIR" -path '*/skills/*/requirements.txt' 2>/dev/null | sort > "$SKILL_REQS_FILE"
fi

compute_deps_stamp() {
    deps_input_file="$TMP_DIR/deps-files.txt"
    : > "$deps_input_file"

    for file in pyproject.toml setup.py uv.lock; do
        if [ -f "$SCRIPT_DIR/$file" ]; then
            printf '%s\n' "$SCRIPT_DIR/$file" >> "$deps_input_file"
        fi
    done
    if [ -s "$SKILL_REQS_FILE" ]; then
        cat "$SKILL_REQS_FILE" >> "$deps_input_file"
    fi

    if [ ! -s "$deps_input_file" ]; then
        printf 'no-deps-files\n'
        return
    fi

    while IFS= read -r file; do
        [ -n "$file" ] || continue
        shasum "$file"
    done < "$deps_input_file" | shasum | awk '{print $1}'
}

# 安装依赖（不包含 mlx，仅支持 Apple Silicon arm64）
CURRENT_DEPS_STAMP="$(compute_deps_stamp)"
INSTALLED_DEPS_STAMP=""
if [ -f "$DEPS_STAMP_FILE" ]; then
    INSTALLED_DEPS_STAMP="$(cat "$DEPS_STAMP_FILE")"
fi

if [ "$CURRENT_DEPS_STAMP" != "$INSTALLED_DEPS_STAMP" ]; then
    echo "[3/5] 安装依赖..."
    UV_HTTP_TIMEOUT=300 "$UV_BIN" pip install --python "$PYTHON_BIN" -e ".[dev]"
    if [ -s "$SKILL_REQS_FILE" ]; then
        while IFS= read -r req; do
            [ -n "$req" ] || continue
            echo "      → skill deps: ${req#$SCRIPT_DIR/}"
            UV_HTTP_TIMEOUT=300 "$UV_BIN" pip install --python "$PYTHON_BIN" -r "$req"
        done < "$SKILL_REQS_FILE"
    fi
    printf '%s\n' "$CURRENT_DEPS_STAMP" > "$DEPS_STAMP_FILE"
else
    echo "[3/5] 依赖未变化，跳过安装"
fi

# 同步 deploy-all/qwenpaw/working/workspaces/<agent>/skills/ 到对应运行时目录
# 仅同步 skills/ 这一层 —— 这是 repo 里会变更的代码。其他文件（agent.json、
# skill.json、HEARTBEAT.md、jobs.json 等）都是 runtime 状态/配置，由前端 UI
# 写入；同步进去会覆盖钉钉/邮件等通道的实际配置。
WORKSPACES_SRC="$SCRIPT_DIR/deploy-all/qwenpaw/working/workspaces"
WORKSPACES_DST="$WORKING_DIR/workspaces"
if [ -d "$WORKSPACES_SRC" ] && command -v rsync >/dev/null 2>&1; then
    echo "[3.5/5] 同步 skills 代码到 $WORKSPACES_DST ..."
    synced_count=0
    for src_skills_dir in "$WORKSPACES_SRC"/*/skills; do
        [ -d "$src_skills_dir" ] || continue
        agent_name=$(basename "$(dirname "$src_skills_dir")")
        dst_skills_dir="$WORKSPACES_DST/$agent_name/skills"
        mkdir -p "$dst_skills_dir"
        rsync -a "$src_skills_dir/" "$dst_skills_dir/"
        synced_count=$((synced_count + 1))
    done
    echo "      synced skills/ for $synced_count agent(s)"
else
    echo "[3.5/5] 跳过 skills 同步（缺少 $WORKSPACES_SRC 或 rsync）"
fi

# 构建前端（如果需要）
CONSOLE_DIST="$SCRIPT_DIR/console/dist"
CONSOLE_PACKAGE_DIR="$SCRIPT_DIR/src/qwenpaw/console"
NEED_BUILD=false

sync_console_assets() {
    src_dir="$1"
    dest_dir="$2"

    if [ ! -d "$src_dir" ] || [ ! -f "$src_dir/index.html" ]; then
        echo "[4.5/5] 跳过前端产物同步（未找到 $src_dir/index.html）"
        return
    fi

    echo "[4.5/5] 同步前端产物到 $dest_dir ..."
    mkdir -p "$dest_dir"

    if command -v rsync >/dev/null 2>&1; then
        rsync -a --delete "$src_dir/" "$dest_dir/"
    else
        rm -rf "$dest_dir"
        mkdir -p "$dest_dir"
        cp -R "$src_dir/." "$dest_dir/"
    fi
}

if [ "$REBUILD_FRONTEND" = true ]; then
    NEED_BUILD=true
    rm -rf "$CONSOLE_DIST"
    echo "[4/5] 强制重新构建前端..."
elif [ ! -d "$CONSOLE_DIST" ] || [ ! -f "$CONSOLE_DIST/index.html" ]; then
    NEED_BUILD=true
    echo "[4/5] 构建前端..."
else
    echo "[4/5] 前端已构建，跳过（使用 --rebuild 强制重新构建）"
fi

if [ "$NEED_BUILD" = true ]; then
    if command -v pnpm > /dev/null 2>&1; then
        echo "      使用 pnpm 加速构建..."
        cd "$SCRIPT_DIR/console"
        pnpm install --frozen-lockfile=false
        pnpm run build
        cd "$SCRIPT_DIR"
    elif command -v npm > /dev/null 2>&1; then
        cd "$SCRIPT_DIR/console"
        npm ci --quiet
        npm run build
        cd "$SCRIPT_DIR"
    else
        echo "警告: 未找到 npm 或 pnpm，跳过前端构建"
        echo "如需前端界面，请手动安装 Node.js 并运行: cd console && npm ci && npm run build"
    fi
fi

sync_console_assets "$CONSOLE_DIST" "$CONSOLE_PACKAGE_DIR"

# 禁用匿名遥测数据收集
TELEMETRY_MARKER="$WORKING_DIR/.telemetry_collected"
if [ ! -f "$TELEMETRY_MARKER" ]; then
    echo '{"opted_out": true}' > "$TELEMETRY_MARKER"
fi

# 初始化配置（如果需要）
CONFIG_FILE="$WORKING_DIR/config.json"
if [ ! -f "$CONFIG_FILE" ]; then
    echo "[5/5] 初始化配置..."
    "$PYTHON_BIN" -m qwenpaw init --defaults --accept-security
else
    echo "[5/5] 配置已存在，跳过初始化"
fi

echo ""
echo "=========================================="
echo "  启动 QwenPaw..."
echo "=========================================="
echo ""

# 同步故障处置 builtin skill 到 fault 工作区，避免工作区副本滞后
FAULT_WORKSPACE_SKILL_DIR="$WORKING_DIR/workspaces/fault/skills/fault-disposal"
FAULT_SOURCE_SKILL_DIR="$SCRIPT_DIR/src/qwenpaw/agents/skills/fault-disposal"
if [ -d "$FAULT_SOURCE_SKILL_DIR" ] && [ -d "$(dirname "$FAULT_WORKSPACE_SKILL_DIR")" ]; then
    echo "[sync] 同步 fault-disposal skill 到工作区..."
    mkdir -p "$FAULT_WORKSPACE_SKILL_DIR"
    rsync -a --delete "$FAULT_SOURCE_SKILL_DIR/" "$FAULT_WORKSPACE_SKILL_DIR/"
fi

# 同步 portal 扩展路由到 QwenPaw custom_channels，避免换机器后 /api/portal/* 丢失
PORTAL_CUSTOM_CHANNEL_DIR="$WORKING_DIR/custom_channels"
PORTAL_CUSTOM_CHANNEL_FILE="$PORTAL_CUSTOM_CHANNEL_DIR/portal_api.py"
echo "[sync] 同步 portal_api custom channel..."
mkdir -p "$PORTAL_CUSTOM_CHANNEL_DIR"
cat > "$PORTAL_CUSTOM_CHANNEL_FILE" <<'PY'
from qwenpaw.extensions.api.portal_backend import register_app_routes


__all__ = ["register_app_routes"]
PY

# 启动应用（默认绑定 0.0.0.0 以便局域网访问；如已显式传入 --host 则不覆盖）
HOST_OVERRIDDEN=false
if [ -s "$APP_ARGS_FILE" ]; then
    while IFS= read -r arg; do
        case "$arg" in
            --host|--host=*)
                HOST_OVERRIDDEN=true
                break
                ;;
        esac
    done < "$APP_ARGS_FILE"
fi

set --
if [ "$HOST_OVERRIDDEN" != true ]; then
    set -- --host 0.0.0.0
fi
if [ -s "$APP_ARGS_FILE" ]; then
    while IFS= read -r arg; do
        set -- "$@" "$arg"
    done < "$APP_ARGS_FILE"
fi

"$PYTHON_BIN" -m qwenpaw app "$@"
