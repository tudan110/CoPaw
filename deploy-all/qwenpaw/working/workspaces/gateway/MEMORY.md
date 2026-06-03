---
summary: "Agent 长期记忆"
read_when:
  - 手动引导工作区
---

## 工具与环境

### HTML 应用产物目录

AI 应用开发工作台生成的 HTML 文件存放位置：

- **根目录：** `~/.qwenpaw/extensions/app_artifacts/html/`
- **结构：** 每个 HTML 应用一个 hash 子目录，内含 `index.html`
- **查找命令：** `find ~/.qwenpaw/extensions/app_artifacts/html -name "index.html"`
- **不在工作区 `gateway/` 内**，而是在 QwenPaw 的扩展目录下

当用户说"修改之前的页面""改一下那个 HTML"时，先去上述目录找已有文件，而不是从零生成。

### 其他关键路径

- QwenPaw 根目录：`~/.qwenpaw/`
- 各 agent 工作区：`~/.qwenpaw/workspaces/<agent-id>/`
- Skill 脚本（跨 agent 调用用）：`~/.qwenpaw/workspaces/<agent-id>/skills/<skill-name>/scripts/`

## 用户偏好

（尚无记录）

## 核心决策与经验

（尚无记录）
