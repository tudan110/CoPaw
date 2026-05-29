#!/bin/bash

# 同步 GitHub 代码到内部仓库的脚本
# 用法：./sync-to-internal.sh [--full] [branch_name]
#   --full    全量同步（重写所有提交历史），默认为增量同步
#   branch_name  分支名称，默认 dev

set -e

# 配置变量
SYNC_MODE="incremental"
BRANCH_NAME="dev"
GITHUB_REMOTE="origin"
INTERNAL_REMOTE="internal"
MARKER_FILE=".git/sync-internal-last-sha"

# 默认内部仓库提交者信息（未匹配到映射时使用）
DEFAULT_INTERNAL_AUTHOR_NAME="王坦"
DEFAULT_INTERNAL_AUTHOR_EMAIL="wangt091@chinatelecom.cn"

# 解析参数
while [[ $# -gt 0 ]]; do
    case "$1" in
        --full)
            SYNC_MODE="full"
            shift
            ;;
        *)
            BRANCH_NAME="$1"
            shift
            ;;
    esac
done

TEMP_BRANCH="sync-internal-$(date +%s)"

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# 打印函数
print_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

print_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# 作者映射函数：根据 GitHub 用户名返回内部姓名和邮箱
map_author() {
    local name="$1"
    case "$name" in
        "Zhuwenyong"|"Vince Zhu")
            echo "朱文勇|zhuwy09@chinatelecom.cn"
            ;;
        "mak073")
            echo "mak073|mak073@chinatelecom.cn"
            ;;
        "tudan110")
            echo "王坦|wangt091@chinatelecom.cn"
            ;;
        *)
            echo "${DEFAULT_INTERNAL_AUTHOR_NAME}|${DEFAULT_INTERNAL_AUTHOR_EMAIL}"
            ;;
    esac
}

# 检查是否在 Git 仓库中
if ! git rev-parse --git-dir > /dev/null 2>&1; then
    print_error "当前目录不是一个 Git 仓库"
    exit 1
fi

# 检查当前分支
CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)
if [ "$CURRENT_BRANCH" != "$BRANCH_NAME" ]; then
    print_warn "当前分支是 $CURRENT_BRANCH，将切换到 $BRANCH_NAME"
    git checkout "$BRANCH_NAME"
fi

# 拉取最新代码
print_info "从 $GITHUB_REMOTE 拉取最新代码..."
git fetch "$GITHUB_REMOTE"

# 检查分支是否存在
if ! git show-ref --verify --quiet "refs/remotes/$GITHUB_REMOTE/$BRANCH_NAME"; then
    print_error "分支 $GITHUB_REMOTE/$BRANCH_NAME 不存在"
    exit 1
fi

# 检查是否有未提交的更改
if ! git diff-index --quiet HEAD --; then
    print_error "当前分支有未提交的更改，请先提交或暂存"
    exit 1
fi

# 确定同步模式
LATEST_SHA=$(git rev-parse "$GITHUB_REMOTE/$BRANCH_NAME")

if [ "$SYNC_MODE" = "incremental" ]; then
    if [ -f "$MARKER_FILE" ]; then
        LAST_SYNCED_SHA=$(cat "$MARKER_FILE")
        # 验证 SHA 仍存在于历史中
        if git merge-base --is-ancestor "$LAST_SYNCED_SHA" "$LATEST_SHA" 2>/dev/null; then
            NEW_COMMITS=$(git rev-list --count "$LAST_SYNCED_SHA".."$LATEST_SHA")
            if [ "$NEW_COMMITS" -eq 0 ]; then
                print_info "没有新的提交需要同步（已是最新）"
                exit 0
            fi
            print_info "增量同步模式：发现 $NEW_COMMITS 个新提交"
        else
            print_warn "上次同步记录无效，自动切换为全量同步"
            SYNC_MODE="full"
        fi
    else
        print_warn "首次运行，无同步记录，自动切换为全量同步"
        SYNC_MODE="full"
    fi
fi

if [ "$SYNC_MODE" = "full" ]; then
    print_info "全量同步模式：重写所有提交历史..."

    # 创建临时分支
    git checkout -b "$TEMP_BRANCH" "$GITHUB_REMOTE/$BRANCH_NAME"

    git filter-branch -f --env-filter '
    case "$GIT_AUTHOR_NAME" in
        "Zhuwenyong"|"Vince Zhu")
            export GIT_AUTHOR_NAME="朱文勇"
            export GIT_AUTHOR_EMAIL="zhuwy09@chinatelecom.cn"
            export GIT_COMMITTER_NAME="朱文勇"
            export GIT_COMMITTER_EMAIL="zhuwy09@chinatelecom.cn"
            ;;
        "mak073")
            export GIT_AUTHOR_NAME="mak073"
            export GIT_AUTHOR_EMAIL="mak073@chinatelecom.cn"
            export GIT_COMMITTER_NAME="mak073"
            export GIT_COMMITTER_EMAIL="mak073@chinatelecom.cn"
            ;;
        "tudan110")
            export GIT_AUTHOR_NAME="王坦"
            export GIT_AUTHOR_EMAIL="wangt091@chinatelecom.cn"
            export GIT_COMMITTER_NAME="王坦"
            export GIT_COMMITTER_EMAIL="wangt091@chinatelecom.cn"
            ;;
        *)
            export GIT_AUTHOR_NAME="'"$DEFAULT_INTERNAL_AUTHOR_NAME"'"
            export GIT_AUTHOR_EMAIL="'"$DEFAULT_INTERNAL_AUTHOR_EMAIL"'"
            export GIT_COMMITTER_NAME="'"$DEFAULT_INTERNAL_AUTHOR_NAME"'"
            export GIT_COMMITTER_EMAIL="'"$DEFAULT_INTERNAL_AUTHOR_EMAIL"'"
            ;;
    esac
    ' HEAD

    # 推送到内部仓库
    print_info "推送到内部仓库 $INTERNAL_REMOTE/$BRANCH_NAME..."
    git push -f "$INTERNAL_REMOTE" "$TEMP_BRANCH:$BRANCH_NAME"

    # 清理
    git checkout "$BRANCH_NAME"
    git branch -D "$TEMP_BRANCH"
    git update-ref -d "refs/original/refs/heads/$TEMP_BRANCH" 2>/dev/null || true

    # 全量重写后清理悬空对象
    print_info "清理 Git 悬空对象..."
    git reflog expire --expire=now --all 2>/dev/null || true
    git gc --prune=now --quiet 2>/dev/null || true

else
    # 增量同步：只处理新提交
    print_info "增量同步：处理 $LAST_SYNCED_SHA..$LATEST_SHA"

    # 获取内部仓库当前分支的 HEAD 作为基础
    git fetch "$INTERNAL_REMOTE" "$BRANCH_NAME" 2>/dev/null || true
    INTERNAL_HEAD=$(git rev-parse "$INTERNAL_REMOTE/$BRANCH_NAME" 2>/dev/null)

    if [ -z "$INTERNAL_HEAD" ]; then
        print_error "无法获取内部仓库 $BRANCH_NAME 分支，请先执行全量同步: ./sync-to-internal.sh --full"
        exit 1
    fi

    # 创建临时分支，基于内部仓库当前 HEAD
    git checkout -b "$TEMP_BRANCH" "$INTERNAL_HEAD"

    # 逐个 cherry-pick 新提交并重写作者
    FAILED=0
    for COMMIT_SHA in $(git rev-list --reverse "$LAST_SYNCED_SHA".."$LATEST_SHA"); do
        ORIG_AUTHOR=$(git log -1 --format='%an' "$COMMIT_SHA")
        MAPPED=$(map_author "$ORIG_AUTHOR")
        NEW_NAME="${MAPPED%%|*}"
        NEW_EMAIL="${MAPPED##*|}"

        if ! git cherry-pick --allow-empty "$COMMIT_SHA" >/dev/null 2>&1; then
            # 冲突时尝试用 theirs 策略
            if ! git cherry-pick --abort 2>/dev/null; then true; fi
            if ! git cherry-pick --allow-empty --strategy=recursive -X theirs "$COMMIT_SHA" >/dev/null 2>&1; then
                print_error "Cherry-pick 失败: $COMMIT_SHA ($(git log -1 --format='%s' "$COMMIT_SHA"))"
                print_error "请使用全量同步: ./sync-to-internal.sh --full"
                git cherry-pick --abort 2>/dev/null || true
                git checkout "$BRANCH_NAME"
                git branch -D "$TEMP_BRANCH" 2>/dev/null || true
                FAILED=1
                break
            fi
        fi

        # 重写作者信息
        git commit --amend --no-edit \
            --author="$NEW_NAME <$NEW_EMAIL>" \
            --quiet 2>/dev/null || true
    done

    if [ "$FAILED" -eq 1 ]; then
        exit 1
    fi

    # 推送到内部仓库
    print_info "推送到内部仓库 $INTERNAL_REMOTE/$BRANCH_NAME..."
    git push -f "$INTERNAL_REMOTE" "$TEMP_BRANCH:$BRANCH_NAME"

    # 清理
    git checkout "$BRANCH_NAME"
    git branch -D "$TEMP_BRANCH"
fi

# 记录本次同步的 SHA
echo "$LATEST_SHA" > "$MARKER_FILE"
print_info "同步标记已更新: $LATEST_SHA"

print_info "✅ 同步完成！"
print_info "内部仓库 $INTERNAL_REMOTE/$BRANCH_NAME 已更新"
