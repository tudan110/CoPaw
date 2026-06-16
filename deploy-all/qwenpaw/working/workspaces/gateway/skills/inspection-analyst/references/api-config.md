# 巡检指标接口配置

该技能固定读取自己目录下的 `.env`，不要回退到别的技能目录。

## 最小配置

```bash
INOE_API_BASE_URL=http://82.156.83.38:30080
INOE_API_TOKEN=your_jwt_token_here
INSPECTION_METRIC_TIMEOUT_SECONDS=120
INSPECTION_METRIC_PAGE_SIZE=100
INSPECTION_NOTIFY_PUSH_URL=
INSPECTION_NOTIFY_DINGTALK_WEBHOOK_URL=
INSPECTION_NOTIFY_DINGTALK_SECRET=
INSPECTION_NOTIFY_FEISHU_WEBHOOK_URL=
INSPECTION_NOTIFY_FEISHU_SECRET=
INSPECTION_NOTIFY_TIMEOUT_SECONDS=8
INSPECTION_NOTIFY_MENTION_ALL=true
```

## 接口说明

| 接口 | 用途 |
|------|------|
| `getMetricDefinitions` | 查询资源类型的全部指标定义 |
| `getMetricData` | 批量查询指标值（queryKeys 传数组） |
| `/resource/inspection/config/list` | 查询指标对应的阈值规则 |
| `/admin/dict/data/list?dictType=verification_rules_new` | 字典解码 operator |

## 关键规则

- `INOE_API_BASE_URL` 与 `INOE_API_TOKEN` 必须配置，缺少 token 时必须明确报错
- `getMetricDefinitions` 与 `getMetricData` 共用同一个 base URL
- `operator` 不是直接可读文案，必须再查询字典做解码
- 命中规则配置时：**满足规则 = 正常，不满足规则 = 异常**
- 没有对应规则配置的指标：标注"需结合上下文由大模型判断"，不要伪造阈值
