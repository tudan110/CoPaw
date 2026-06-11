---
name: report-export
description: 当用户要求“生成报告”“导出报告”“生成巡检报告”“生成告警分析报告”“生成运维报表”等可下载的报告类交付物时使用此技能。它把基于会话上下文撰写的报告文件归档到统一下载目录，并生成可点击下载的链接。默认生成 Markdown 格式；用户明确要求 PDF / Word / Excel / PPT 时，先用对应的 pdf / docx / xlsx / pptx 技能生成文件，再用本技能归档。
---

# 报告导出与下载

把报告文件归档到平台统一的下载目录（`<working_dir>/extensions/reports/<agent_id>/`），
并输出 portal 可渲染成下载按钮的 markdown 链接。

## 工作流程

1. **撰写报告内容**（基于当前会话上下文，不要凭空编造数据）：
   - 默认格式 **Markdown**：把报告内容写入当前目录的临时文件，如 `./_report_tmp.md`
   - 用户要 PDF → 用 **pdf** 技能生成 `.pdf` 文件
   - 用户要 Word → 用 **docx** 技能生成 `.docx` 文件
   - 用户要 Excel 报表 → 用 **xlsx** 技能生成 `.xlsx` 文件
   - 用户要 PPT → 用 **pptx** 技能生成 `.pptx` 文件
2. **归档**（在工作区目录下执行；`{this_skill_dir}` 指本技能目录）：

   ```bash
   python {this_skill_dir}/scripts/save_report.py <生成的文件路径> --title <报告主题>
   ```

3. **回复用户**：脚本最后会输出一行 `[下载报告：...](...)` 形式的 markdown
   下载链接，**必须把这一行原样包含在给用户的回复中**，portal 会把它渲染成
   下载按钮。

## 注意

- `--title` 用简短中文主题词（如 `数据库巡检报告`），不要带路径、斜杠或扩展名。
- 不要自己拼下载链接，一律以脚本输出为准。
- 脚本默认把源文件移动到归档目录；如需保留源文件加 `--copy`。
- 支持的格式：`.md` `.pdf` `.docx` `.xlsx` `.pptx`，其余格式脚本会拒绝。
