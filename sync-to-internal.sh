#!/bin/bash

# 同步 GitHub 代码到内部仓库的脚本
# 用法：./sync-to-internal.sh [branch_name]
# 默认分支：dev

set -e

# 配置变量
BRANCH_NAME="${1:-dev}"
TEMP_BRANCH="sync-internal-$(date +%s)"
GITHUB_REMOTE="origin"
INTERNAL_REMOTE="internal"

# 默认内部仓库提交者信息（未匹配到映射时使用）
DEFAULT_INTERNAL_AUTHOR_NAME="王坦"
DEFAULT_INTERNAL_AUTHOR_EMAIL="wangt091@chinatelecom.cn"

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

# 创建临时分支
print_info "创建临时分支 $TEMP_BRANCH..."
git checkout -b "$TEMP_BRANCH" "$GITHUB_REMOTE/$BRANCH_NAME"

# 重写提交历史（根据原始提交者映射到对应的内部提交者）
print_info "重写提交历史（根据提交者映射修改作者信息）..."

git filter-branch -f --env-filter '
# 根据原始提交者姓名设置内部提交者信息
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

# 切换回原分支
print_info "切换回原分支 $BRANCH_NAME..."
git checkout "$BRANCH_NAME"

# 删除临时分支
print_info "删除临时分支 $TEMP_BRANCH..."
git branch -D "$TEMP_BRANCH"

# 清理备份引用
print_info "清理 Git 备份引用..."
git update-ref -d "refs/original/refs/heads/$TEMP_BRANCH" 2>/dev/null || true

# 清理垃圾回收
print_info "执行 Git 垃圾回收..."
git reflog expire --expire=now --all 2>/dev/null || true
git gc --prune=now --aggressive 2>/dev/null || true

print_info "✅ 同步完成！"
print_info "内部仓库 $INTERNAL_REMOTE/$BRANCH_NAME 已更新"
