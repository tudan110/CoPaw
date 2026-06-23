#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""操作目录半自动扫描器:从 inoe-ui(若依范式)前端工程里抽取"新增"类操作候选,
供人工 review 后并入 catalog/operations.json。

若依 CRUD 页高度一致:`handleAdd()` 开弹窗 → `el-form ref="form"` 绑 `form.xxx`
→ `submitForm()` 校验后调 `addXxx()`。本脚本据此正则抽取每个页面的:组件 name、
弹窗标题(→操作名/意图词)、表单字段(prop/label/type/required)、新增接口 url。

**这是辅助工具,不是事实源**:产出的是"候选",route 留空(运行期由 getRouters 按
component 反查),字段/必填可能有漏,务必人工核对后再并入目录。

用法:
    python3 scripts/scan_catalog.py --src <inoe-ui>/packages/inoe-ui/src \
        [--out catalog/scanned.json] [--limit 0]

不传 --src 时按几个常见相对位置猜测。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        try:
            return path.read_text(encoding="gbk")
        except Exception:
            return ""


def _guess_src() -> Path | None:
    candidates = [
        Path("D:/work/projects/web/inoe-ui-monorepo/packages/inoe-ui/src"),
        Path.home() / "inoe-ui-monorepo" / "packages" / "inoe-ui" / "src",
        Path("../inoe-ui-monorepo/packages/inoe-ui/src"),
    ]
    for c in candidates:
        if (c / "views").is_dir():
            return c
    return None


def _component_id(views_root: Path, vue_file: Path) -> tuple[str, str]:
    """返回 (component, op_id)。component 如 workflow/category/index;
    op_id 如 workflow.category.add。"""
    rel = vue_file.relative_to(views_root).as_posix()
    comp = rel[:-4] if rel.endswith(".vue") else rel  # 去掉 .vue
    parts = comp.split("/")
    if parts and parts[-1] == "index":
        key = ".".join(parts[:-1]) or "index"
    else:
        key = ".".join(parts)
    return comp, f"{key}.add"


def _script_block(text: str) -> str:
    m = re.search(r"<script[^>]*>([\s\S]*?)</script>", text)
    return m.group(1) if m else text


def _component_name(script: str) -> str:
    m = re.search(r"\bname:\s*['\"]([A-Za-z0-9_\-]+)['\"]", script)
    return m.group(1) if m else ""


def _add_title(script: str) -> str:
    """从 handleAdd 里抽 `this.title = '添加xxx'`。"""
    m = re.search(r"handleAdd\s*\([^)]*\)\s*\{([\s\S]{0,400}?)\}", script)
    seg = m.group(1) if m else script
    t = re.search(r"title\s*=\s*['\"]([^'\"]+)['\"]", seg)
    return t.group(1).strip() if t else ""


def _intents(title: str, name: str) -> tuple[str, list[str]]:
    """由"添加xxx"标题推操作名与意图同义词。"""
    base = re.sub(r"^(添加|新增|新建|创建)\s*", "", title).strip()
    label = base or title or name
    op_name = f"新建{label}" if label else "新建"
    verbs = ["新建", "添加", "创建", "新增"]
    intents = [f"{v}{label}" for v in verbs] if label else []
    intents += [f"{v}一个{label}" for v in ("新建", "加")] if label else []
    # 去重保序
    seen: set[str] = set()
    uniq = []
    for x in [op_name] + intents:
        if x and x not in seen:
            seen.add(x)
            uniq.append(x)
    return op_name, uniq


# 弹窗里(append-to-body 的新增/编辑表单)抽 el-form-item。
_FORM_ITEM_RE = re.compile(
    r"<el-form-item\b([^>]*?)\bprop=\"([^\"]+)\"([\s\S]*?)</el-form-item>",
    re.IGNORECASE,
)


def _fields(text: str, rules_props: set[str]) -> list[dict]:
    """抽取新增表单字段。只取出现在 :model=\"form\" 的 el-form 区域内的项;
    退化时取全文(过滤掉查询表单 queryParams 的项)。"""
    # 优先锁定绑定 form 的表单块(新增弹窗),排除 queryForm(queryParams)。
    blocks = re.findall(
        r"<el-form\b[^>]*:model=\"form\"[\s\S]*?</el-form>",
        text,
        re.IGNORECASE,
    )
    scope = "\n".join(blocks) if blocks else ""
    if not scope:
        return []
    out: list[dict] = []
    seen: set[str] = set()
    for attrs, prop, body in _FORM_ITEM_RE.findall(scope):
        if prop in seen:
            continue
        seen.add(prop)
        lab = re.search(r"label=\"([^\"]+)\"", attrs)
        label = lab.group(1) if lab else prop
        ftype = "input"
        if re.search(r"type=\"textarea\"", body):
            ftype = "textarea"
        elif re.search(r"<el-select\b", body):
            ftype = "select"
        elif re.search(r"<el-date-picker\b", body):
            ftype = "date"
        elif re.search(r"<el-switch\b", body):
            ftype = "switch"
        elif re.search(r"<el-radio", body):
            ftype = "radio"
        out.append(
            {
                "prop": prop,
                "label": label,
                "type": ftype,
                "required": prop in rules_props,
            }
        )
    return out


def _required_props(script: str) -> set[str]:
    """从 rules: { prop: [{ required: true }] } 抽必填字段。"""
    props: set[str] = set()
    m = re.search(r"rules\s*:\s*\{([\s\S]*?)\n\s{0,6}\}", script)
    seg = m.group(1) if m else script
    for pm in re.finditer(
        r"(\w+)\s*:\s*\[([\s\S]*?)\]", seg
    ):
        if "required: true" in pm.group(2) or "required:true" in pm.group(2):
            props.add(pm.group(1))
    return props


def _add_api(script: str, src: Path) -> dict:
    """找 add 接口 url:从 import 的 @/api/... 文件里找 addXxx 的 url。"""
    # import { ..., addXxx, ... } from '@/api/x/y'
    for im in re.finditer(
        r"import\s*\{([^}]*)\}\s*from\s*['\"]@/api/([^'\"]+)['\"]", script
    ):
        names = [n.strip() for n in im.group(1).split(",")]
        add_names = [n for n in names if re.match(r"add[A-Z]", n)]
        if not add_names:
            continue
        api_file = src / "api" / (im.group(2) + ".js")
        if not api_file.is_file():
            continue
        api_text = _read(api_file)
        for an in add_names:
            fn = re.search(
                an + r"\s*\([\s\S]*?url:\s*['\"]([^'\"]+)['\"]"
                r"[\s\S]*?method:\s*['\"](\w+)['\"]",
                api_text,
            )
            if fn:
                return {"method": fn.group(2).lower(), "url": fn.group(1)}
    return {}


def scan_one(views_root: Path, src: Path, vue_file: Path) -> dict | None:
    text = _read(vue_file)
    if "handleAdd" not in text or "submitForm" not in text:
        return None  # 不是标准若依新增页
    script = _script_block(text)
    comp, op_id = _component_id(views_root, vue_file)
    name = _component_name(script)
    title = _add_title(script)
    op_name, intents = _intents(title, name)
    rules_props = _required_props(script)
    fields = _fields(text, rules_props)
    if not fields:
        return None  # 抽不到表单字段,跳过(留给人工)
    api = _add_api(script, src)
    return {
        "id": op_id,
        "name": op_name,
        "intent": intents,
        "menu": "",
        "component": comp,
        "page": name,
        "route": "",
        "action": "create",
        "open": "handleAdd",
        "model": "form",
        "submit": "submitForm",
        "fields": fields,
        "api": api,
        "risk": "create",
        "permission": "",
        "_source": vue_file.relative_to(views_root).as_posix(),
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="扫描若依前端生成操作目录候选")
    parser.add_argument("--src", default=None, help="inoe-ui 的 src 目录")
    parser.add_argument("--out", default=None, help="写入候选 JSON 的路径")
    parser.add_argument("--limit", type=int, default=0, help="最多扫多少个页面")
    args = parser.parse_args(argv)

    src = Path(args.src) if args.src else _guess_src()
    if not src or not (src / "views").is_dir():
        print(
            "[error] 找不到 inoe-ui src(传 --src <…>/packages/inoe-ui/src)",
            file=sys.stderr,
        )
        return 2
    views_root = src / "views"

    files = sorted(views_root.rglob("index.vue"))
    candidates: list[dict] = []
    scanned = 0
    for f in files:
        scanned += 1
        try:
            entry = scan_one(views_root, src, f)
        except Exception as exc:  # noqa: BLE001 - 单页失败不该中断整体
            print(f"[warn] 解析失败 {f}: {exc}", file=sys.stderr)
            entry = None
        if entry:
            candidates.append(entry)
        if args.limit and len(candidates) >= args.limit:
            break

    result = {
        "version": 1,
        "scanned_pages": scanned,
        "candidate_count": len(candidates),
        "operations": candidates,
    }
    payload = json.dumps(result, ensure_ascii=False, indent=2)
    if args.out:
        Path(args.out).write_text(payload, encoding="utf-8")
        print(
            f"扫描 {scanned} 个页面,抽到 {len(candidates)} 个新增操作候选 → "
            f"{args.out}(请人工 review 后并入 operations.json)"
        )
    else:
        print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
