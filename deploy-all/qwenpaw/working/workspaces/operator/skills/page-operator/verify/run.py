#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""操作模式前端执行器自测的运行器。

前端模块(action.js / operator/*.js)住在 inoe-ui 工程里、用无扩展名的相对
import(webpack 习惯),Node ESM 不能直接跑。本脚本把它们拷进 ``_fe/`` 并补上
``.js`` 扩展名,然后用 node 跑 ``executor_selftest.mjs``,跑完清理。

用法:
    python3 verify/run.py [--fe <inoe-ui>/packages/inoe-ui/src] [--node <node 路径>]

找不到前端工程或 node 时打印 SKIP 并以 0 退出(不算失败)。
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path


HERE = Path(__file__).resolve().parent
CHAT_REL = Path("layout/components/chatDialog")
MODULES = [
    "action.js",
    "operator/operableBus.js",
    "operator/operableMixin.js",
    "operator/cursor.js",
    "operator/runner.js",
    "operator/pageSchema.js",
    "operator/pageMap.js",
]

_IMPORT_RE = re.compile(r"(from\s+['\"])(\.[^'\"]+?)(['\"])")


def _fix_imports(text: str) -> str:
    def repl(m):
        spec = m.group(2)
        if not spec.endswith(".js"):
            spec += ".js"
        return m.group(1) + spec + m.group(3)

    return _IMPORT_RE.sub(repl, text)


def _guess_fe() -> Path | None:
    env = os.getenv("INOE_UI_SRC", "").strip()
    cands = []
    if env:
        cands.append(Path(env))
    cands.append(
        Path("D:/work/projects/web/inoe-ui-monorepo/packages/inoe-ui/src")
    )
    for c in cands:
        if (c / CHAT_REL / "action.js").is_file():
            return c
    return None


def _guess_node() -> str | None:
    env = os.getenv("NODE_BIN", "").strip()
    cands = [env] if env else []
    cands += [
        shutil.which("node") or "",
        "D:/work/environment/web/nodejs/node.exe",
    ]
    for c in cands:
        if c and Path(c).exists():
            return c
    return None


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="前端执行器自测运行器")
    parser.add_argument("--fe", default=None, help="inoe-ui 的 src 目录")
    parser.add_argument("--node", default=None, help="node 可执行文件")
    args = parser.parse_args(argv)

    fe = Path(args.fe) if args.fe else _guess_fe()
    node = args.node or _guess_node()
    if fe is None or not (fe / CHAT_REL / "action.js").is_file():
        print("SKIP: 未找到 inoe-ui 前端工程(设 INOE_UI_SRC 或 --fe)")
        return 0
    if not node:
        print("SKIP: 未找到 node(设 NODE_BIN 或 --node)")
        return 0

    src = fe / CHAT_REL
    dst = HERE / "_fe"
    if dst.exists():
        shutil.rmtree(dst)
    (dst / "operator").mkdir(parents=True, exist_ok=True)
    try:
        for rel in MODULES:
            text = (src / rel).read_text(encoding="utf-8")
            (dst / rel).write_text(_fix_imports(text), encoding="utf-8")
        proc = subprocess.run(
            [node, "executor_selftest.mjs"],
            cwd=str(HERE),
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        sys.stdout.write(proc.stdout)
        if proc.stderr:
            sys.stderr.write(proc.stderr)
        return proc.returncode
    finally:
        shutil.rmtree(dst, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
