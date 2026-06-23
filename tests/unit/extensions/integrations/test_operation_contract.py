# -*- coding: utf-8 -*-
"""跨仓库契约测试:后端 emit_action.py 产出的 ``qwenpaw:action`` 指令块,
必须能被前端 action.js 的正则解析出来。

后端(QwenPaw)发指令、前端(inoe-ui)收指令是两个仓库,契约一旦漂移就静默失效。
这里固化契约正则,跑真实 CLI 产出指令,断言能解析;若本机能找到前端 action.js,
额外断言它仍用同一条 fence 正则(防止任一侧改了格式而另一侧没跟上)。
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_REPO_ROOT = Path(__file__).resolve().parents[4]
_EMIT = (
    _REPO_ROOT
    / "deploy-all"
    / "qwenpaw"
    / "working"
    / "workspaces"
    / "operator"
    / "skills"
    / "page-operator"
    / "scripts"
    / "emit_action.py"
)

# 前后端共同约定的 fence 正则(与 action.js 的 ACTION_FENCE_RE 等价)。
CONTRACT_FENCE_RE = r"```qwenpaw:action\s*([\s\S]*?)```"


def _run_emit(*args: str) -> tuple[int, str]:
    proc = subprocess.run(
        # 契约测试不依赖 getRouters 网络反查,显式跳过
        [sys.executable, str(_EMIT), *args, "--no-resolve-route"],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return proc.returncode, proc.stdout


def test_emit_action_directive_matches_frontend_regex():
    code, out = _run_emit(
        "workflow.category.add",
        "--set",
        "categoryName=财务类",
        "--set",
        "code=FIN",
    )
    assert code == 0, f"emit_action 应成功,得到 {code}: {out}"
    m = re.search(CONTRACT_FENCE_RE, out)
    assert m, "前端契约正则应能从 CLI 输出里切出指令块"
    payload = json.loads(m.group(1).strip())
    assert payload["op"] == "workflow.category.add"
    assert payload["route"] and payload["page"]
    assert payload["params"] == {"categoryName": "财务类", "code": "FIN"}
    # 写操作的 submit 必须带回(前端高亮用),但执行器不得自动调用
    assert payload["submit"] == "submitForm"


def test_emit_action_always_emits_for_card_completion():
    # 卡片补全模式:匹配到即出指令——只给了 categoryName、没给 code 也照出,
    # 没给的字段由前端在聊天里弹卡片让用户补全(不再 exit 2 拦)。
    code, out = _run_emit(
        "workflow.category.add", "--set", "categoryName=财务类"
    )
    assert code == 0, "匹配到应直接出指令(不再因缺参退出码 2)"
    m = re.search(CONTRACT_FENCE_RE, out)
    assert m, "应产出指令块"
    payload = json.loads(m.group(1).strip())
    assert payload["op"] == "workflow.category.add"
    assert payload["params"].get("categoryName") == "财务类"
    assert "code" not in payload["params"]  # 没给的字段不编造,交前端补


def _find_action_js() -> Path | None:
    env = os.getenv("INOE_UI_SRC", "").strip()
    candidates = []
    if env:
        candidates.append(Path(env))
    candidates += [
        Path("D:/work/projects/web/inoe-ui-monorepo/packages/inoe-ui/src"),
    ]
    for src in candidates:
        f = src / "layout" / "components" / "chatDialog" / "action.js"
        if f.is_file():
            return f
    return None


def test_frontend_action_js_uses_same_fence():
    """漂移守卫:本机有前端工程时,确认 action.js 仍用同一条 fence。"""
    action_js = _find_action_js()
    if action_js is None:
        pytest.skip("未找到 inoe-ui action.js(设 INOE_UI_SRC 可启用本检查)")
    text = action_js.read_text(encoding="utf-8")
    assert "```qwenpaw:action" in text
    # action.js 用 /```qwenpaw:action\s*([\s\S]*?)```/ —— 关键片段应一致
    assert "qwenpaw:action\\s*([\\s\\S]*?)" in text or re.search(
        r"qwenpaw:action\\s\*\(\[\\s\\S\]\*\?\)", text
    )
