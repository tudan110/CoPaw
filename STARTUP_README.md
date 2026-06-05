# QwenPaw 启动脚本说明

## 概述

本项目提供多个常用脚本，分别用于启动 QwenPaw 主应用、同步本地工作目录，以及启动 Portal 前端开发服务器。

---

## start-qwenpaw.sh - QwenPaw 主应用启动脚本

### 功能说明

自动完成环境准备和应用启动，包括：
- 安装并配置 `uv`（Python 包管理工具）
- 创建 Python 虚拟环境
- 安装项目依赖
- 构建前端资源
- 初始化配置文件
- 启动 QwenPaw 应用

### 使用方法

```bash
# 基本启动
./start-qwenpaw.sh

# 强制重新构建前端
./start-qwenpaw.sh --rebuild

# 传递参数给后端启动命令
./start-qwenpaw.sh [任意参数]
```

### 参数说明

| 参数 | 说明 |
|------|------|
| `--rebuild` | 强制重新构建前端资源（删除旧的构建产物后重新构建） |
| 其他参数 | 默认传递给 `qwenpaw.extensions.runtime.worker_app`；使用 `--reload` 时传递给 `qwenpaw app` |

### 前置要求

- **Python 3.x**：运行环境
- **Node.js**（可选）：用于构建前端，如未安装会跳过前端构建
- **pnpm/npm**（可选）：前端构建工具，优先使用 pnpm

### 执行步骤

1. **检查并安装 uv**：如果未安装 uv，自动下载并安装
2. **创建虚拟环境**：在项目根目录创建 `.venv` 目录
3. **安装依赖**：使用 uv 安装项目开发依赖
4. **构建前端**：在 `console` 目录构建前端资源（如需要）
5. **初始化配置**：创建 `~/.qwenpaw/config.json` 配置文件（如不存在）
6. **启动应用**：默认运行 `qwenpaw.extensions.runtime.worker_app`，以支持多 worker；使用 `--reload` 时回退到 `qwenpaw app`

### 注意事项

- 首次运行会自动安装 uv 和创建虚拟环境
- 前端构建产物位于 `console/dist` 目录
- 配置文件位于 `~/.qwenpaw/config.json`
- 默认后端 worker 数为 `2`，可通过 `QWENPAW_APP_WORKERS` 或 `--workers` 覆盖；如需强制使用原始 `qwenpaw app`，设置 `QWENPAW_START_USE_WORKER_APP=false`

---

## sync-qwenpaw-working.sh - 同步工作目录脚本

### 功能说明

将仓库内的 `deploy-all/qwenpaw/working/` 内容同步到本地工作目录，默认目标为 `~/.qwenpaw/`。

默认行为会**覆盖同名文件**，但会**保留目标目录中额外存在的文件**；如需严格镜像，可使用 `--delete`。

### 使用方法

```bash
# 同步到默认目录 ~/.qwenpaw
./sync-qwenpaw-working.sh

# 严格镜像（删除目标目录中多余文件）
./sync-qwenpaw-working.sh --delete

# 同步到自定义目录
./sync-qwenpaw-working.sh /tmp/qwenpaw-working
```

### 参数说明

| 参数 | 说明 |
|------|------|
| `--delete` | 删除目标目录中源目录不存在的文件，执行严格镜像 |
| `target_dir` | 可选，自定义目标目录；默认值为 `~/.qwenpaw/` |

### 说明

- 默认目标目录也可通过环境变量 `QWENPAW_WORKING_DIR` 覆盖
- 同步依赖系统已安装 `rsync`

---

## start-portal.sh - Portal 前端启动脚本

### 功能说明

启动 Portal 前端开发服务器，用于开发和调试。

### 使用方法

```bash
# 基本启动（默认端口 5173）
./start-portal.sh

# 指定端口启动
PORT=3000 ./start-portal.sh

# 自定义 Portal 展示名称
VITE_PORTAL_APP_TITLE="数字员工门户" ./start-portal.sh
```

### 参数说明

| 环境变量 | 默认值 | 说明 |
|----------|--------|------|
| `PORT` | 5173 | 开发服务器监听端口 |
| `VITE_PORTAL_APP_TITLE` | `数字员工门户` | Portal 页面展示名称 |

### 前置要求

- **pnpm**：必须安装，用于依赖管理和启动开发服务器

### 执行步骤

1. **检查 pnpm**：验证 pnpm 是否已安装
2. **检查 portal 目录**：验证 portal 目录是否存在
3. **安装依赖**：运行 `pnpm install` 安装依赖
4. **启动开发服务器**：运行 `pnpm dev` 启动服务

### 访问地址

启动后可通过以下地址访问：
- 本地：`http://localhost:{PORT}`
- 局域网：`http://0.0.0.0:{PORT}`

---

## 快速开始

### 首次启动 QwenPaw 主应用

```bash
./start-qwenpaw.sh
```

### 同步本地工作目录

会同步本地开发的技能，需要在 qwenpaw 里面点击“从磁盘刷新技能”按钮

```bash
./sync-qwenpaw-working.sh
```

### 开发 Portal 前端

```bash
./start-portal.sh
```

### 重新构建前端

```bash
./start-qwenpaw.sh --rebuild
```

---

## 常见问题

### 1. uv 安装失败

手动安装 uv：
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### 2. 前端构建失败

确保已安装 Node.js 和 pnpm：
```bash
# 安装 Node.js (推荐使用 nvm)
nvm install --lts

# 安装 pnpm
npm install -g pnpm
```

### 3. Portal 启动失败

确认 pnpm 已安装：
```bash
pnpm --version
```

如未安装：
```bash
npm install -g pnpm
```

### 4. 端口被占用

修改 Portal 端口：
```bash
PORT=3000 ./start-portal.sh
```
