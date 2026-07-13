# Web Availability Monitor API Notes

## Base URL

默认地址：

```text
http://web-check-app:3101
```

## 主要接口

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/health` | 系统健康检查 |
| GET | `/api/dashboard` | 看板聚合数据 |
| GET | `/api/monitors` | 监测任务列表 |
| GET | `/api/monitors/{id}` | 监测任务详情 |
| POST | `/api/monitors` | 创建监测任务 |
| PUT | `/api/monitors/{id}` | 更新监测任务 |
| DELETE | `/api/monitors/{id}` | 删除监测任务 |
| POST | `/api/monitors/{id}/publish` | 发布任务定义 |
| POST | `/api/monitors/{id}/trigger` | 手工触发执行 |
| GET | `/api/monitors/{id}/runs` | 查询某个任务的运行历史 |
| GET | `/api/runs/{id}` | 查询单次执行详情 |
| DELETE | `/api/runs/{id}` | 删除单次执行记录 |
| POST | `/api/runs/batch-delete` | 批量删除执行记录 |
| POST | `/api/selector-helper` | 根据 URL 获取元素定位建议 |

## Monitor 核心字段

```json
{
  "id": "0acc0c24-393c-428e-8a31-b9c7c5e1ec07",
  "name": "网易163门户",
  "description": "网易163门户",
  "targetUrl": "https://www.163.com",
  "status": "enabled",
  "scheduleEnabled": true,
  "scheduleCron": "0 * * * *",
  "scheduleTimezone": "Asia/Shanghai",
  "draftDefinition": {
    "startUrl": "https://www.163.com",
    "steps": []
  },
  "publishedDefinition": {
    "startUrl": "https://www.163.com",
    "steps": []
  }
}
```

## Step 核心字段

```json
{
  "id": "step-001",
  "name": "检查文本",
  "actionType": "assertText",
  "enabled": true,
  "onFailure": "abort",
  "config": {
    "expectedText": "Example Domain"
  }
}
```

## 已确认 actionType

1. `goto`
2. `wait`
3. `assertText`
4. `assertElement`
5. `click`
6. `input`
7. `scroll`
8. `screenshot`

## Selector Helper 返回结构

```json
{
  "finalUrl": "https://example.com/",
  "pageTitle": "Example Domain",
  "snapshot": {
    "width": 1280,
    "height": 720,
    "imageUrl": "..."
  },
  "suggestions": [
    {
      "id": "selector-1",
      "label": "a role=link",
      "locator": {
        "type": "role",
        "value": "Learn more",
        "options": {
          "role": "link"
        }
      },
      "text": "Learn more",
      "role": "link",
      "bounds": {
        "x": 288,
        "y": 220,
        "width": 79,
        "height": 20
      }
    }
  ]
}
