# 运行时数据迁移参考（不用于通用镜像构建）

> **当前规则**：通用 QwenPaw 镜像从 `deploy-all/qwenpaw/working/` 生成无环境工作目录 seed，不读取或打包 `deploy-all/qwenpaw/data/qwenpaw/` 或 `~/.qwenpaw`。按当前发布要求，唯一例外是 `deploy-all/qwenpaw/data/qwenpaw.secret/`：它会随镜像交付已配置的大模型。请参阅 [`QWENPAW_IMAGE_BUILD.md`](QWENPAW_IMAGE_BUILD.md) 了解正式打包流程。
>
> 本文以下内容仅供迁移、备份或恢复某个**已明确目标环境**的运行时数据时参考。运行数据库、知识库上传文件和外部系统凭据不得将按本文步骤复制回通用镜像构建输入。

本文档记录如何在特定环境中处理 `~/.qwenpaw` 的运行时数据。

## 目录结构对照

| 本地目录 | 部署目录 | 说明 |
|---------|---------|------|
| `~/.qwenpaw/` | `deploy-all/qwenpaw/data/qwenpaw/` | 主目录 |
| `~/.qwenpaw.secret/` | `deploy-all/qwenpaw/data/qwenpaw.secret/` | 大模型配置（API Key 等） |
| `~/.qwenpaw/secrets/` | `deploy-all/qwenpaw/data/qwenpaw/secrets/` | 外部系统连接凭证 |

> **安全提示**：按当前发布要求，`qwenpaw.secret` 会随镜像交付以提供预配置模型。该目录可能包含 API Key、`.master_key` 与 OAuth 状态，因此镜像 tar、导出目录和文件服务器均必须按密钥材料限制访问；绝不能提交到仓库或公开分发。

## 同步步骤

> **执行前必须先确认环境**：同步 `data` 目录前，先询问”这次同步的是什么环境？4A、北京环境、上海环境、大装置、生产环境、公网演示环境、公网测试环境，还是本地测试？”
>
> data 目录中的服务地址按环境替换规则如下：
>
> | 原地址 | 4A 环境 | 北京环境 | 上海环境 | 大装置环境 | 生产环境 | 公网演示环境 | 公网测试环境 | 本地测试环境 |
> |--------|---------|----------|----------|------------|----------|--------------|--------------|--------------|
> | `http://172.28.75.4:30080` | `http://10.141.245.15:30080` | `http://10.3.39.246:30080` | `http://172.16.1.32:30080` | `http://172.28.75.4:30080` | `http://gateway:8080` | `http://82.156.83.38:30080` | `http://81.70.93.245:30080` | 不替换 |
> | `http://192.168.134.96:30080` | `http://10.141.245.15:30080` | `http://10.3.39.246:30080` | `http://172.16.1.32:30080` | `http://172.28.75.4:30080` | `http://gateway:8080` | `http://82.156.83.38:30080` | `http://81.70.93.245:30080` | 不替换 |
> | `http://192.168.134.96:30081` | `http://10.141.245.15:30081` | `http://10.3.39.246:30081` | `http://172.16.1.32:30081` | `http://172.28.75.4:30081` | 不替换 | `http://82.156.83.38:30081` | `http://81.70.93.245:30081` | 不替换 |
> | `http://192.168.134.96:31089` | `http://10.141.245.15:31089` | `http://10.3.39.246:31089` | `http://172.16.1.32:31089` | `http://172.28.75.4:31089` | 不替换 | `http://82.156.83.38:31089` | `http://81.70.93.245:31089` | 不替换 |
> | `http://192.168.134.96:30001` | `http://10.141.245.15:3000` | `http://10.3.39.246:3000` | `http://172.16.1.32:3000` | `http://172.28.75.4:3000` | 不替换 | `http://82.156.83.38:3000` | `http://81.70.93.245:3000` | 不替换 |
> | `http://192.168.134.96:31010` | `http://10.141.245.15:31010` | `http://10.3.39.246:31010` | `http://172.16.1.32:31010` | `http://172.28.75.4:31010` | 不替换 | `http://82.156.83.38:31010` | `http://81.70.93.245:31010` | 不替换 |
> | `http://192.168.134.96:17001` | `http://10.141.245.15:17001` | `http://10.3.39.246:17001` | `http://172.16.1.32:17001` | `http://172.28.75.4:17001` | 不替换 | `http://82.156.83.38:17001` | `http://81.70.93.245:17001` | 不替换 |

### 1. 清理旧版目录和文件

```bash
# 清理工作区旧目录
cd deploy-all/qwenpaw/data/qwenpaw
find workspaces -type d \( -name "active_skills" -o -name "customized_skills" -o -name "dialog" -o -name "embedding_cache" \) -exec rm -rf {} + 2>/dev/null

# 清理旧文件
find workspaces -type f \( -name "copaw_file_metadata.json" -o -name "token_usage.json" -o -name "memory.md" \) -delete 2>/dev/null
rm -f copaw_file_metadata.json 2>/dev/null
```

### 2. 同步共享技能池

```bash
rm -rf deploy-all/qwenpaw/data/qwenpaw/skill_pool 2>/dev/null
mkdir -p deploy-all/qwenpaw/data/qwenpaw/skill_pool
rsync -a --exclude='.DS_Store' --exclude='__pycache__' --exclude='*.pyc' --exclude='.venv' --exclude='.lock' --exclude='.git' \
  ~/.qwenpaw/skill_pool/ deploy-all/qwenpaw/data/qwenpaw/skill_pool/
```

### 3. 同步工作区技能目录

```bash
for ws in $(ls ~/.qwenpaw/workspaces/); do
  # 删除旧的 skills 目录
  rm -rf "deploy-all/qwenpaw/data/qwenpaw/workspaces/$ws/skills" 2>/dev/null
  rm -rf "deploy-all/qwenpaw/data/qwenpaw/workspaces/$ws/.skill.json.lock" 2>/dev/null
  
  # 同步 skills 目录
  if [ -d ~/.qwenpaw/workspaces/$ws/skills ]; then
    mkdir -p "deploy-all/qwenpaw/data/qwenpaw/workspaces/$ws/skills"
    rsync -a --exclude='.DS_Store' --exclude='__pycache__' --exclude='*.pyc' --exclude='.venv' --exclude='.lock' --exclude='.git' \
      ~/.qwenpaw/workspaces/$ws/skills/ "deploy-all/qwenpaw/data/qwenpaw/workspaces/$ws/skills/"
  fi
  
  # 同步 skill.json
  if [ -f ~/.qwenpaw/workspaces/$ws/skill.json ]; then
    cp ~/.qwenpaw/workspaces/$ws/skill.json "deploy-all/qwenpaw/data/qwenpaw/workspaces/$ws/"
  fi
done
```

### 4. 同步 extensions 目录（运行时设置数据库 + 仓库内置扩展）

```bash
# 先清理旧的 extensions 目录，避免遗留无效文件
rm -rf deploy-all/qwenpaw/data/qwenpaw/extensions 2>/dev/null
mkdir -p deploy-all/qwenpaw/data/qwenpaw/extensions

# 同步本地 extensions 运行数据。通知通道等设置统一保存在
# extensions/settings/settings.db；该数据库可能含 webhook 和密钥，
# 同步前必须确认目标环境，且不要将真实凭据提交到仓库。
if [ -d ~/.qwenpaw/extensions ]; then
  rsync -a --exclude='.DS_Store' --exclude='__pycache__' --exclude='*.pyc' --exclude='.git' \
    ~/.qwenpaw/extensions/ deploy-all/qwenpaw/data/qwenpaw/extensions/
fi

# 再覆盖仓库内置 extensions 代码（如 notification_settings.py）。
# 不再提供 notifications helper；通知配置由 settings.db 物化为环境变量。
if [ -d deploy-all/qwenpaw/working/extensions ]; then
  rsync -a --exclude='.DS_Store' --exclude='__pycache__' --exclude='*.pyc' --exclude='.git' \
    deploy-all/qwenpaw/working/extensions/ deploy-all/qwenpaw/data/qwenpaw/extensions/
fi
```

> **说明**：`deploy-all/qwenpaw/working/extensions` 维护随仓库发布的扩展辅助代码；`~/.qwenpaw/extensions/settings/settings.db` 是共享运行时设置数据库。数据库可含 webhook、secret 等敏感信息，务必在同步前确认 4A / 北京 / 上海 / 大装置 / 生产 / 本地目标环境，不能用某个环境的数据库覆盖另一个环境。

### 5. 同步配置文件并替换路径

```bash
# 同步并更新 config.json
cp ~/.qwenpaw/config.json deploy-all/qwenpaw/data/qwenpaw/config.json
sed -i '' 's|/Users/[^/]*/\.qwenpaw|/app/working|g' deploy-all/qwenpaw/data/qwenpaw/config.json
sed -i '' 's|/Users/[^/]*/\.copaw|/app/working|g' deploy-all/qwenpaw/data/qwenpaw/config.json
sed -i '' 's|~/.qwenpaw|/app/working|g' deploy-all/qwenpaw/data/qwenpaw/config.json
sed -i '' 's|~/.copaw|/app/working|g' deploy-all/qwenpaw/data/qwenpaw/config.json

# 同步并更新各工作区的 agent.json
for ws in $(ls ~/.qwenpaw/workspaces/); do
  if [ -f ~/.qwenpaw/workspaces/$ws/agent.json ]; then
    cp ~/.qwenpaw/workspaces/$ws/agent.json "deploy-all/qwenpaw/data/qwenpaw/workspaces/$ws/agent.json"
    sed -i '' 's|/Users/[^/]*/\.qwenpaw|/app/working|g' "deploy-all/qwenpaw/data/qwenpaw/workspaces/$ws/agent.json"
    sed -i '' 's|/Users/[^/]*/\.copaw|/app/working|g' "deploy-all/qwenpaw/data/qwenpaw/workspaces/$ws/agent.json"
    sed -i '' 's|~/.qwenpaw|/app/working|g' "deploy-all/qwenpaw/data/qwenpaw/workspaces/$ws/agent.json"
    sed -i '' 's|~/.copaw|/app/working|g' "deploy-all/qwenpaw/data/qwenpaw/workspaces/$ws/agent.json"
  fi
done

# 更新 skill.json 路径
for ws in $(ls ~/.qwenpaw/workspaces/); do
  if [ -f "deploy-all/qwenpaw/data/qwenpaw/workspaces/$ws/skill.json" ]; then
    sed -i '' 's|/Users/[^/]*/\.qwenpaw|/app/working|g' "deploy-all/qwenpaw/data/qwenpaw/workspaces/$ws/skill.json"
    sed -i '' 's|/Users/[^/]*/\.copaw|/app/working|g' "deploy-all/qwenpaw/data/qwenpaw/workspaces/$ws/skill.json"
    sed -i '' 's|~/.qwenpaw|/app/working|g' "deploy-all/qwenpaw/data/qwenpaw/workspaces/$ws/skill.json"
    sed -i '' 's|~/.copaw|/app/working|g' "deploy-all/qwenpaw/data/qwenpaw/workspaces/$ws/skill.json"
  fi
done

# 更新 skill_pool/skill.json 路径
if [ -f deploy-all/qwenpaw/data/qwenpaw/skill_pool/skill.json ]; then
  sed -i '' 's|/Users/[^/]*/\.qwenpaw|/app/working|g' deploy-all/qwenpaw/data/qwenpaw/skill_pool/skill.json
  sed -i '' 's|/Users/[^/]*/\.copaw|/app/working|g' deploy-all/qwenpaw/data/qwenpaw/skill_pool/skill.json
  sed -i '' 's|~/.qwenpaw|/app/working|g' deploy-all/qwenpaw/data/qwenpaw/skill_pool/skill.json
  sed -i '' 's|~/.copaw|/app/working|g' deploy-all/qwenpaw/data/qwenpaw/skill_pool/skill.json
fi
```

#### 按环境替换 `data` 目录中的服务地址

```bash
echo "这次同步的是什么环境？"
echo "1) 4A"
echo "2) 北京环境"
echo "3) 上海环境"
echo "4) 大装置"
echo "5) 生产环境"
echo "6) 公网演示环境 (82.156.83.38)"
echo "7) 公网测试环境 (81.70.93.245)"
echo "8) 本地测试（不替换服务地址）"
read -r TARGET_ENV

case "$TARGET_ENV" in
  1|4A|4a)
    TARGET_HOST="10.141.245.15"
    TARGET_ENV_NAME="4A"
    SHOULD_REPLACE_SERVICE_URLS=true
    ;;
  2|北京|北京环境|beijing|bj)
    TARGET_HOST="10.3.39.246"
    TARGET_ENV_NAME="北京环境"
    SHOULD_REPLACE_SERVICE_URLS=true
    ;;
  3|上海|上海环境|shanghai|sh)
    TARGET_HOST="172.16.1.32"
    TARGET_ENV_NAME="上海环境"
    SHOULD_REPLACE_SERVICE_URLS=true
    ;;
  4|大装置)
    TARGET_HOST="172.28.75.4"
    TARGET_ENV_NAME="大装置"
    SHOULD_REPLACE_SERVICE_URLS=true
    ;;
  5|生产|生产环境|prod|production)
    TARGET_HOST=""
    TARGET_ENV_NAME="生产环境"
    SHOULD_REPLACE_SERVICE_URLS=true
    ;;
  6|公网演示|公网演示环境|demo)
    TARGET_HOST="82.156.83.38"
    TARGET_ENV_NAME="公网演示环境"
    SHOULD_REPLACE_SERVICE_URLS=true
    ;;
  7|公网测试|公网测试环境|test)
    TARGET_HOST="81.70.93.245"
    TARGET_ENV_NAME="公网测试环境"
    SHOULD_REPLACE_SERVICE_URLS=true
    ;;
  8|本地测试|local|本地)
    TARGET_HOST=""
    TARGET_ENV_NAME="本地测试"
    SHOULD_REPLACE_SERVICE_URLS=false
    ;;
  *)
    echo "未知环境: $TARGET_ENV"
    exit 1
    ;;
esac

if [ "$SHOULD_REPLACE_SERVICE_URLS" = true ]; then
  find deploy-all/qwenpaw/data/qwenpaw -type f \
    \( -name "*.json" -o -name "*.md" -o -name "*.txt" -o -name "*.yaml" -o -name "*.yml" -o -name "*.env" -o -name "*.sh" \) \
    -print0 | while IFS= read -r -d '' file; do
      if [ "$TARGET_ENV_NAME" = "生产环境" ]; then
        sed -i '' "s|http://172.28.75.4:30080|http://gateway:8080|g" "$file"
        sed -i '' "s|http://192.168.134.96:30080|http://gateway:8080|g" "$file"
      else
        sed -i '' "s|http://172.28.75.4:30080|http://$TARGET_HOST:30080|g" "$file"
        sed -i '' "s|http://192.168.134.96:30080|http://$TARGET_HOST:30080|g" "$file"
        sed -i '' "s|http://192.168.134.96:30081|http://$TARGET_HOST:30081|g" "$file"
        sed -i '' "s|http://192.168.134.96:31089|http://$TARGET_HOST:31089|g" "$file"
        sed -i '' "s|http://192.168.134.96:30001|http://$TARGET_HOST:3000|g" "$file"
        sed -i '' "s|http://192.168.134.96:31010|http://$TARGET_HOST:31010|g" "$file"
        sed -i '' "s|http://192.168.134.96:17001|http://$TARGET_HOST:17001|g" "$file"
      fi
    done

  echo "已按 $TARGET_ENV_NAME 环境完成 data 目录地址替换"
else
  echo "本地测试环境不替换 data 目录中的服务地址"
fi
```

### 6. 同步工作区其他文件

```bash
for ws in $(ls ~/.qwenpaw/workspaces/); do
  # 同步必要的 JSON 文件
  for f in chats.json jobs.json feishu_receive_ids.json; do
    if [ -f ~/.qwenpaw/workspaces/$ws/$f ]; then
      cp ~/.qwenpaw/workspaces/$ws/$f "deploy-all/qwenpaw/data/qwenpaw/workspaces/$ws/$f"
    fi
  done
  
  # 同步 Markdown 文件
  for f in AGENTS.md BOOTSTRAP.md HEARTBEAT.md MEMORY.md PROFILE.md SOUL.md; do
    if [ -f ~/.qwenpaw/workspaces/$ws/$f ]; then
      cp ~/.qwenpaw/workspaces/$ws/$f "deploy-all/qwenpaw/data/qwenpaw/workspaces/$ws/$f"
    fi
  done
done
```

### 7. 同步大模型配置目录 (qwenpaw.secret)

```bash
# 同步 qwenpaw.secret 目录（包含大模型 Provider 配置）
rm -rf deploy-all/qwenpaw/data/qwenpaw.secret 2>/dev/null
mkdir -p deploy-all/qwenpaw/data/qwenpaw.secret
rsync -a --exclude='.DS_Store' \
  ~/.qwenpaw.secret/ deploy-all/qwenpaw/data/qwenpaw.secret/
```

> **说明**：`qwenpaw.secret` 目录包含大模型 API Key 等敏感配置，需要打包到镜像中，容器启动后会自动加载。请确保该目录中的 API Key 是有效的，或者在部署后通过环境变量覆盖。

### 8. 同步外部系统凭证目录 (secrets)

```bash
# 同步 secrets 目录（包含外部系统连接凭证）
rm -rf deploy-all/qwenpaw/data/qwenpaw/secrets 2>/dev/null
mkdir -p deploy-all/qwenpaw/data/qwenpaw/secrets
rsync -a --exclude='.DS_Store' \
  ~/.qwenpaw/secrets/ deploy-all/qwenpaw/data/qwenpaw/secrets/
```

> **说明**：`secrets` 目录包含外部系统的连接凭证 `.env` 文件，如：
> - `inoe.env` - 智观告警平台连接配置
> - `n9e.env` - 夜莺监控连接配置
> - `zgops-cmdb.env` - CMDB 连接配置
>
> 每个 `.env` 文件都有对应的 `.env.example` 示例文件。部署到不同环境时需根据实际情况修改凭证内容。

### 9. 清理运行时数据（不打包进镜像）

```bash
for ws in $(ls deploy-all/qwenpaw/data/qwenpaw/workspaces/); do
  rm -rf "deploy-all/qwenpaw/data/qwenpaw/workspaces/$ws/sessions" 2>/dev/null
  rm -rf "deploy-all/qwenpaw/data/qwenpaw/workspaces/$ws/file_store" 2>/dev/null
  rm -rf "deploy-all/qwenpaw/data/qwenpaw/workspaces/$ws/tool_result" 2>/dev/null
  rm -f "deploy-all/qwenpaw/data/qwenpaw/workspaces/$ws/chats.json" 2>/dev/null
  rm -f "deploy-all/qwenpaw/data/qwenpaw/workspaces/$ws/feishu_receive_ids.json" 2>/dev/null
done

rm -f deploy-all/qwenpaw/data/qwenpaw/token_usage.json 2>/dev/null
rm -f deploy-all/qwenpaw/data/qwenpaw/qwenpaw.log 2>/dev/null
```

### 10. 清理 Python 缓存和系统文件

```bash
find deploy-all/qwenpaw/data/qwenpaw -type d \( -name ".venv" -o -name "__pycache__" -o -name "*.egg-info" -o -name ".git" \) -exec rm -rf {} + 2>/dev/null
find deploy-all/qwenpaw/data/qwenpaw -name "*.pyc" -delete 2>/dev/null
find deploy-all/qwenpaw/data/qwenpaw -name ".DS_Store" -delete 2>/dev/null
```

### 11. 敏感文件处理

**注意**：`.env` 文件包含 API Token 等敏感信息，请根据实际情况决定是否保留。

> **重要提示**：Skills 目录下的 `.env` 文件通常包含外部系统的 API Token（如告警系统、数据库连接等）。同步前请确认：
> - 该 Token 是否可以用于生产环境
> - 是否需要使用环境变量或 Secret 替代
> - 是否需要与运维团队确认

```bash
# 询问是否同步 .env 文件
echo "是否保留 .env 文件？(Y/n)"
read -r SYNC_ENV

if [ -z "${SYNC_ENV:-}" ] || [ "$SYNC_ENV" = "y" ] || [ "$SYNC_ENV" = "Y" ]; then
  echo "保留 .env 文件..."
else
  echo "删除 .env 文件..."
  find deploy-all/qwenpaw/data/qwenpaw -name ".env" -type f -delete 2>/dev/null
fi
```

或者直接决定：

```bash
# 如果不需要打包敏感配置，删除 .env 文件
find deploy-all/qwenpaw/data/qwenpaw -name ".env" -type f -delete 2>/dev/null

# 如果需要保留，确保 .env 文件已同步
```

## 路径替换规则

| 本地路径 | 容器路径 |
|---------|---------|
| `/Users/<用户名>/.qwenpaw` | `/app/working` |
| `/Users/<用户名>/.copaw` | `/app/working` |
| `~/.qwenpaw` | `/app/working` |
| `~/.copaw` | `/app/working` |

## 已废弃的目录/文件

以下目录/文件是旧版本遗留，应删除：

| 类型 | 名称 | 说明 |
|------|------|------|
| 目录 | `active_skills/` | 旧版技能目录，已迁移到 `skills/` |
| 目录 | `customized_skills/` | 旧版自定义技能目录 |
| 目录 | `dialog/` | 空目录，未使用 |
| 目录 | `embedding_cache/` | 空目录，未使用 |
| 文件 | `copaw_file_metadata.json` | 未被代码引用的缓存文件 |
| 文件 | `token_usage.json` (工作区内) | 空数组，实际使用根目录版本 |
| 文件 | `memory.md` | 与 `MEMORY.md` 重复（小写旧版） |

## 不应打包的运行时数据

以下数据在容器运行时生成，不应打包进镜像：

| 目录/文件 | 说明 |
|----------|------|
| `sessions/` | 会话数据 |
| `file_store/` | 文件存储（含向量数据库） |
| `tool_result/` | 工具结果缓存 |
| `chats.json` | 聊天记录 |
| `feishu_receive_ids.json` | 飞书接收 ID |
| `token_usage.json` | Token 使用统计 |
| `qwenpaw.log` | 日志文件 |
| `.venv/` | Python 虚拟环境 |
| `__pycache__/` | Python 缓存 |
| `*.pyc` | 编译后的 Python 文件 |
| `.git/`（嵌套仓库） | 技能目录被 `uv init` 等建出的内嵌 git 仓库，不应进镜像（rsync 已 `--exclude='.git'`，Step 10 再兜底清理）|

## 一键同步脚本

可以将以上步骤合并为一个脚本 `sync-from-local.sh`（建议保存在**仓库根目录**）：

```bash
#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DEPLOY_ROOT="$SCRIPT_DIR/deploy-all/qwenpaw/data"
DEPLOY_DIR="$DEPLOY_ROOT/qwenpaw"
SECRET_DIR="$DEPLOY_ROOT/qwenpaw.secret"
LOCAL_DIR="$HOME/.qwenpaw"
LOCAL_SECRET_DIR="$HOME/.qwenpaw.secret"
REPO_WORKING_DIR="$SCRIPT_DIR/deploy-all/qwenpaw/working"

echo "这次同步的是什么环境？"
echo "1) 4A"
echo "2) 北京环境"
echo "3) 上海环境"
echo "4) 大装置"
echo "5) 生产环境"
echo "6) 公网演示环境 (82.156.83.38)"
echo "7) 公网测试环境 (81.70.93.245)"
echo "8) 本地测试（不替换服务地址）"
read -r TARGET_ENV

case "$TARGET_ENV" in
  1|4A|4a)
    TARGET_HOST="10.141.245.15"
    TARGET_ENV_NAME="4A"
    SHOULD_REPLACE_SERVICE_URLS=true
    ;;
  2|北京|北京环境|beijing|bj)
    TARGET_HOST="10.3.39.246"
    TARGET_ENV_NAME="北京环境"
    SHOULD_REPLACE_SERVICE_URLS=true
    ;;
  3|上海|上海环境|shanghai|sh)
    TARGET_HOST="172.16.1.32"
    TARGET_ENV_NAME="上海环境"
    SHOULD_REPLACE_SERVICE_URLS=true
    ;;
  4|大装置)
    TARGET_HOST="172.28.75.4"
    TARGET_ENV_NAME="大装置"
    SHOULD_REPLACE_SERVICE_URLS=true
    ;;
  5|生产|生产环境|prod|production)
    TARGET_HOST=""
    TARGET_ENV_NAME="生产环境"
    SHOULD_REPLACE_SERVICE_URLS=true
    ;;
  6|公网演示|公网演示环境|demo)
    TARGET_HOST="82.156.83.38"
    TARGET_ENV_NAME="公网演示环境"
    SHOULD_REPLACE_SERVICE_URLS=true
    ;;
  7|公网测试|公网测试环境|test)
    TARGET_HOST="81.70.93.245"
    TARGET_ENV_NAME="公网测试环境"
    SHOULD_REPLACE_SERVICE_URLS=true
    ;;
  8|本地测试|local|本地)
    TARGET_HOST=""
    TARGET_ENV_NAME="本地测试"
    SHOULD_REPLACE_SERVICE_URLS=false
    ;;
  *)
    echo "未知环境: $TARGET_ENV" >&2
    exit 1
    ;;
esac

replace_service_urls() {
  local target_dir="$1"
  if [ "$SHOULD_REPLACE_SERVICE_URLS" != true ]; then
    echo "[$TARGET_ENV_NAME] 跳过服务地址替换"
    return
  fi
  find "$target_dir" -type f \
    \( -name "*.json" -o -name "*.md" -o -name "*.txt" -o -name "*.yaml" -o -name "*.yml" -o -name "*.env" -o -name "*.sh" \) \
    -print0 | while IFS= read -r -d '' file; do
      if [ "$TARGET_ENV_NAME" = "生产环境" ]; then
        sed -i '' "s|http://172.28.75.4:30080|http://gateway:8080|g" "$file"
        sed -i '' "s|http://192.168.134.96:30080|http://gateway:8080|g" "$file"
      else
        sed -i '' "s|http://172.28.75.4:30080|http://$TARGET_HOST:30080|g" "$file"
        sed -i '' "s|http://192.168.134.96:30080|http://$TARGET_HOST:30080|g" "$file"
        sed -i '' "s|http://192.168.134.96:30081|http://$TARGET_HOST:30081|g" "$file"
        sed -i '' "s|http://192.168.134.96:31089|http://$TARGET_HOST:31089|g" "$file"
        sed -i '' "s|http://192.168.134.96:30001|http://$TARGET_HOST:3000|g" "$file"
        sed -i '' "s|http://192.168.134.96:31010|http://$TARGET_HOST:31010|g" "$file"
        sed -i '' "s|http://192.168.134.96:17001|http://$TARGET_HOST:17001|g" "$file"
      fi
    done
}

mkdir -p "$DEPLOY_DIR" "$SECRET_DIR" "$DEPLOY_DIR/workspaces"

echo "=== Step 1: Clean old directories ==="
cd "$DEPLOY_DIR"
find workspaces -type d \( -name "active_skills" -o -name "customized_skills" -o -name "dialog" -o -name "embedding_cache" \) -exec rm -rf {} + 2>/dev/null || true
find workspaces -type f \( -name "copaw_file_metadata.json" -o -name "token_usage.json" -o -name "memory.md" \) -delete 2>/dev/null || true

echo "=== Step 2: Sync skill_pool ==="
rm -rf skill_pool
mkdir -p skill_pool
rsync -a --exclude='.DS_Store' --exclude='__pycache__' --exclude='*.pyc' --exclude='.venv' --exclude='.lock' --exclude='.git' \
  "$LOCAL_DIR/skill_pool/" skill_pool/

echo "=== Step 3: Sync workspace skills ==="
for ws in $(ls "$LOCAL_DIR/workspaces/"); do
  rm -rf "workspaces/$ws/skills" "workspaces/$ws/.skill.json.lock" 2>/dev/null || true
  if [ -d "$LOCAL_DIR/workspaces/$ws/skills" ]; then
    mkdir -p "workspaces/$ws/skills"
    rsync -a --exclude='.DS_Store' --exclude='__pycache__' --exclude='*.pyc' --exclude='.venv' --exclude='.lock' --exclude='.git' \
      "$LOCAL_DIR/workspaces/$ws/skills/" "workspaces/$ws/skills/"
  fi
  [ -f "$LOCAL_DIR/workspaces/$ws/skill.json" ] && cp "$LOCAL_DIR/workspaces/$ws/skill.json" "workspaces/$ws/"
done

echo "=== Step 4: Sync extensions ==="
rm -rf extensions 2>/dev/null || true
mkdir -p extensions
if [ -d "$LOCAL_DIR/extensions" ]; then
  rsync -a --exclude='.DS_Store' --exclude='__pycache__' --exclude='*.pyc' --exclude='.git' \
    "$LOCAL_DIR/extensions/" extensions/
fi
if [ -d "$REPO_WORKING_DIR/extensions" ]; then
  rsync -a --exclude='.DS_Store' --exclude='__pycache__' --exclude='*.pyc' --exclude='.git' \
    "$REPO_WORKING_DIR/extensions/" extensions/
fi

echo "=== Step 5: Sync config files and update paths ==="
cp "$LOCAL_DIR/config.json" config.json
sed -i '' 's|/Users/[^/]*/\.qwenpaw|/app/working|g' config.json
sed -i '' 's|/Users/[^/]*/\.copaw|/app/working|g' config.json
sed -i '' 's|~/.qwenpaw|/app/working|g' config.json
sed -i '' 's|~/.copaw|/app/working|g' config.json

for ws in $(ls "$LOCAL_DIR/workspaces/"); do
  if [ -f "$LOCAL_DIR/workspaces/$ws/agent.json" ]; then
    cp "$LOCAL_DIR/workspaces/$ws/agent.json" "workspaces/$ws/agent.json"
    sed -i '' 's|/Users/[^/]*/\.qwenpaw|/app/working|g' "workspaces/$ws/agent.json"
    sed -i '' 's|/Users/[^/]*/\.copaw|/app/working|g' "workspaces/$ws/agent.json"
    sed -i '' 's|~/.qwenpaw|/app/working|g' "workspaces/$ws/agent.json"
    sed -i '' 's|~/.copaw|/app/working|g' "workspaces/$ws/agent.json"
  fi
  [ -f "workspaces/$ws/skill.json" ] && sed -i '' 's|~/.qwenpaw|/app/working|g; s|~/.copaw|/app/working|g; s|/Users/[^/]*/\.qwenpaw|/app/working|g; s|/Users/[^/]*/\.copaw|/app/working|g' "workspaces/$ws/skill.json"
done

[ -f skill_pool/skill.json ] && sed -i '' 's|~/.qwenpaw|/app/working|g; s|~/.copaw|/app/working|g; s|/Users/[^/]*/\.qwenpaw|/app/working|g; s|/Users/[^/]*/\.copaw|/app/working|g' skill_pool/skill.json

echo "=== Step 6: Sync workspace files ==="
for ws in $(ls "$LOCAL_DIR/workspaces/"); do
  for f in AGENTS.md BOOTSTRAP.md HEARTBEAT.md MEMORY.md PROFILE.md SOUL.md chats.json jobs.json; do
    [ -f "$LOCAL_DIR/workspaces/$ws/$f" ] && cp "$LOCAL_DIR/workspaces/$ws/$f" "workspaces/$ws/"
  done
done

echo "=== Step 6.1: Replace service URLs by environment ($TARGET_ENV_NAME) ==="
replace_service_urls "$DEPLOY_DIR"

echo "=== Step 7: Sync qwenpaw.secret (model providers) ==="
rm -rf "$SECRET_DIR" 2>/dev/null || true
mkdir -p "$SECRET_DIR"
rsync -a --exclude='.DS_Store' "$LOCAL_SECRET_DIR/" "$SECRET_DIR/"

echo "=== Step 8: Sync secrets (external system credentials) ==="
rm -rf "$DEPLOY_DIR/secrets" 2>/dev/null || true
mkdir -p "$DEPLOY_DIR/secrets"
rsync -a --exclude='.DS_Store' "$LOCAL_DIR/secrets/" "$DEPLOY_DIR/secrets/"

echo "=== Step 9: Clean runtime data ==="
for ws in $(ls workspaces/); do
  rm -rf "workspaces/$ws/sessions" "workspaces/$ws/file_store" "workspaces/$ws/tool_result" 2>/dev/null || true
  rm -f "workspaces/$ws/chats.json" "workspaces/$ws/feishu_receive_ids.json" 2>/dev/null || true
done
rm -f token_usage.json qwenpaw.log 2>/dev/null || true

echo "=== Step 10: Clean cache files ==="
find . -type d \( -name ".venv" -o -name "__pycache__" -o -name ".git" \) -exec rm -rf {} + 2>/dev/null || true
find . -name "*.pyc" -delete 2>/dev/null || true
find . -name ".DS_Store" -delete 2>/dev/null || true

echo "=== Step 11: Handle .env files ==="
echo "Skills 目录下可能包含 .env 文件（如 real-alarm/.env 包含 API Token）"
echo "是否保留 .env 文件？(Y/n)"
read -r SYNC_ENV
if [ -z "${SYNC_ENV:-}" ] || [ "$SYNC_ENV" = "y" ] || [ "$SYNC_ENV" = "Y" ]; then
  echo "保留 .env 文件..."
else
  echo "删除 .env 文件..."
  find . -name ".env" -type f -delete 2>/dev/null || true
fi

echo "=== Done ==="
du -sh .
```

## 验证同步结果

```bash
# 检查主目录结构
ls deploy-all/qwenpaw/data/qwenpaw/
ls deploy-all/qwenpaw/data/qwenpaw/extensions/settings/settings.db
ls deploy-all/qwenpaw/data/qwenpaw/workspaces/fault/
ls deploy-all/qwenpaw/data/qwenpaw/skill_pool/

# 检查大模型配置目录
ls deploy-all/qwenpaw/data/qwenpaw.secret/
ls deploy-all/qwenpaw/data/qwenpaw.secret/providers/
cat deploy-all/qwenpaw/data/qwenpaw.secret/providers/active_model.json

# 检查路径是否正确替换
grep "/app/working" deploy-all/qwenpaw/data/qwenpaw/config.json | head -5

# 检查是否有残留的本地路径（递归检查所有 JSON）
grep -r "~/.qwenpaw\|~/.copaw\|/Users/.*/\.\(qwenpaw\|copaw\)" deploy-all/qwenpaw/data/qwenpaw || echo "No local paths found"

# 检查旧环境地址是否已清理
grep -r "192\.168\.130\.51" deploy-all/qwenpaw/data/qwenpaw && echo "仍有旧地址，请继续检查" || echo "192.168.134.96 已清理"

# 如果本次是 4A 环境，再额外确认 172.28.75.4:30080 已替换
grep -r "172\.28\.75\.4:30080" deploy-all/qwenpaw/data/qwenpaw && echo "若目标是 4A，请继续检查剩余 30080 地址" || echo "30080 地址已按需替换"

# 如果本次是生产环境，再额外确认 30080 地址已替换为 gateway:8080
grep -r "gateway:8080" deploy-all/qwenpaw/data/qwenpaw && echo "生产环境 gateway:8080 已写入" || echo "请检查生产环境 30080 地址替换"
```

## 版本升级检查

QwenPaw 版本升级后，目录结构可能发生变化。同步前请先检查以下代码文件确认当前结构：

### 1. 检查工作区目录结构

```bash
# 检查工作区使用哪些目录
grep -rn "workspace_dir\|sessions\|memory\|file_store\|media\|tool_result" \
  src/qwenpaw/constant.py src/qwenpaw/config/config.py src/qwenpaw/app/workspace/
```

关键文件：
- `src/qwenpaw/constant.py` - 定义默认目录常量
- `src/qwenpaw/config/config.py` - 配置结构定义
- `src/qwenpaw/app/workspace/workspace.py` - 工作区管理逻辑

### 2. 检查技能目录结构

```bash
# 检查技能目录定义
grep -rn "skills\|skill_pool\|active_skills\|customized_skills" \
  src/qwenpaw/agents/skills_manager.py src/qwenpaw/app/migration.py
```

关键文件：
- `src/qwenpaw/agents/skills_manager.py` - 技能管理核心逻辑
- `src/qwenpaw/app/migration.py` - 迁移逻辑，包含旧目录清理

### 3. 检查废弃目录

```bash
# 检查迁移逻辑中的废弃目录
grep -rn "active_skills\|customized_skills\|dialog\|embedding_cache" \
  src/qwenpaw/app/migration.py
```

迁移文件 `src/qwenpaw/app/migration.py` 中的 `_WORKSPACE_ITEMS_TO_MIGRATE` 和相关注释会说明哪些目录是旧版废弃的。

### 4. 检查运行时数据目录

```bash
# 检查哪些是运行时生成的目录
grep -rn "sessions\|file_store\|tool_result\|chats\.json\|token_usage" \
  src/qwenpaw/constant.py src/qwenpaw/app/workspace/
```

### 5. 检查敏感文件处理

```bash
# 检查 .env 文件的处理方式
grep -rn "\.env\|dotenv" src/qwenpaw/agents/skills_manager.py

# 检查 qwenpaw.secret / copaw.secret 兼容目录定义
grep -rn "secret\|SECRET_DIR\|qwenpaw\.secret\|copaw\.secret" src/qwenpaw/constant.py
```

### 6. 检查大模型配置目录 (qwenpaw.secret)

```bash
# 检查 Provider 配置加载逻辑
grep -rn "providers\|active_model\|qwenpaw.secret" \
  src/qwenpaw/config/config.py src/qwenpaw/agents/
```

关键文件：
- `src/qwenpaw/constant.py` - 定义 `SECRET_DIR` 常量
- `src/qwenpaw/config/config.py` - Provider 配置加载逻辑

### 常见版本升级变化

| 变化类型 | 检查方式 | 示例 |
|---------|---------|------|
| 新增目录 | 检查 `constant.py` 中的新常量 | `MEMORY_DIR`, `CUSTOM_CHANNELS_DIR` |
| 目录重命名 | 检查 `migration.py` 中的迁移逻辑 | `active_skills` → `skills` |
| 废弃目录 | 检查 `migration.py` 中的清理逻辑 | `dialog`, `embedding_cache` |
| 配置结构变化 | 检查 `config.py` 中的模型定义 | 新增字段、字段重命名 |
| 敏感信息处理 | 检查技能加载逻辑 | `.env` 文件是否被 gitignore |
| 大模型配置变化 | 检查 `qwenpaw.secret` 目录结构 | Provider 配置格式变化 |

### 版本升级同步流程

1. **更新代码**
   ```bash
   git pull origin main
   ```

2. **检查变更日志**
   ```bash
   git log --oneline -20
   git diff HEAD~10 -- src/qwenpaw/constant.py src/qwenpaw/app/migration.py
   ```

3. **检查目录结构变化**
   ```bash
   # 按上述方法检查关键文件
   ```

4. **更新本文档**
   - 如果发现新的目录结构变化，更新本文档的相应章节
   - 更新废弃目录列表
   - 更新运行时数据列表

5. **执行同步**
   - 按本文档步骤执行同步
   - 如有新的废弃目录，先清理再同步

### 快速检查脚本

```bash
#!/bin/bash
# version-check.sh - 快速检查版本变化

echo "=== 检查工作区目录常量 ==="
grep -E "^[A-Z_]+_DIR\s*=" src/qwenpaw/constant.py

echo ""
echo "=== 检查迁移项 ==="
grep -A 10 "_WORKSPACE_ITEMS_TO_MIGRATE\s*=" src/qwenpaw/app/migration.py

echo ""
echo "=== 检查技能目录定义 ==="
grep -n "def get_.*skills.*dir\|SKILL_POOL\|skill_pool\|active_skills" \
  src/qwenpaw/agents/skills_manager.py | head -20

echo ""
echo "=== 检查工作区初始化 ==="
grep -n "mkdir\|\.json\|sessions\|memory\|file_store" \
  src/qwenpaw/app/workspace/workspace.py | head -30
```
