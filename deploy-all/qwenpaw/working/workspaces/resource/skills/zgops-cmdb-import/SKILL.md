---
name: zgops-cmdb-import
description: 用于处理CMDB 测试环境中的资源清单智能导入、资源纳管、批量导入预检查和入库确认。当用户明确表达导入资源清单、上传台账导入、资源纳管、批量导入 CMDB 时使用。
---

# CMDB 资源导入技能

凭证默认从共享路径 `working/secrets/zgops-cmdb.env` 读取，
该位置由所有 zgops-cmdb 系列 skill 共用，与本 skill 目录名解耦。
若需要为本 skill 单独覆盖，仍可在当前目录放 `.env`（优先级更高）。

解析顺序：
`$VEOPS_ENV_FILE` → `<skill_dir>/.env` → `$QWENPAW_WORKING_DIR/secrets/zgops-cmdb.env` → `~/.qwenpaw/secrets/zgops-cmdb.env` → `<repo>/deploy-all/qwenpaw/working/secrets/zgops-cmdb.env`

## 默认行为

- 优先使用 `scripts/resource_import_bridge.py`。
- 不要打开浏览器，不要引导用户去传统模板导入页面。
- 默认把导入看作一个多阶段确认任务，而不是一次性写入任务。
- 在用户确认前，不要执行创建分组、创建模型、写入 CI、写入关系。
- 如果用户要求查看系统完整拓扑，返回拓扑查询提示词，交给现有查询能力执行；如果当前没有明确应用名，提示查询能力在多应用场景下先要求用户指定应用，不要默认任选一个。

## 快速路径

```bash
python scripts/resource_import_bridge.py start
python scripts/resource_import_bridge.py metadata
python scripts/resource_import_bridge.py preview --context-file <json>
python scripts/resource_import_bridge.py import --context-file <json>
python scripts/resource_import_bridge.py topology-prompt
```

`preview` 的 `context-file` 结构：

```json
{
  "agentId": "query",
  "files": [
    {
      "name": "network-devices.xlsx",
      "path": "/absolute/path/network-devices.xlsx"
    }
  ]
}
```

`import` 的 `context-file` 结构：

```json
{
  "payload": {
    "preview": {},
    "resourceGroups": [],
    "relations": []
  }
}
```

## 工作流

1. `start`
   返回导入起始卡片文案和支持格式。
2. `metadata`
   返回当前 CMDB 的模型、属性、关系类型和分组元数据。
3. `preview`
   完成文件解析、LLM 字段映射、模型/分组匹配预检查、待确认项标记和关系预览。
4. `import`
   在用户确认后执行真实入库。
5. `topology-prompt`
   返回查看当前系统完整拓扑的提示词；若没有明确应用名，则要求查询侧先确认具体应用。

## 输出风格

- 默认返回阶段化结果，不直接倾倒完整原始 JSON。
- 优先展示当前阶段、待确认项、失败原因和导入结果。
- 如果存在无法自动确认的字段，用明确的待确认语义提示用户，而不是静默推测。

## 备注

- 这个 skill 只负责导入。
- 执行层入口在 `scripts/resource_import_bridge.py`。
- 运行时只依赖当前 skill 自己的 `.env` 和仓库内导入实现，不需要检查其他 skill 的目录结构。
