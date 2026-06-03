#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import threading
from pathlib import Path
from typing import Any


def _ensure_qwenpaw_importable() -> None:
    """Make ``qwenpaw`` importable across deploy modes.

    1. Already installed (wheel / ``pip install -e .``) → no-op.
    2. Running from a repo checkout (``deploy-all/...`` path) → walk up to
       the checkout root (has ``pyproject.toml`` + ``src/qwenpaw/``) and add
       ``src/`` to ``sys.path``.
    3. Synced into ``~/.qwenpaw/`` with no install → fail loudly with a
       fixable message instead of crashing on a stale ``_repo_root`` walk.
    """
    try:
        import qwenpaw  # noqa: F401
        return
    except ImportError:
        pass
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (
            (parent / "pyproject.toml").exists()
            and (parent / "src" / "qwenpaw").is_dir()
        ):
            sys.path.insert(0, str(parent / "src"))
            return
    raise RuntimeError(
        "无法导入 qwenpaw 包：脚本运行环境里没有安装 qwenpaw，"
        "也找不到源码 checkout。请在仓库根执行 "
        "`pip install -e .` 或确保部署 wheel 已安装。\n"
        f"当前脚本路径：{current}"
    )


_ensure_qwenpaw_importable()

SKILL_ROOT = Path(__file__).resolve().parents[1]

from qwenpaw.extensions.integrations.zgops_cmdb.resource_import import (  # noqa: E402
    import_preview_to_cmdb,
    load_resource_import_metadata,
    parse_uploaded_file,
    preview_resource_import,
    resolve_resource_import_runtime,
)


def _load_context(path: str | None) -> dict[str, Any]:
    if not path:
        return {}
    return json.loads(Path(path).read_text(encoding="utf-8"))


class ProgressReporter:
    def __init__(self, path: str | None):
        self.path = Path(path) if path else None
        self._lock = threading.Lock()

    def emit(self, payload: dict[str, Any]) -> None:
        if not self.path:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def _start_payload() -> dict[str, Any]:
    metadata = load_resource_import_metadata()
    return {
        "copyBlocks": [
            {
                "title": "资源导入入口已准备好",
                "paragraphs": [
                    "请在下方上传资源清单文件，我会先解析字段、清洗数据并生成预览，确认无误后再导入 CMDB。",
                ],
            },
            {
                "title": "我能处理的各种资料：",
                "items": [
                    "资源实例：服务器、虚拟机、容器、Kubernetes 节点、数据库、中间件、Nginx / Apache、网络设备。",
                    "业务对象：产品、应用、服务、平台、负责人、环境、所属部门。",
                    "网络与机房：IP 地址、子网、VLAN、机柜、机房、交换机端口。",
                    "资源关系：服务器属于哪个应用、应用属于哪个产品、IP 与设备绑定、上下游依赖关系。",
                ],
            },
            {
                "title": "建议清单中包含的字段：",
                "items": [
                    "基础字段：名称、资源类型、IP、环境、状态、所属应用或产品。",
                    "可选字段：厂商、型号、序列号、系统版本、负责人、机房、机柜、备注。",
                    "关系字段：应用名、产品名、父级资源、关联 IP、依赖服务。",
                ],
            },
            {
                "title": "导入前会自动处理：",
                "items": [
                    "识别 Excel/CSV 表头并映射到 CMDB 字段。",
                    "清洗名称、IP、状态、类型等不统一的数据。",
                    "按命名、网段、应用字段推断资源拓扑关系。",
                    "生成可编辑预览，确认后才会写入 CMDB。",
                ],
            },
            {
                "title": "导入流程：",
                "ordered": True,
                "items": [
                    "上传资源清单文件。",
                    "AI 解析字段并清洗数据。",
                    "确认资源和关系预览。",
                    "查看推断拓扑。",
                    "确认导入 CMDB。",
                ],
            },
            {
                "title": "支持的文件：",
                "paragraphs": [
                    "Excel / CSV 资源台账优先支持。",
                    "Word 文档、拓扑图片可上传，系统会尽量抽取结构化信息。",
                    "可以一次上传多个客户或多个系统的清单，进入预览后再筛选。",
                    f"支持格式：{'、'.join(metadata.get('supportedFormats') or ['Excel', 'CSV', 'Word', '图片'])}",
                ],
            },
        ],
        "supportedFormats": metadata.get("supportedFormats") or [],
        "startPrompt": "导入资源清单",
        "topologyPrompt": "请查询当前系统的应用关系拓扑，并用 echarts 树状图展示。若系统中存在多个应用而我没有明确指定应用名，请先列出候选应用并要求我明确选择，不要默认任选一个。",
    }


async def _preview(context: dict[str, Any]) -> dict[str, Any]:
    files = context.get("files") or []
    if not isinstance(files, list) or not files:
        raise ValueError("files is required")

    reporter = ProgressReporter(str(context.get("progressFile") or "").strip() or None)
    reporter.emit({
        "stage": "queued",
        "message": "已接收导入任务，正在准备解析环境",
        "percent": 2,
    })
    metadata = load_resource_import_metadata()
    reporter.emit({
        "stage": "metadata",
        "message": "已加载 CMDB 元数据，开始准备智能解析",
        "percent": 5,
    })
    agent_id = str(context.get("agentId") or "").strip() or None
    runtime = await resolve_resource_import_runtime(agent_id)
    llm_client = runtime.client
    reporter.emit({
        "stage": "runtime",
        "message": f"已选择解析引擎：{runtime.source}",
        "percent": 6,
    })
    parsed_files = []
    try:
        for item in files:
            if not isinstance(item, dict):
                continue
            filename = str(item.get("name") or "unnamed")
            file_path = Path(str(item.get("path") or ""))
            if not file_path.exists():
                raise FileNotFoundError(f"预览文件不存在: {file_path}")
            parsed_files.append(
                await parse_uploaded_file(
                    filename,
                    file_path.read_bytes(),
                    llm_client=llm_client,
                    progress_callback=reporter.emit,
                )
            )
        result = await preview_resource_import(
            parsed_files,
            metadata,
            llm_client=llm_client,
            runtime_source=runtime.source,
            progress_callback=reporter.emit,
        )
        reporter.emit({
            "stage": "completed",
            "message": "智能解析完成，已生成待确认预览结果",
            "percent": 100,
        })
        return result
    except Exception as exc:
        reporter.emit({
            "stage": "failed",
            "message": f"智能解析失败：{exc}",
            "percent": 100,
        })
        raise
    finally:
        if llm_client:
            await llm_client.aclose()


def main() -> int:
    parser = argparse.ArgumentParser(description="ZGOPS CMDB 资源导入桥接脚本")
    parser.add_argument(
        "command",
        choices=["start", "metadata", "preview", "import", "topology-prompt"],
    )
    parser.add_argument("--context-file")
    args = parser.parse_args()

    context = _load_context(args.context_file)

    if args.command == "start":
        result = _start_payload()
    elif args.command == "metadata":
        result = load_resource_import_metadata()
    elif args.command == "preview":
        result = asyncio.run(_preview(context))
    elif args.command == "import":
        result = import_preview_to_cmdb(context.get("payload") or {})
    else:
        result = {"prompt": _start_payload().get("topologyPrompt")}

    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
