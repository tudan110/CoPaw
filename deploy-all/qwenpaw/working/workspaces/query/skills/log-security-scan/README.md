# log-security-scan

夜莺（n9e）业务日志的敏感信息与攻击征兆扫描 skill：基于 YAML 规则库 + 正则匹配 + Luhn 等 post_filter，命中样例**必经脱敏**。

挂在 `query` 工作区下，与 `nightingale-log`（关键字检索）、`log-hazard-detection`（隐患识别 / 聚类）并列。

更多说明见同目录 `SKILL.md`。规则文件：`references/security_rules.yml`。
