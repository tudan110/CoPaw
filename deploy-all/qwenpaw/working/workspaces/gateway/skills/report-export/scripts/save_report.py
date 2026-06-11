#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把生成好的报告文件归档到平台统一下载目录，并输出下载链接。

归档位置: <working_dir>/extensions/reports/<agent_id>/
文件命名: YYYYMMDD-HHMM-<主题>.<原扩展名>

agent_id / working_dir 默认从当前工作目录推导（智能体执行 shell 时
cwd 即其工作区目录 .../workspaces/<agent_id>），也可用参数显式指定。

用法:
    python save_report.py ./_report_tmp.md --title 数据库巡检报告
    python save_report.py ./out.pdf --title 月度告警报表 --copy
"""
from __future__ import annotations

import argparse
import datetime
import os
import re
import shutil
import sys
from pathlib import Path
from urllib.parse import quote

ALLOWED_SUFFIXES = {".md", ".pdf", ".docx", ".xlsx", ".pptx"}


def _derive_from_cwd() -> tuple[Path | None, str | None]:
    """从 cwd (.../workspaces/<agent_id>/...) 推导 working_dir 和 agent_id."""
    parts = Path.cwd().resolve().parts
    if "workspaces" not in parts:
        return None, None
    idx = parts.index("workspaces")
    working_dir = Path(*parts[:idx]) if idx > 0 else None
    agent_id = parts[idx + 1] if len(parts) > idx + 1 else None
    return working_dir, agent_id


def _resolve_working_dir(explicit: str | None) -> Path:
    if explicit:
        return Path(explicit).expanduser().resolve()
    env = os.environ.get("QWENPAW_WORKING_DIR") or os.environ.get(
        "COPAW_WORKING_DIR"
    )
    if env:
        return Path(env).expanduser().resolve()
    derived, _ = _derive_from_cwd()
    if derived:
        return derived
    for candidate in (Path.home() / ".qwenpaw", Path.home() / ".copaw"):
        if candidate.is_dir():
            return candidate
    sys.exit("错误: 无法确定 working_dir，请用 --working-dir 显式指定")


def _resolve_agent_id(explicit: str | None) -> str:
    if explicit:
        return explicit
    _, derived = _derive_from_cwd()
    if derived:
        return derived
    sys.exit(
        "错误: 无法从当前目录推导 agent_id（不在 workspaces/<agent_id> 下），"
        "请用 --agent-id 显式指定"
    )


def _slugify(title: str, fallback: str) -> str:
    cleaned = re.sub(r"[\\/\s]+", "-", (title or "").strip())
    cleaned = re.sub(r"[^\w一-鿿-]", "", cleaned).strip("-")
    return cleaned or fallback


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", help="已生成的报告文件路径")
    parser.add_argument("--title", default="", help="报告主题（用于命名与链接文案）")
    parser.add_argument("--agent-id", default="", help="显式指定 agent_id")
    parser.add_argument("--working-dir", default="", help="显式指定 working_dir")
    parser.add_argument(
        "--copy", action="store_true", help="保留源文件（默认移动）"
    )
    args = parser.parse_args()

    source = Path(args.source).expanduser().resolve()
    if not source.is_file():
        sys.exit(f"错误: 源文件不存在: {source}")
    suffix = source.suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        sys.exit(
            f"错误: 不支持的报告格式 {suffix or '(无扩展名)'}，"
            f"支持: {' '.join(sorted(ALLOWED_SUFFIXES))}"
        )

    working_dir = _resolve_working_dir(args.working_dir or None)
    agent_id = _resolve_agent_id(args.agent_id or None)

    slug = _slugify(args.title, source.stem)
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M")
    reports_dir = working_dir / "extensions" / "reports" / agent_id
    reports_dir.mkdir(parents=True, exist_ok=True)

    target = reports_dir / f"{stamp}-{slug}{suffix}"
    counter = 2
    while target.exists():
        target = reports_dir / f"{stamp}-{slug}-{counter}{suffix}"
        counter += 1

    if args.copy:
        shutil.copy2(source, target)
    else:
        shutil.move(str(source), str(target))

    label = args.title.strip() or target.stem
    href = f"/api/portal/agents/{agent_id}/reports/{quote(target.name)}"
    print(f"已保存: {target}")
    print("请在回复中原样包含以下下载链接（portal 会渲染为下载按钮）:")
    print(f"[下载报告：{label}]({href})")


if __name__ == "__main__":
    main()
