"""Synthetic gold documents for the knowledge-base eval harness.

Built in-memory so no binary blobs are committed. Covers the multimodal
ingestion paths that the P0/P1 work added: Markdown structure, and a .docx with
heading + paragraph + table (table cell text must survive into retrieval).
"""
from __future__ import annotations

import io
import zipfile

_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_A = "http://schemas.openxmlformats.org/drawingml/2006/main"


GATEWAY_RUNBOOK_MD = """# 网关告警处置手册

## 概述
本手册描述 INOE 网关常见告警的处置流程。网关默认监听端口为 8443。

## 告警分级
P0 告警需在 15 分钟内响应。P1 告警需在 1 小时内响应。

## 数据库连接告警
当出现“数据库连接池耗尽”告警时，先检查活跃连接数是否超过 200。
处置办法是重启连接池并扩容到 400。
"""

ONBOARD_FAQ_MD = """# 新员工常见问题

## 如何申请 VPN
提交工单到 IT 服务台，选择“网络接入”类目，审批通过后 1 个工作日内开通。

## 报销周期
每月 25 日为报销截止日，次月 10 日发放。
"""


def _docx_document_xml() -> str:
    return f"""<?xml version="1.0"?>
<w:document xmlns:w="{_W}" xmlns:r="{_R}" xmlns:a="{_A}">
 <w:body>
  <w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr>
       <w:r><w:t>季度运维指标报告</w:t></w:r></w:p>
  <w:p><w:r><w:t>本季度服务整体可用性达标，告警总量同比下降。</w:t></w:r></w:p>
  <w:p><w:pPr><w:pStyle w:val="Heading2"/></w:pPr>
       <w:r><w:t>核心指标</w:t></w:r></w:p>
  <w:tbl>
   <w:tr><w:tc><w:p><w:r><w:t>指标</w:t></w:r></w:p></w:tc>
         <w:tc><w:p><w:r><w:t>数值</w:t></w:r></w:p></w:tc></w:tr>
   <w:tr><w:tc><w:p><w:r><w:t>工单总数</w:t></w:r></w:p></w:tc>
         <w:tc><w:p><w:r><w:t>2299</w:t></w:r></w:p></w:tc></w:tr>
   <w:tr><w:tc><w:p><w:r><w:t>平均处理时长</w:t></w:r></w:p></w:tc>
         <w:tc><w:p><w:r><w:t>3.7 小时</w:t></w:r></w:p></w:tc></w:tr>
  </w:tbl>
 </w:body>
</w:document>"""


def metrics_report_docx() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("word/document.xml", _docx_document_xml())
    return buf.getvalue()


def gold_documents() -> list[tuple[str, bytes]]:
    """(filename, content_bytes) pairs to ingest for the retrieval eval."""
    return [
        ("gateway_runbook.md", GATEWAY_RUNBOOK_MD.encode("utf-8")),
        ("onboarding_faq.md", ONBOARD_FAQ_MD.encode("utf-8")),
        ("metrics_report.docx", metrics_report_docx()),
    ]
