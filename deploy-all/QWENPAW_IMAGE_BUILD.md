# QwenPaw 通用镜像打包说明

本文档说明如何基于 [`qwenpaw/Dockerfile`](qwenpaw/Dockerfile) 构建**跨环境通用**的 QwenPaw 镜像。

## 核心原则

通用镜像只包含：

- QwenPaw 程序与离线运行依赖；
- 仓库维护的 Agent、Skill 和初始化模板；
- 构建期生成的无环境工作目录 seed。

通用镜像不包含：

- `deploy-all/qwenpaw/data/qwenpaw/` 运行时快照；
- `~/.qwenpaw` 中的设置数据库、知识库、会话和报告；
- 知识库数据库、上传文件、会话、缓存和环境专属服务数据。

> **模型配置例外**：按当前发布要求，`deploy-all/qwenpaw/data/qwenpaw.secret/` 会随镜像交付，使空的 `/app/working.secret` 在首次启动时获得 `.master_key`、Provider 配置和已选模型。镜像 tar 因而属于敏感密钥材料，必须按 Secret 保护，禁止提交到 Git、公开分发或上传到无访问控制的位置。

## 唯一维护源

受管的 Agent/Skill 维护在：

```text
deploy-all/qwenpaw/working/
├── config.json
├── universal-seed.json
└── workspaces/
    └── <agent-id>/
        ├── agent.json
        ├── skill.json
        └── skills/
```

其中：

- `workspaces/*/skills/` 是 Skill 代码唯一维护源；
- `skill.json` 决定 Skill 是否启用、适用渠道及配置元数据；
- `universal-seed.json` 声明废弃 Skill 和跨工作区复用的源码；
- 不再需要将 `working`、本机用户目录或 Skill 手工同步到 `deploy-all/qwenpaw/data/` 后再打包。

构建时，`scripts/build_universal_seed.py` 会将这些输入生成到镜像的：

```text
/app/share/qwenpaw-seed/
```

并完成：

1. 将本机 workspace 路径规范化为 `/app/working/workspaces/<agent-id>`；
2. 根据 manifest 物化缺失的 builtin Skill；
3. 仅过滤真实 `.env`、明确的凭据字段和生成缓存；`working` 中维护的其他文件都会保留；
4. 生成空的 `jobs.json` 与 seed 内容哈希；
5. 拒绝没有受管源码的有效 Skill，避免隐性依赖 data 快照。

## 打包前检查

打包前只需维护并检查 repository source：

```bash
python3 deploy-all/qwenpaw/scripts/build_universal_seed.py \
  --source deploy-all/qwenpaw/working \
  --builtin-root src/qwenpaw/agents/skills \
  --output /tmp/qwenpaw-universal-seed \
  --runtime-working-dir /app/working
```

成功后可以检查输出内容：

```bash
find /tmp/qwenpaw-universal-seed -type f | sort
```

临时目录可在检查后删除。该命令不会读取或改写 `~/.qwenpaw`、`data/` 或任何运行环境。

## 构建镜像

在仓库根目录执行：

```bash
docker build -f deploy-all/qwenpaw/Dockerfile -t qwenpaw:latest .
```

按架构构建时使用现有脚本：

```bash
cd deploy-all/qwenpaw && ./build-amd64.sh
```

```bash
cd deploy-all/qwenpaw && ./build-arm64.sh
```

同一版本的 amd64 与 arm64 镜像必须使用相同镜像 tag；导出的 tar 文件名可用架构区分。

## 首次运行行为

容器发现工作目录为空时，会把 `/app/share/qwenpaw-seed/` 初始化到运行时工作目录。随后 QwenPaw 会按既有机制创建内置 `skill_pool`、默认 Agent 和 QA Agent。

镜像会在 `/app/working.secret` 为空时恢复随镜像交付的 Provider 配置，但不会覆盖非空 secret 目录。当前 `working` 不维护运行时数据库、会话或知识库上传文件，因此这些内容不会由镜像恢复；若未来将某个文件明确纳入 `working`，它会随 seed 交付。

## 运行时数据与环境迁移

[`SYNC_GUIDE.md`](SYNC_GUIDE.md) 仅用于理解或迁移某个环境的运行时数据；它不是通用镜像构建步骤。运行时数据库、知识库文件和环境专属业务数据不得重新烘焙进通用镜像；当前唯一明确例外是受保护的 `qwenpaw.secret` 模型配置。
