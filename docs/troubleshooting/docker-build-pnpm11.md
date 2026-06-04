# Docker 构建失败：pnpm 11 兼容性问题

> 发生时间：2026-06-04
> 影响项目：digital-workforce-portal
> Dockerfile：`deploy-all/portal/Dockerfile`

---

## 问题现象

Docker 构建在 `pnpm install --frozen-lockfile` 步骤失败，历经三次不同报错。

---

## 问题 1：Node.js 版本过低导致 `node:sqlite` 缺失

### 报错信息

```
Error [ERR_UNKNOWN_BUILTIN_MODULE]: No such built-in module: node:sqlite
```

### 原因

- Dockerfile 基础镜像为 `node:20-alpine`（Node.js v20.20.2）
- `corepack prepare pnpm@11` 安装了 pnpm 11.5.1
- pnpm 11 要求 **Node.js ≥ 22.13**，且内部依赖了 `node:sqlite` 模块
- `node:sqlite` 从 **Node.js 22.5.0** 才开始内置，Node 20 没有该模块

### 修复

```dockerfile
# 改前
FROM node:20-alpine AS builder

# 改后
FROM node:22-alpine AS builder
```

---

## 问题 2：`package.json` 中的 `pnpm.onlyBuiltDependencies` 已废弃

### 报错信息

```
[WARN] The "pnpm" field in package.json is no longer read by pnpm.
The following keys were ignored: "pnpm.onlyBuiltDependencies".
```

### 原因

- pnpm 11 不再读取 `package.json` 中的 `pnpm.onlyBuiltDependencies` 字段
- 该配置已迁移至 `.npmrc`，但项目中 `pnpm-workspace.yaml` 已有 `allowBuilds` 配置可替代
- `.npmrc` 中的 `onlyBuiltDependencies` 与 `pnpm-workspace.yaml` 中的 `allowBuilds` 功能重叠，保留后者即可

### 修复

1. 删除 `package.json` 中的 `pnpm` 字段
2. 不再需要单独创建 `.npmrc`

```jsonc
// package.json — 删除以下内容
{
  "pnpm": {
    "onlyBuiltDependencies": ["esbuild"]
  }
}
```

---

## 问题 3：`pnpm-workspace.yaml` 未复制进容器导致构建脚本审批缺失

### 报错信息

```
[ERR_PNPM_IGNORED_BUILDS] Ignored build scripts: esbuild@0.25.12
Run "pnpm approve-builds" to pick which dependencies should be allowed to run scripts.
```

### 原因

- pnpm 11 的构建审批机制从 `pnpm-workspace.yaml` 读取 `allowBuilds` 配置
- 项目中 `pnpm-workspace.yaml` 已正确声明：

  ```yaml
  allowBuilds:
    esbuild: true
  ```

- 但 Dockerfile 的 COPY 步骤只复制了 `package.json` 和 `pnpm-lock.yaml`，**没有复制 `pnpm-workspace.yaml`**
- 容器内缺少该文件 → pnpm 找不到审批配置 → 拒绝执行 esbuild 的 postinstall 脚本

### 修复

```dockerfile
# 改前
COPY portal/package.json portal/pnpm-lock.yaml ./

# 改后
COPY portal/package.json portal/pnpm-lock.yaml portal/pnpm-workspace.yaml ./
```

---

## 最终 Dockerfile 改动汇总

```diff
- FROM node:20-alpine AS builder
+ FROM node:22-alpine AS builder

- COPY portal/package.json portal/pnpm-lock.yaml ./
+ COPY portal/package.json portal/pnpm-lock.yaml portal/pnpm-workspace.yaml ./
```

## 知识点：pnpm 11 构建脚本审批机制

pnpm 11 引入了安全机制，默认禁止第三方依赖包在安装时执行脚本（如 postinstall）。相关配置：

| 配置项 | 所在文件 | 作用 |
|--------|----------|------|
| `onlyBuiltDependencies` | `.npmrc` | 限制**哪些包可以拥有**构建脚本（安全限制） |
| `allowBuilds` | `pnpm-workspace.yaml` | **批准执行**这些构建脚本（审批放行） |

两者区别：

- `onlyBuiltDependencies` — 白名单，未列入的包即使有构建脚本也不会被扫描
- `allowBuilds` — 执行许可，批准后构建脚本才会实际运行

两者配合使用更安全，但如果只需要解决 `ERR_PNPM_IGNORED_BUILDS` 报错，`allowBuilds` 是必须的，`onlyBuiltDependencies` 可选。
