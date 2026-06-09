# FDE 交付工作台 · 审查/编辑/安全扫描 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the FDE delivery workbench a full review/edit/scan station — render rich security findings, let operators edit staged skills (guided fields + raw files), and gate install behind a persisted, digest-bound human-review approval.

**Architecture:** Three change surfaces, all inside the internal delta (no upstream `src/qwenpaw/` core touched). (1) The workspace runtime `selfcheck.py::_scan()` is enriched to surface every `Finding` field. (2) The backend service `fde_workbench_service.py` gains content-digest, persisted review state in `_fde_meta.json`, frontmatter/`.env.example`/raw-file editing with path-safety, and a server-side install gate; `portal_backend.py` exposes 3 new routes. (3) The portal panel right column is redesigned to Layout A (status strip with two gate badges, 概览/代码/试跑 tabs, editable guided fields + code, sticky footer). Review validity is a *derived* check (`status==approved AND stored_digest==current_digest`) so any edit auto-invalidates approval with no extra writes.

**Tech Stack:** Python 3.10 / FastAPI / Pydantic / pytest (`asyncio_mode=auto`); React + Vite + hand-rolled `fde-*` CSS (no antd in this panel, no code-editor lib — `<textarea>`). Tests: `.venv/bin/python -m pytest`. Frontend check: `cd portal && pnpm build` (tsc typecheck).

**Spec:** `docs/superpowers/specs/2026-06-08-fde-review-edit-scan-design.md`

---

## File Structure

| File | Responsibility | Change |
| --- | --- | --- |
| `deploy-all/qwenpaw/working/workspaces/fde/skills/fde-onboarding/runtime/selfcheck.py` | self-check runtime (subprocess-reached) | enrich `_scan()` findings |
| `src/qwenpaw/extensions/api/fde_workbench_service.py` | FDE service logic | + digest/review/edit/path-safety/frontmatter; gate `install_staged_skill` |
| `src/qwenpaw/extensions/api/fde_workbench_models.py` | request models | +4 models |
| `src/qwenpaw/extensions/api/portal_backend.py` | FDE routes | +3 routes; GET detail carries review |
| `portal/src/api/fde.ts` | FDE API client | rich finding/review types + 3 methods |
| `portal/src/pages/digital-employee/SelfcheckReport.tsx` | **new** — render 体检报告 (rich findings) | create |
| `portal/src/pages/digital-employee/fdeWorkbenchPanel.tsx` | workbench panel | right-col → Layout A |
| `portal/src/pages/fde-workbench.css` | panel styles | + tabs/findings/gates/editor CSS |
| `tests/unit/extensions/api/test_fde_selfcheck_findings.py` | **new** — finding enrichment | create |
| `tests/unit/extensions/api/test_fde_staged_review.py` | **new** — digest + review lifecycle + gate | create |
| `tests/unit/extensions/api/test_fde_staged_edit.py` | **new** — frontmatter/env/path-safety/edit | create |
| `tests/unit/extensions/api/test_fde_workbench.py` | existing FDE tests | update install tests to approve first |

> ⚠️ Memory `project_extensions_test_flakiness`: FDE workbench tests are order-sensitive. Keep every new test in its own module, build staged skills under `tmp_path`, monkeypatch subprocess calls (`selfcheck_staged_skill`/`show_staged_skill`) in pure-logic tests, and never touch the real `~/.qwenpaw`.

---

## Phase 1 — 缺口B: enrich self-check findings

### Task 1.1: `_scan()` surfaces snippet/remediation/category/rule_id/description

**Files:**
- Modify: `deploy-all/qwenpaw/working/workspaces/fde/skills/fde-onboarding/runtime/selfcheck.py:40-49`
- Test: `tests/unit/extensions/api/test_fde_selfcheck_findings.py` (create)

- [ ] **Step 1: Write the failing test**

```python
# -*- coding: utf-8 -*-
"""缺口B：_scan() 必须把 Finding 的富字段透出给前端「体检报告」。"""
from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

REPO_ROOT = Path(__file__).resolve().parents[4]
SELFCHECK_PATH = (
    REPO_ROOT
    / "deploy-all/qwenpaw/working/workspaces/fde/skills"
    / "fde-onboarding/runtime/selfcheck.py"
)


def _load_selfcheck():
    spec = importlib.util.spec_from_file_location(
        "fde_selfcheck_under_test", SELFCHECK_PATH,
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_scan_surfaces_rich_finding_fields(monkeypatch, tmp_path):
    mod = _load_selfcheck()
    fake_finding = SimpleNamespace(
        severity=SimpleNamespace(value="medium"),
        title="疑似硬编码凭证",
        file_path="runtime/tool_adapters.py",
        line_number=42,
        snippet='token = "Bearer abc123"',
        remediation="移到 .env，用 os.environ[...] 读取",
        category=SimpleNamespace(value="hardcoded_secret"),
        rule_id="hardcoded_secrets",
        description="疑似把令牌写死在源码里",
    )
    fake_result = SimpleNamespace(
        findings=[fake_finding],
        is_safe=True,
        max_severity=SimpleNamespace(value="medium"),
    )
    monkeypatch.setattr(
        "qwenpaw.security.skill_scanner.scan_skill_directory",
        lambda *a, **k: fake_result,
    )
    out = mod._scan(tmp_path, "demo")
    f = out["findings"][0]
    assert f["severity"] == "medium"
    assert f["title"] == "疑似硬编码凭证"
    assert f["file"] == "runtime/tool_adapters.py"
    assert f["line"] == 42
    assert f["snippet"] == 'token = "Bearer abc123"'
    assert "os.environ" in f["remediation"]
    assert f["category"] == "hardcoded_secret"
    assert f["rule_id"] == "hardcoded_secrets"
    assert "令牌" in f["description"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/extensions/api/test_fde_selfcheck_findings.py -v`
Expected: FAIL with `KeyError: 'snippet'` (the field isn't surfaced yet).

- [ ] **Step 3: Enrich the finding dict in `_scan()`**

In `selfcheck.py`, replace the `findings.append({...})` block (lines 42-49) with:

```python
        findings.append(
            {
                "severity": getattr(
                    getattr(f, "severity", None),
                    "value",
                    str(getattr(f, "severity", "")),
                ),
                "title": getattr(f, "title", ""),
                "file": getattr(f, "file_path", ""),
                "line": getattr(f, "line_number", None),
                "snippet": getattr(f, "snippet", None),
                "remediation": getattr(f, "remediation", None),
                "category": getattr(
                    getattr(f, "category", None),
                    "value",
                    str(getattr(f, "category", "") or ""),
                ),
                "rule_id": getattr(f, "rule_id", ""),
                "description": getattr(f, "description", ""),
            }
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/extensions/api/test_fde_selfcheck_findings.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add deploy-all/qwenpaw/working/workspaces/fde/skills/fde-onboarding/runtime/selfcheck.py tests/unit/extensions/api/test_fde_selfcheck_findings.py
git commit -m "feat(fde): surface rich scan findings in selfcheck for the workbench report"
```

---

## Phase 2 — content digest + persisted review state

All in `fde_workbench_service.py`. Add `import hashlib` to the top-of-file imports (currently `json, os, re, subprocess, sys, tempfile`).

### Task 2.1: `_staged_content_digest`

**Files:**
- Modify: `src/qwenpaw/extensions/api/fde_workbench_service.py` (add helper near `_read_staged_bundle`, ~line 903)
- Test: `tests/unit/extensions/api/test_fde_staged_review.py` (create)

- [ ] **Step 1: Write the failing test**

```python
# -*- coding: utf-8 -*-
"""digest + 持久化人工审查闸门（方案 P）。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from qwenpaw.extensions.api import fde_workbench_service as svc


def _make_staged(staged_root: Path, name: str = "demo") -> Path:
    """Hand-build a minimal staged skill (no subprocess)."""
    d = staged_root / name
    (d / "runtime").mkdir(parents=True)
    (d / "SKILL.md").write_text(
        "---\nname: demo\ndescription: 网管告警查询\n"
        "triggers: [\"告警\"]\n---\n\n# Demo\n",
        encoding="utf-8",
    )
    (d / "runtime" / "tool_adapters.py").write_text(
        "X = 1\n", encoding="utf-8",
    )
    (d / "_fde_meta.json").write_text(
        json.dumps(
            {
                "schema": "fde-staged-skill.v1",
                "skill_name": name,
                "target_workspace": "query",
            },
        ),
        encoding="utf-8",
    )
    return d


def test_digest_is_stable_and_content_sensitive(tmp_path):
    d = _make_staged(tmp_path)
    base = svc._staged_content_digest(d)
    assert base == svc._staged_content_digest(d)  # stable

    (d / "runtime" / "tool_adapters.py").write_text("X = 2\n", "utf-8")
    assert svc._staged_content_digest(d) != base  # content change moves it


def test_digest_ignores_internal_meta_files(tmp_path):
    d = _make_staged(tmp_path)
    base = svc._staged_content_digest(d)
    # mutating _fde_meta.json / GENERATION.md must NOT change the digest
    # (the review block itself lives in _fde_meta.json — no self-reference)
    meta = json.loads((d / "_fde_meta.json").read_text("utf-8"))
    meta["review"] = {"status": "approved"}
    (d / "_fde_meta.json").write_text(json.dumps(meta), "utf-8")
    (d / "GENERATION.md").write_text("# notes\n", "utf-8")
    assert svc._staged_content_digest(d) == base
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/extensions/api/test_fde_staged_review.py -v`
Expected: FAIL with `AttributeError: module ... has no attribute '_staged_content_digest'`.

- [ ] **Step 3: Implement `_staged_content_digest`**

Add to `fde_workbench_service.py` (and `import hashlib` at top):

```python
def _staged_content_digest(skill_dir: Path) -> str:
    """SHA-256 over all managed staged files (sorted by relpath),
    excluding FDE-internal meta files. Binds a human-review approval to
    exact content: any edit changes the digest, auto-invalidating the
    approval. Excludes ``_fde_meta.json`` (which stores the digest) to
    avoid self-reference. Mirrors ``_read_staged_bundle``'s file filter.
    """
    h = hashlib.sha256()
    for path in sorted(skill_dir.rglob("*")):
        if path.is_dir():
            continue
        if "__pycache__" in path.parts or path.suffix == ".pyc":
            continue
        rel = path.relative_to(skill_dir)
        if len(rel.parts) == 1 and rel.parts[0] in _STAGED_INTERNAL_FILES:
            continue
        h.update(rel.as_posix().encode("utf-8"))
        h.update(b"\0")
        h.update(path.read_bytes())
        h.update(b"\0")
    return h.hexdigest()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/extensions/api/test_fde_staged_review.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add src/qwenpaw/extensions/api/fde_workbench_service.py tests/unit/extensions/api/test_fde_staged_review.py
git commit -m "feat(fde): content-digest helper for staged skills (review-gate binding)"
```

### Task 2.2: meta load/save + `_review_state`

**Files:**
- Modify: `src/qwenpaw/extensions/api/fde_workbench_service.py`
- Test: `tests/unit/extensions/api/test_fde_staged_review.py` (append)

- [ ] **Step 1: Write the failing test** (append to the same file)

```python
def test_review_state_defaults_to_pending(tmp_path):
    d = _make_staged(tmp_path)
    meta = svc._load_staged_meta(d)
    rv = svc._review_state(d, meta)
    assert rv["status"] == "pending"
    assert rv["effective"] == "pending"
    assert rv["digest_matches"] is False


def test_review_state_approved_then_stale_on_edit(tmp_path):
    d = _make_staged(tmp_path)
    meta = svc._load_staged_meta(d)
    meta["review"] = {
        "status": "approved",
        "approved_by": "op",
        "approved_at": "2026-06-08T00:00:00+00:00",
        "content_digest": svc._staged_content_digest(d),
    }
    svc._save_staged_meta(d, meta)

    rv = svc._review_state(d, svc._load_staged_meta(d))
    assert rv["effective"] == "approved"

    # edit a managed file -> digest drifts -> approval goes stale
    (d / "runtime" / "tool_adapters.py").write_text("X = 99\n", "utf-8")
    rv2 = svc._review_state(d, svc._load_staged_meta(d))
    assert rv2["status"] == "approved"
    assert rv2["digest_matches"] is False
    assert rv2["effective"] == "stale"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/extensions/api/test_fde_staged_review.py -v`
Expected: FAIL (`_load_staged_meta` undefined).

- [ ] **Step 3: Implement meta helpers + `_review_state`**

```python
def _load_staged_meta(skill_dir: Path) -> dict[str, Any]:
    meta_path = skill_dir / "_fde_meta.json"
    if not meta_path.exists():
        raise FdeWorkbenchError(
            f"staged 技能缺少 _fde_meta.json：{skill_dir.name}"
        )
    try:
        data = json.loads(meta_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise FdeWorkbenchError(
            f"_fde_meta.json 不是合法 JSON：{skill_dir.name}"
        ) from exc
    if not isinstance(data, dict):
        raise FdeWorkbenchError(
            f"_fde_meta.json 不是 JSON 对象：{skill_dir.name}"
        )
    return data


def _save_staged_meta(skill_dir: Path, meta: dict[str, Any]) -> None:
    (skill_dir / "_fde_meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8",
    )


def _review_state(
    skill_dir: Path, meta: dict[str, Any],
) -> dict[str, Any]:
    """Derive the human-review verdict. ``effective`` is computed, never
    stored: approved only when status==approved AND the stored digest
    still matches current content (else 'stale'); otherwise 'pending'.
    """
    review = meta.get("review") or {}
    status = str(review.get("status") or "pending")
    stored = review.get("content_digest")
    current = _staged_content_digest(skill_dir)
    digest_matches = bool(stored) and stored == current
    if status == "approved" and digest_matches:
        effective = "approved"
    elif status == "approved":
        effective = "stale"
    else:
        effective = "pending"
    return {
        "status": status,
        "approved_by": review.get("approved_by"),
        "approved_at": review.get("approved_at"),
        "content_digest": stored,
        "current_digest": current,
        "digest_matches": digest_matches,
        "effective": effective,
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/extensions/api/test_fde_staged_review.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add src/qwenpaw/extensions/api/fde_workbench_service.py tests/unit/extensions/api/test_fde_staged_review.py
git commit -m "feat(fde): persisted review state with derived staleness on edit"
```

---

## Phase 3 — editing: frontmatter, .env.example, path-safety, edit endpoints

### Task 3.1: safe frontmatter rewrite

**Files:**
- Modify: `src/qwenpaw/extensions/api/fde_workbench_service.py`
- Test: `tests/unit/extensions/api/test_fde_staged_edit.py` (create)

- [ ] **Step 1: Write the failing test**

```python
# -*- coding: utf-8 -*-
"""缺口A：引导字段 + 高级直改 + 路径安全。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from qwenpaw.extensions.api import fde_workbench_service as svc

SKILL_MD = (
    "---\n"
    "name: demo\n"
    "category: ops-delivery\n"
    "tags: [fde, demo]\n"
    "triggers: [告警, 查询]\n"
    "description: 老描述\n"
    "---\n\n"
    "# Demo\n\n正文保持不动。\n"
)


def test_rewrite_frontmatter_updates_keys_preserves_body():
    out = svc._rewrite_frontmatter(
        SKILL_MD,
        {
            "description": "新描述: 含冒号也安全",
            "triggers": ["应用拓扑", "查CMDB"],
        },
    )
    # body untouched
    assert "正文保持不动。" in out
    # frontmatter still valid YAML and reflects the edits
    block = out.split("---", 2)[1]
    data = yaml.safe_load(block)
    assert data["description"] == "新描述: 含冒号也安全"
    assert data["triggers"] == ["应用拓扑", "查CMDB"]
    # untouched keys survive
    assert data["name"] == "demo"
    assert data["category"] == "ops-delivery"


def test_rewrite_frontmatter_rejects_missing_frontmatter():
    with pytest.raises(svc.FdeWorkbenchError):
        svc._rewrite_frontmatter("no frontmatter here\n", {"description": "x"})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/extensions/api/test_fde_staged_edit.py -v`
Expected: FAIL (`_rewrite_frontmatter` undefined).

- [ ] **Step 3: Implement the rewriter**

```python
def _yaml_dq(s: str) -> str:
    """Double-quote a scalar so it's always valid YAML (no quoting guesswork)."""
    return '"' + str(s).replace("\\", "\\\\").replace('"', '\\"') + '"'


def _render_fm_line(key: str, value: Any) -> str:
    if isinstance(value, (list, tuple)):
        items = ", ".join(
            _yaml_dq(str(v).strip()) for v in value if str(v).strip()
        )
        return f"{key}: [{items}]"
    return f"{key}: {_yaml_dq(str(value))}"


def _rewrite_frontmatter(skill_md: str, updates: dict[str, Any]) -> str:
    """Surgically update specific frontmatter keys, preserving the body and
    every other key. Edited keys are re-emitted as double-quoted YAML
    scalars / flow lists. Raises on malformed frontmatter so we never write
    a corrupt SKILL.md.
    """
    updates = {k: v for k, v in (updates or {}).items() if v is not None}
    if not updates:
        return skill_md
    m = re.match(r"^(---\s*\n)(.*?)(\n---\s*\n)(.*)$", skill_md, re.S)
    if not m:
        raise FdeWorkbenchError(
            "SKILL.md 缺少合法 YAML frontmatter，无法安全改写"
        )
    head, block, fence, body = m.group(1), m.group(2), m.group(3), m.group(4)
    seen: set[str] = set()
    new_lines: list[str] = []
    for line in block.split("\n"):
        stripped = line.strip()
        key = (
            stripped.partition(":")[0].strip()
            if ":" in stripped and not stripped.startswith("#")
            else ""
        )
        if key in updates:
            new_lines.append(_render_fm_line(key, updates[key]))
            seen.add(key)
        else:
            new_lines.append(line)
    for key, value in updates.items():
        if key not in seen:
            new_lines.append(_render_fm_line(key, value))
    return head + "\n".join(new_lines) + fence + body
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/extensions/api/test_fde_staged_edit.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add src/qwenpaw/extensions/api/fde_workbench_service.py tests/unit/extensions/api/test_fde_staged_edit.py
git commit -m "feat(fde): surgical SKILL.md frontmatter rewrite for guided edits"
```

### Task 3.2: `.env.example` updater with secret-emptying (D4)

**Files:**
- Modify: `src/qwenpaw/extensions/api/fde_workbench_service.py`
- Test: `tests/unit/extensions/api/test_fde_staged_edit.py` (append)

- [ ] **Step 1: Write the failing test**

```python
def test_update_env_example_sets_values_and_empties_secrets():
    text = "# token\nCMDB_TOKEN=\n# base url\nCMDB_BASE_URL=\n"
    out = svc._update_env_example(
        text,
        {
            "CMDB_TOKEN": "super-secret",      # secret -> emptied (D4)
            "CMDB_BASE_URL": "http://x:8000",  # non-secret -> kept
            "EXTRA_FLAG": "1",                 # new key appended
        },
    )
    assert "CMDB_TOKEN=\n" in out             # value stripped
    assert "super-secret" not in out          # secret never lands on disk
    assert "CMDB_BASE_URL=http://x:8000" in out
    assert "EXTRA_FLAG=1" in out
    # comments preserved
    assert "# token" in out and "# base url" in out


def test_is_secret_env_key_matches_credential_shapes():
    for k in ["CMDB_TOKEN", "API_KEY", "x_secret", "DB_PASSWORD", "AK", "app_sk"]:
        assert svc._is_secret_env_key(k) is True
    for k in ["CMDB_BASE_URL", "TIMEOUT", "TASK_URL", "REGION"]:
        assert svc._is_secret_env_key(k) is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/extensions/api/test_fde_staged_edit.py -v`
Expected: FAIL (`_update_env_example` undefined).

- [ ] **Step 3: Implement**

```python
# KEY as substring + AK/SK only as whole _-bounded segments (so TASK/RISK
# don't false-match). Emptying a non-secret by mistake is harmless (operator
# re-enters at install); leaking a secret into a staged file is not.
_SECRET_ENV_KEY_RE = re.compile(
    r"(TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL|KEY|(^|_)(AK|SK)(_|$))",
    re.I,
)


def _is_secret_env_key(key: str) -> bool:
    return bool(_SECRET_ENV_KEY_RE.search(str(key or "")))


def _update_env_example(text: str, updates: dict[str, str]) -> str:
    """Update/append ``KEY=value`` lines, preserving comments + order.
    Secret-looking keys are written with an EMPTY value (D4: credentials
    never land in staged files).
    """
    if not updates:
        return text or ""
    remaining = {
        str(k).strip(): ("" if _is_secret_env_key(k) else str(v))
        for k, v in updates.items()
        if str(k).strip()
    }
    out_lines: list[str] = []
    for raw in (text or "").splitlines():
        stripped = raw.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key = stripped.partition("=")[0].strip()
            if key in remaining:
                out_lines.append(f"{key}={remaining.pop(key)}")
                continue
        out_lines.append(raw)
    for key, val in remaining.items():
        out_lines.append(f"{key}={val}")
    body = "\n".join(out_lines)
    return body if body.endswith("\n") else body + "\n"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/extensions/api/test_fde_staged_edit.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add src/qwenpaw/extensions/api/fde_workbench_service.py tests/unit/extensions/api/test_fde_staged_edit.py
git commit -m "feat(fde): .env.example updater that empties secret values (D4)"
```

### Task 3.3: path-safe staged target resolver

**Files:**
- Modify: `src/qwenpaw/extensions/api/fde_workbench_service.py`
- Test: `tests/unit/extensions/api/test_fde_staged_edit.py` (append)

- [ ] **Step 1: Write the failing test**

```python
def _bare_staged(tmp_path: Path) -> Path:
    d = tmp_path / "demo"
    (d / "runtime").mkdir(parents=True)
    (d / "SKILL.md").write_text("---\nname: demo\n---\n", "utf-8")
    return d


def test_safe_staged_target_allows_normal_paths(tmp_path):
    d = _bare_staged(tmp_path)
    assert svc._safe_staged_target(d, "SKILL.md") == (d / "SKILL.md").resolve()
    assert svc._safe_staged_target(d, "runtime/x.py") == (
        d / "runtime" / "x.py"
    ).resolve()


@pytest.mark.parametrize(
    "rel",
    ["../escape.py", "/etc/passwd", "_fde_meta.json", "GENERATION.md",
     "runtime/../../x", ""],
)
def test_safe_staged_target_rejects_bad_paths(tmp_path, rel):
    d = _bare_staged(tmp_path)
    with pytest.raises(svc.FdeWorkbenchError):
        svc._safe_staged_target(d, rel)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/extensions/api/test_fde_staged_edit.py -v`
Expected: FAIL (`_safe_staged_target` undefined).

- [ ] **Step 3: Implement**

```python
def _safe_staged_target(skill_dir: Path, rel: str) -> Path:
    """Resolve a relative path inside ``skill_dir`` for writing, rejecting
    traversal, absolute paths, FDE-internal files, and symlinks."""
    rel = str(rel or "").strip()
    if not rel:
        raise FdeWorkbenchError("文件路径不能为空")
    if rel.startswith("/") or rel.startswith("\\") or ":" in rel.split("/")[0]:
        raise FdeWorkbenchError(f"不允许绝对路径：{rel}")
    base = skill_dir.resolve()
    target = (base / rel).resolve()
    if target != base and base not in target.parents:
        raise FdeWorkbenchError(f"路径越界（疑似穿越）：{rel}")
    parts = target.relative_to(base).parts
    if not parts:
        raise FdeWorkbenchError(f"不允许写入技能根目录：{rel}")
    if parts[-1] in _STAGED_INTERNAL_FILES:
        raise FdeWorkbenchError(f"不允许编辑内部文件：{parts[-1]}")
    if target.is_symlink():
        raise FdeWorkbenchError(f"不允许写入符号链接：{rel}")
    return target
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/extensions/api/test_fde_staged_edit.py -v`
Expected: PASS (path-safety params all green).

- [ ] **Step 5: Commit**

```bash
git add src/qwenpaw/extensions/api/fde_workbench_service.py tests/unit/extensions/api/test_fde_staged_edit.py
git commit -m "feat(fde): path-safe staged file target resolver"
```

### Task 3.4: edit endpoints + mutation result composer

**Files:**
- Modify: `src/qwenpaw/extensions/api/fde_workbench_service.py`
- Test: `tests/unit/extensions/api/test_fde_staged_edit.py` (append)

- [ ] **Step 1: Write the failing test**

```python
def _full_staged(tmp_path: Path) -> Path:
    d = tmp_path / "demo"
    (d / "runtime").mkdir(parents=True)
    d_md = (
        "---\nname: demo\ncategory: ops\ntags: [a]\n"
        "triggers: [告警]\ndescription: 旧\n---\n\n# Demo\n"
    )
    (d / "SKILL.md").write_text(d_md, "utf-8")
    (d / ".env.example").write_text("CMDB_TOKEN=\nCMDB_BASE_URL=\n", "utf-8")
    (d / "runtime" / "tool_adapters.py").write_text("X = 1\n", "utf-8")
    (d / "_fde_meta.json").write_text(
        json.dumps({"skill_name": "demo", "target_workspace": "query"}),
        "utf-8",
    )
    return d


@pytest.fixture
def staged_only(monkeypatch, tmp_path):
    """Point the staged dir at tmp_path and stub the subprocess calls so the
    edit logic is tested in isolation (no fde_tools / scanner / LLM)."""
    staged = tmp_path / "staged"
    staged.mkdir()
    monkeypatch.setenv("QWENPAW_FDE_STAGED_DIR", str(staged))
    monkeypatch.setattr(
        svc, "show_staged_skill",
        lambda name, **k: {"skill_name": name, "files": []},
    )
    monkeypatch.setattr(
        svc, "selfcheck_staged_skill",
        lambda name: {"ready_for_review": True, "scan": {"findings": []}},
    )
    return staged


def test_edit_fields_rewrites_md_and_env(staged_only):
    d = _full_staged(staged_only.parent)
    # relocate into the staged dir the service looks at
    d.rename(staged_only / "demo")
    out = svc.edit_staged_fields(
        "demo",
        description="新描述",
        triggers=["应用拓扑"],
        env={"CMDB_TOKEN": "leak", "CMDB_BASE_URL": "http://x:8000"},
    )
    md = (staged_only / "demo" / "SKILL.md").read_text("utf-8")
    assert "新描述" in md and "应用拓扑" in md
    env = (staged_only / "demo" / ".env.example").read_text("utf-8")
    assert "CMDB_TOKEN=\n" in env and "leak" not in env       # secret emptied
    assert "CMDB_BASE_URL=http://x:8000" in env
    # envelope shape: staged(+review) + fresh selfcheck
    assert out["staged"]["review"]["effective"] == "pending"
    assert out["selfcheck"]["ready_for_review"] is True


def test_edit_files_writes_and_rejects_traversal(staged_only):
    d = _full_staged(staged_only.parent)
    d.rename(staged_only / "demo")
    svc.edit_staged_files(
        "demo",
        [{"path": "runtime/tool_adapters.py", "content": "Y = 2\n"}],
    )
    assert (
        staged_only / "demo" / "runtime" / "tool_adapters.py"
    ).read_text("utf-8") == "Y = 2\n"
    with pytest.raises(svc.FdeWorkbenchError):
        svc.edit_staged_files(
            "demo", [{"path": "../evil.py", "content": "x"}],
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/extensions/api/test_fde_staged_edit.py -v`
Expected: FAIL (`edit_staged_fields` undefined).

- [ ] **Step 3: Implement detail composer + edit functions**

```python
def staged_detail_with_review(name: str) -> dict[str, Any]:
    """show-staged bundle + computed review state. Shape returned by GET
    /fde/staged/{name}."""
    name = _validate_skill_name(name)
    skill_dir = fde_staged_dir() / name
    if not skill_dir.is_dir():
        raise FdeWorkbenchError(f"未找到 staged 技能：{name}")
    detail = show_staged_skill(name)
    detail["review"] = _review_state(skill_dir, _load_staged_meta(skill_dir))
    return detail


def _mutation_result(name: str) -> dict[str, Any]:
    """Envelope returned by edit/review mutators: staged(bundle+review) +
    fresh selfcheck — one response the panel re-renders from."""
    return {
        "staged": staged_detail_with_review(name),
        "selfcheck": selfcheck_staged_skill(name),
    }


def edit_staged_fields(
    name: str,
    *,
    description: str | None = None,
    triggers: list[str] | None = None,
    category: str | None = None,
    tags: list[str] | None = None,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    name = _validate_skill_name(name)
    skill_dir = fde_staged_dir() / name
    if not skill_dir.is_dir():
        raise FdeWorkbenchError(f"未找到 staged 技能：{name}")
    updates: dict[str, Any] = {}
    if description is not None:
        updates["description"] = description
    if triggers is not None:
        updates["triggers"] = triggers
    if category is not None:
        updates["category"] = category
    if tags is not None:
        updates["tags"] = tags
    if updates:
        md_path = skill_dir / "SKILL.md"
        if not md_path.is_file():
            raise FdeWorkbenchError("staged 技能缺少 SKILL.md")
        new_md = _rewrite_frontmatter(
            md_path.read_text(encoding="utf-8"), updates,
        )
        try:  # never write frontmatter that doesn't parse
            import yaml

            yaml.safe_load(new_md.split("---", 2)[1])
        except Exception as exc:  # noqa: BLE001
            raise FdeWorkbenchError(
                f"改写后的 frontmatter 非法 YAML：{exc}"
            ) from exc
        md_path.write_text(new_md, encoding="utf-8")
    if env:
        example = skill_dir / ".env.example"
        current = (
            example.read_text(encoding="utf-8") if example.is_file() else ""
        )
        example.write_text(_update_env_example(current, env), encoding="utf-8")
    return _mutation_result(name)


def edit_staged_files(
    name: str, files: list[dict[str, Any]],
) -> dict[str, Any]:
    name = _validate_skill_name(name)
    skill_dir = fde_staged_dir() / name
    if not skill_dir.is_dir():
        raise FdeWorkbenchError(f"未找到 staged 技能：{name}")
    if not files:
        raise FdeWorkbenchError("没有要保存的文件")
    # validate ALL paths before writing ANY (atomic-ish)
    targets: list[tuple[Path, str]] = []
    for item in files:
        path = item.get("path") if isinstance(item, dict) else None
        content = item.get("content") if isinstance(item, dict) else None
        targets.append(
            (_safe_staged_target(skill_dir, path or ""), content or ""),
        )
    for target, content in targets:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    return _mutation_result(name)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/extensions/api/test_fde_staged_edit.py -v`
Expected: PASS (all edit tests).

- [ ] **Step 5: Commit**

```bash
git add src/qwenpaw/extensions/api/fde_workbench_service.py tests/unit/extensions/api/test_fde_staged_edit.py
git commit -m "feat(fde): staged-skill guided-field and raw-file edit endpoints"
```

---

## Phase 4 — review action, install gate, models, routes

### Task 4.1: `set_staged_review` (approve/reset)

**Files:**
- Modify: `src/qwenpaw/extensions/api/fde_workbench_service.py`
- Test: `tests/unit/extensions/api/test_fde_staged_review.py` (append)

- [ ] **Step 1: Write the failing test**

```python
@pytest.fixture
def staged_review_env(monkeypatch, tmp_path):
    staged = tmp_path / "staged"
    staged.mkdir()
    monkeypatch.setenv("QWENPAW_FDE_STAGED_DIR", str(staged))
    monkeypatch.setattr(
        svc, "show_staged_skill",
        lambda name, **k: {"skill_name": name, "files": []},
    )
    return staged


def test_approve_requires_ready_for_review(staged_review_env, monkeypatch):
    _make_staged(staged_review_env)
    monkeypatch.setattr(
        svc, "selfcheck_staged_skill",
        lambda name: {"ready_for_review": False,
                      "blocked_reasons": ["语法错误"]},
    )
    with pytest.raises(svc.FdeWorkbenchError):
        svc.set_staged_review("demo", action="approve")


def test_approve_then_reset_review(staged_review_env, monkeypatch):
    d = _make_staged(staged_review_env)
    monkeypatch.setattr(
        svc, "selfcheck_staged_skill",
        lambda name: {"ready_for_review": True},
    )
    out = svc.set_staged_review("demo", action="approve", approved_by="vince")
    rv = out["staged"]["review"]
    assert rv["effective"] == "approved"
    assert rv["approved_by"] == "vince"
    assert rv["content_digest"] == svc._staged_content_digest(d)

    out2 = svc.set_staged_review("demo", action="reset")
    assert out2["staged"]["review"]["effective"] == "pending"
    assert out2["staged"]["review"]["content_digest"] is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/extensions/api/test_fde_staged_review.py -v`
Expected: FAIL (`set_staged_review` undefined).

- [ ] **Step 3: Implement**

```python
def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def set_staged_review(
    name: str,
    *,
    action: str,
    approved_by: str | None = None,
) -> dict[str, Any]:
    name = _validate_skill_name(name)
    skill_dir = fde_staged_dir() / name
    if not skill_dir.is_dir():
        raise FdeWorkbenchError(f"未找到 staged 技能：{name}")
    meta = _load_staged_meta(skill_dir)
    if action == "approve":
        sc = selfcheck_staged_skill(name)  # gate 1 at approve time
        if not sc.get("ready_for_review"):
            raise FdeWorkbenchError(
                "AI 自检未通过，不能标记审查通过："
                + "；".join(sc.get("blocked_reasons") or ["未知原因"])
            )
        label = str(approved_by or "").strip() or None
        meta["review"] = {
            "status": "approved",
            "approved_by": label,
            "approved_at": _now_iso(),
            "content_digest": _staged_content_digest(skill_dir),
        }
    elif action == "reset":
        meta["review"] = {
            "status": "pending",
            "approved_by": None,
            "approved_at": None,
            "content_digest": None,
        }
    else:
        raise FdeWorkbenchError(f"未知的审查动作：{action}")
    _save_staged_meta(skill_dir, meta)
    return _mutation_result(name)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/extensions/api/test_fde_staged_review.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/qwenpaw/extensions/api/fde_workbench_service.py tests/unit/extensions/api/test_fde_staged_review.py
git commit -m "feat(fde): approve/reset human-review action on staged skills"
```

### Task 4.2: gate `install_staged_skill` + update existing install tests

The install gate enforces the human review server-side. AI-自检 is enforced *transitively* (approve requires `ready_for_review`, and the digest proves the content is identical to what passed) plus the live `SkillService.create_skill` scan that install already runs — so no redundant standalone self-check here.

**Files:**
- Modify: `src/qwenpaw/extensions/api/fde_workbench_service.py:1061-1069` (the inline meta read inside `install_staged_skill`)
- Modify: `tests/unit/extensions/api/test_fde_workbench.py` (install tests must approve first)
- Test: `tests/unit/extensions/api/test_fde_staged_review.py` (append gate tests)

- [ ] **Step 1: Write the failing gate tests** (append to `test_fde_staged_review.py`)

```python
def test_install_blocked_until_review_approved(
    monkeypatch, tmp_path,
):
    staged = tmp_path / "staged"
    staged.mkdir()
    monkeypatch.setenv("QWENPAW_FDE_STAGED_DIR", str(staged))
    d = _make_staged(staged)

    # pending review -> install refused before touching any workspace
    with pytest.raises(svc.FdeWorkbenchError) as ei:
        svc.install_staged_skill("demo", auto_create_target=False)
    assert "审查" in str(ei.value)

    # approve, then edit -> stale -> still refused
    monkeypatch.setattr(
        svc, "selfcheck_staged_skill",
        lambda name: {"ready_for_review": True},
    )
    monkeypatch.setattr(
        svc, "show_staged_skill",
        lambda name, **k: {"skill_name": name, "files": []},
    )
    svc.set_staged_review("demo", action="approve")
    (d / "runtime" / "tool_adapters.py").write_text("X = 2\n", "utf-8")
    with pytest.raises(svc.FdeWorkbenchError) as ei2:
        svc.install_staged_skill("demo", auto_create_target=False)
    assert "复审" in str(ei2.value) or "修改" in str(ei2.value)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/extensions/api/test_fde_staged_review.py::test_install_blocked_until_review_approved -v`
Expected: FAIL — currently install proceeds past the (missing) gate and raises a *different* error (or none), so the `"审查"` assertion fails.

- [ ] **Step 3: Insert the gate**

In `install_staged_skill`, replace the inline meta read (lines 1061-1069):

```python
    meta_path = skill_dir / "_fde_meta.json"
    if not meta_path.exists():
        raise FdeWorkbenchError(f"staged 技能缺少 _fde_meta.json：{name}")
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise FdeWorkbenchError(
            f"_fde_meta.json 不是合法 JSON：{name}"
        ) from exc
```

with:

```python
    meta = _load_staged_meta(skill_dir)
    # --- 人工审查闸门（D2/D3）：服务端强约束，不靠前端禁用按钮 ---
    review = _review_state(skill_dir, meta)
    if review["effective"] != "approved":
        if review["effective"] == "stale":
            raise FdeWorkbenchError(
                "内容在审查通过后被修改，请复审后再安装"
            )
        raise FdeWorkbenchError(
            "人工审查未通过，不能安装（请先在工作台点「审查通过」）"
        )
```

- [ ] **Step 4: Update existing install tests to approve first**

In `tests/unit/extensions/api/test_fde_workbench.py`, every test that calls `svc.install_staged_skill(<name>)` expecting success must approve first. Insert `svc.set_staged_review(<name>, action="approve")` immediately after the matching `svc.generate_skill(...)` (the generated skill is `ready_for_review`, so approve succeeds). Tests to update:

- `test_install_staged_skill_into_workspace` → after generate `demo-installable`
- `test_install_mirrors_to_gateway_by_default` → after generate `demo-mirror`
- `test_install_skips_mirror_when_target_is_gateway` → after generate `demo-gw-target`
- `test_install_opt_out_mirror` → after generate `demo-no-mirror`
- `test_delete_installed_skill_cleans_gateway_mirror` → after generate `demo-delete-me`
- `test_copy_installed_skill_move` → after generate `demo-migrate-me`
- `test_install_skip_domain_check_prewarms_cache` → after writing the hand-built `demo-skip` staged dir (before `install_staged_skill`)
- `test_install_writes_env_values` → after generate `demo-env-install`
- `test_install_auto_creates_missing_target` → after generate `demo-auto-create`

Example edit (mirror the pattern in each):

```python
    svc.generate_skill(name="demo-installable", target_workspace="some-business-agent", brief={...})
    svc.set_staged_review("demo-installable", action="approve")  # <-- new: gate 2
    result = svc.install_staged_skill("demo-installable")
```

For `test_full_staged_skill_lifecycle`, the `install_staged_skill("demo-alarm-stat", target_override="no-such-agent-xyz", auto_create_target=False)` still `pytest.raises(FdeWorkbenchError)` — it now raises at the review gate instead of the unknown-target check, which still satisfies the test. Leave it unchanged.

- [ ] **Step 5: Run the full FDE suite to verify**

Run: `.venv/bin/python -m pytest tests/unit/extensions/api/test_fde_workbench.py tests/unit/extensions/api/test_fde_staged_review.py -v`
Expected: PASS (install tests green with approval; gate tests green).

- [ ] **Step 6: Commit**

```bash
git add src/qwenpaw/extensions/api/fde_workbench_service.py tests/unit/extensions/api/test_fde_workbench.py tests/unit/extensions/api/test_fde_staged_review.py
git commit -m "feat(fde): gate install behind digest-bound human-review approval"
```

### Task 4.3: request models

**Files:**
- Modify: `src/qwenpaw/extensions/api/fde_workbench_models.py`

- [ ] **Step 1: Add the models** (no separate unit test — exercised via route tests / typecheck; this is a 2-minute mechanical step)

Change the import line `from typing import Any` to `from typing import Any, Literal`, then append:

```python
class FdeEditFieldsRequest(BaseModel):
    """引导字段：只改提供的键，未提供的保持原样。"""

    description: str | None = None
    triggers: list[str] | None = None
    category: str | None = None
    tags: list[str] | None = None
    # 非密配置（接口URL / *_BASE_URL 等）→ 写入 .env.example；密钥型 key
    # 的值由后端强制清空（凭证仍在 install 时经 env_values 注入）。
    env: dict[str, str] | None = None


class FdeStagedFile(BaseModel):
    path: str = Field(..., description="skill_dir 相对路径")
    content: str = Field(default="", description="文件内容")


class FdeEditFilesRequest(BaseModel):
    files: list[FdeStagedFile] = Field(default_factory=list)


class FdeReviewRequest(BaseModel):
    action: Literal["approve", "reset"]
    approved_by: str | None = None
```

- [ ] **Step 2: Verify import**

Run: `.venv/bin/python -c "from qwenpaw.extensions.api.fde_workbench_models import FdeEditFieldsRequest, FdeStagedFile, FdeEditFilesRequest, FdeReviewRequest; print('ok')"`
Expected: prints `ok`.

- [ ] **Step 3: Commit**

```bash
git add src/qwenpaw/extensions/api/fde_workbench_models.py
git commit -m "feat(fde): request models for edit/review endpoints"
```

### Task 4.4: portal routes

**Files:**
- Modify: `src/qwenpaw/extensions/api/portal_backend.py` (FDE routes block, ~3063-3081)

- [ ] **Step 1: Wire the new models into the existing import**

Find where `FdeGenerateRequest`, `FdeProbeRequest`, `FdeInstallRequest`, `FdeEnvWriteRequest`, `FdeCopyInstalledRequest` are imported from `fde_workbench_models` and add `FdeEditFieldsRequest, FdeEditFilesRequest, FdeReviewRequest` to that import.

- [ ] **Step 2: Change GET detail to carry review**

Replace the body of `fde_show_staged` (line ~3064-3070) to call the review-aware composer:

```python
@router.get("/fde/staged/{skill_name}")
async def fde_show_staged(skill_name: str):
    try:
        return await asyncio.to_thread(
            fde_workbench_service.staged_detail_with_review, skill_name,
        )
    except fde_workbench_service.FdeWorkbenchError as exc:
        return _fde_error_response(exc)
```

- [ ] **Step 3: Add the 3 mutator routes** (place after `fde_selfcheck_staged`, before `fde_probe_staged`)

```python
@router.put("/fde/staged/{skill_name}/fields")
async def fde_edit_staged_fields(
    skill_name: str, body: FdeEditFieldsRequest,
):
    try:
        return await asyncio.to_thread(
            lambda: fde_workbench_service.edit_staged_fields(
                skill_name,
                description=body.description,
                triggers=body.triggers,
                category=body.category,
                tags=body.tags,
                env=body.env,
            ),
        )
    except fde_workbench_service.FdeWorkbenchError as exc:
        return _fde_error_response(exc)


@router.put("/fde/staged/{skill_name}/files")
async def fde_edit_staged_files(
    skill_name: str, body: FdeEditFilesRequest,
):
    try:
        return await asyncio.to_thread(
            lambda: fde_workbench_service.edit_staged_files(
                skill_name,
                [{"path": f.path, "content": f.content} for f in body.files],
            ),
        )
    except fde_workbench_service.FdeWorkbenchError as exc:
        return _fde_error_response(exc)


@router.post("/fde/staged/{skill_name}/review")
async def fde_review_staged(skill_name: str, body: FdeReviewRequest):
    try:
        return await asyncio.to_thread(
            lambda: fde_workbench_service.set_staged_review(
                skill_name,
                action=body.action,
                approved_by=body.approved_by,
            ),
        )
    except fde_workbench_service.FdeWorkbenchError as exc:
        return _fde_error_response(exc)
```

- [ ] **Step 4: Verify the app imports the routes cleanly**

Run: `.venv/bin/python -c "import qwenpaw.extensions.api.portal_backend as p; print([r.path for r in p.router.routes if '/fde/staged' in getattr(r, 'path', '')])"`
Expected: list includes `/fde/staged/{skill_name}/fields`, `/fde/staged/{skill_name}/files`, `/fde/staged/{skill_name}/review`.

- [ ] **Step 5: Run the whole extensions suite (regression)**

Run: `.venv/bin/python -m pytest tests/unit/extensions/api/test_fde_workbench.py tests/unit/extensions/api/test_fde_staged_review.py tests/unit/extensions/api/test_fde_staged_edit.py tests/unit/extensions/api/test_fde_selfcheck_findings.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/qwenpaw/extensions/api/portal_backend.py
git commit -m "feat(fde): edit/review portal routes; GET detail carries review state"
```

---

## Phase 5 — frontend: Layout A

No unit-test harness for the panel; verify each task with `cd portal && pnpm build` (tsc typecheck) and a final visual click-through (Phase 6). The panel uses hand-rolled `fde-*` CSS (not antd) and `<textarea>` (no code-editor lib) — match that.

### Task 5.1: fde.ts — rich types + 3 methods

**Files:**
- Modify: `portal/src/api/fde.ts`

- [ ] **Step 1: Add finding/review types** (after `FdeSelfcheckResult`, ~line 128)

```ts
export interface FdeScanFinding {
  severity: string;
  title: string;
  file: string;
  line: number | null;
  snippet?: string | null;
  remediation?: string | null;
  category?: string;
  rule_id?: string;
  description?: string;
}

export interface FdeScanResult {
  status?: string;
  is_safe?: boolean;
  max_severity?: string | null;
  findings?: FdeScanFinding[];
  reason?: string;
}

export type FdeReviewEffective = "approved" | "stale" | "pending";

export interface FdeReviewState {
  status: "pending" | "approved";
  approved_by: string | null;
  approved_at: string | null;
  content_digest: string | null;
  current_digest?: string;
  digest_matches: boolean;
  effective: FdeReviewEffective;
}
```

- [ ] **Step 2: Tighten `FdeSelfcheckResult.scan` + add `review` to detail + envelope type**

In `FdeSelfcheckResult`, change `scan?: Record<string, unknown>;` to `scan?: FdeScanResult;`. In `FdeStagedDetail`, add `review?: FdeReviewState;`. Then add the envelope after `FdeStagedDetail`:

```ts
export interface FdeStagedMutationResult {
  staged: FdeStagedDetail;
  selfcheck: FdeSelfcheckResult;
}
```

- [ ] **Step 3: Add the 3 methods to `fdeApi`** (after `selfcheckStaged`)

```ts
  editStagedFields: (
    skillName: string,
    body: {
      description?: string;
      triggers?: string[];
      category?: string;
      tags?: string[];
      env?: Record<string, string>;
    },
  ) =>
    requestFde<FdeStagedMutationResult>(
      `/staged/${encodeURIComponent(skillName)}/fields`,
      { method: "PUT", body: JSON.stringify(body) },
      HEAVY_TIMEOUT_MS,
    ),

  editStagedFiles: (
    skillName: string,
    files: Array<{ path: string; content: string }>,
  ) =>
    requestFde<FdeStagedMutationResult>(
      `/staged/${encodeURIComponent(skillName)}/files`,
      { method: "PUT", body: JSON.stringify({ files }) },
      HEAVY_TIMEOUT_MS,
    ),

  reviewStaged: (
    skillName: string,
    action: "approve" | "reset",
    approvedBy?: string,
  ) =>
    requestFde<FdeStagedMutationResult>(
      `/staged/${encodeURIComponent(skillName)}/review`,
      {
        method: "POST",
        body: JSON.stringify({ action, approved_by: approvedBy }),
      },
      HEAVY_TIMEOUT_MS,
    ),
```

- [ ] **Step 4: Typecheck**

Run: `cd portal && pnpm build`
Expected: tsc passes (build succeeds).

- [ ] **Step 5: Commit**

```bash
git add portal/src/api/fde.ts
git commit -m "feat(portal): fde api client — rich finding/review types + edit/review methods"
```

### Task 5.2: SelfcheckReport component (体检报告)

**Files:**
- Create: `portal/src/pages/digital-employee/SelfcheckReport.tsx`
- Modify: `portal/src/pages/fde-workbench.css` (append findings styles)

- [ ] **Step 1: Create the component**

```tsx
import type { FdeScanFinding, FdeSelfcheckResult } from "../../api/fde";

const SEV_CLASS: Record<string, string> = {
  critical: "h",
  high: "h",
  medium: "m",
  low: "l",
};
const SEV_LABEL: Record<string, string> = {
  critical: "严重",
  high: "高危",
  medium: "中危",
  low: "低危",
  info: "提示",
};

function Finding({ f }: { f: FdeScanFinding }) {
  const sev = (f.severity || "").toLowerCase();
  return (
    <div className="fde-find">
      <div className="fde-find-top">
        <span className={`fde-sev fde-sev--${SEV_CLASS[sev] || "l"}`}>
          {SEV_LABEL[sev] || f.severity}
        </span>
        <span className="fde-find-title">{f.title}</span>
        <span className="fde-find-loc">
          {f.file}
          {f.line != null ? `:${f.line}` : ""}
        </span>
      </div>
      {f.snippet ? <pre className="fde-find-snip">{f.snippet}</pre> : null}
      {f.remediation ? (
        <div className="fde-find-fix">
          修复建议：{f.remediation}
          {f.rule_id ? ` · 规则 ${f.rule_id}` : ""}
        </div>
      ) : f.rule_id ? (
        <div className="fde-find-fix">规则 {f.rule_id}</div>
      ) : null}
    </div>
  );
}

export function SelfcheckReport({
  result,
}: {
  result: FdeSelfcheckResult | undefined;
}) {
  if (!result) return null;
  if (result.error) {
    return (
      <div className="fde-report fde-report--bad">
        <span className="fde-pill fde-pill--bad">自检失败</span>
        <span className="fde-report-line">{result.error}</span>
      </div>
    );
  }
  const scan = result.scan;
  const findings: FdeScanFinding[] = scan?.findings || [];
  const domain = (result.domain || {}) as Record<string, unknown>;
  const syntax = (result.syntax || {}) as Record<string, unknown>;
  const syntaxErrors = (syntax.errors as unknown[] | undefined) || [];
  const todo = result.todo || [];
  return (
    <div className="fde-report">
      <div className="fde-report-head">
        <span className="fde-report-title">体检报告</span>
        <span className="fde-report-hint">每改一次自动重跑</span>
      </div>

      {/* 安全扫描 */}
      <div className="fde-report-row">
        <span className="fde-report-key">安全扫描</span>
        {findings.length === 0 ? (
          <span className="fde-chip fde-chip--g">未发现问题</span>
        ) : (
          <span className="fde-chip fde-chip--a">{findings.length} 项</span>
        )}
      </div>
      {findings.map((f, i) => (
        <Finding f={f} key={`${f.rule_id || f.title}-${i}`} />
      ))}

      {/* 域审查 */}
      <div className="fde-report-row">
        <span className="fde-report-key">域审查</span>
        <span className="fde-report-val">
          {domain.decision === "allow" ? (
            <span className="fde-chip fde-chip--g">
              allow · {String(domain.category || "网管运维")}
            </span>
          ) : domain.decision === "reject" ? (
            <span className="fde-chip fde-chip--r">reject</span>
          ) : (
            <span className="fde-chip">未执行</span>
          )}
          {domain.reason ? (
            <span className="fde-report-note"> {String(domain.reason)}</span>
          ) : null}
        </span>
      </div>

      {/* 语法 */}
      <div className="fde-report-row">
        <span className="fde-report-key">语法</span>
        {syntaxErrors.length === 0 ? (
          <span className="fde-chip fde-chip--g">.py 全部通过</span>
        ) : (
          <span className="fde-chip fde-chip--r">
            {syntaxErrors.length} 个文件有语法错
          </span>
        )}
      </div>

      {/* 待补全 */}
      {todo.length > 0 ? (
        <div className="fde-report-row fde-report-row--col">
          <span className="fde-report-key">待补全</span>
          <ul className="fde-report-todo">
            {todo.map((t) => (
              <li key={t}>{t}</li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}

export default SelfcheckReport;
```

- [ ] **Step 2: Append CSS** to `portal/src/pages/fde-workbench.css`

```css
/* --- 体检报告（缺口B） --- */
.fde-report { border: 1px solid var(--fde-border, rgba(128,128,128,.4));
  border-radius: 10px; padding: 10px 12px; display: flex;
  flex-direction: column; gap: 8px; font-size: 12px; }
.fde-report--bad { border-color: #d9534f; }
.fde-report-head { display: flex; justify-content: space-between;
  align-items: center; }
.fde-report-title { font-weight: 600; }
.fde-report-hint { font-size: 10px; opacity: .55; }
.fde-report-row { display: flex; gap: 8px; align-items: center; }
.fde-report-row--col { flex-direction: column; align-items: flex-start; }
.fde-report-key { width: 64px; flex: none; opacity: .7; }
.fde-report-note { opacity: .7; }
.fde-report-todo { margin: 2px 0 0; padding-left: 18px; }
.fde-find { border: 1px solid rgba(128,128,128,.35); border-radius: 7px;
  padding: 6px 8px; }
.fde-find-top { display: flex; gap: 7px; align-items: center;
  flex-wrap: wrap; }
.fde-find-title { font-weight: 500; }
.fde-find-loc { margin-left: auto; font-family: ui-monospace, Menlo,
  Consolas, monospace; font-size: 10px; opacity: .75; }
.fde-find-snip { margin: 5px 0 0; background: rgba(128,128,128,.14);
  border-radius: 5px; padding: 5px 7px; font-family: ui-monospace, monospace;
  font-size: 10px; white-space: pre-wrap; overflow: auto; }
.fde-find-fix { margin-top: 4px; font-size: 10px; opacity: .85; }
.fde-sev { font-size: 10px; font-weight: 700; border-radius: 4px;
  padding: 1px 6px; color: #fff; }
.fde-sev--h { background: #d9534f; }
.fde-sev--m { background: #e0a82e; }
.fde-sev--l { background: #6c8ebf; }
.fde-chip { font-size: 10px; border: 1px solid rgba(128,128,128,.5);
  border-radius: 999px; padding: 1px 8px; }
.fde-chip--g { border-color: #3aa76d; color: #3aa76d; }
.fde-chip--a { border-color: #c89a2b; color: #c89a2b; }
.fde-chip--r { border-color: #d9534f; color: #d9534f; }
```

- [ ] **Step 3: Typecheck**

Run: `cd portal && pnpm build`
Expected: passes (component is not yet imported — that's fine; tsc still typechecks the new file).

- [ ] **Step 4: Commit**

```bash
git add portal/src/pages/digital-employee/SelfcheckReport.tsx portal/src/pages/fde-workbench.css
git commit -m "feat(portal): rich self-check report component (security findings)"
```

### Task 5.3: panel right-column → Layout A (status strip + tabs + editing + gates + footer)

**Files:**
- Modify: `portal/src/pages/digital-employee/fdeWorkbenchPanel.tsx`
- Modify: `portal/src/pages/fde-workbench.css` (append tabs/footer/editor styles)

- [ ] **Step 1: Imports + new state**

Add to the fde imports (line 3-12): `type FdeReviewState`. Add `import { SelfcheckReport } from "./SelfcheckReport";`.

Inside `FdeWorkbenchPanel`, add state near the other `useState`s:

```tsx
  const [tab, setTab] = useState<"overview" | "code" | "probe">("overview");
  // edited code buffer per (skill -> path -> content); only dirty files saved
  const [codeEdits, setCodeEdits] = useState<Record<string, string>>({});
  // guided-field draft for the selected skill
  const [fieldDraft, setFieldDraft] = useState<{
    description: string;
    triggers: string;
  }>({ description: "", triggers: "" });
```

- [ ] **Step 2: Derive review + reset drafts on selection**

Add a memo + effect after `targetWorkspace` (line ~349):

```tsx
  const review: FdeReviewState | undefined = detail?.review;
  const reviewOk = review?.effective === "approved";
  const aiOk = Boolean(detail?.selfcheck?.ready_for_review);

  useEffect(() => {
    // seed guided fields from the freshly-loaded SKILL.md frontmatter
    setCodeEdits({});
    setTab("overview");
    if (!detail) {
      setFieldDraft({ description: "", triggers: "" });
      return;
    }
    const md =
      detail.files.find((f) => f.path === "SKILL.md")?.content || "";
    const desc = /^description:\s*(.*)$/m.exec(md)?.[1] || "";
    const trig = /^triggers:\s*\[(.*)\]/m.exec(md)?.[1] || "";
    setFieldDraft({
      description: desc.replace(/^["']|["']$/g, "").trim(),
      triggers: trig
        .split(",")
        .map((s) => s.replace(/^\s*["']?|["']?\s*$/g, ""))
        .filter(Boolean)
        .join(", "),
    });
  }, [detail]);
```

- [ ] **Step 3: Save/review handlers**

Add after `handleProbe` (line ~342). These apply a `FdeStagedMutationResult` back into `detail` so the report + gates re-render from one response:

```tsx
  const applyMutation = useCallback(
    (res: { staged: FdeStagedDetail; selfcheck: FdeSelfcheckResult }) => {
      setDetail({ ...res.staged, selfcheck: res.selfcheck });
    },
    [],
  );

  const handleSaveFields = useCallback(async () => {
    if (!selectedName) return;
    setBusy("save-fields");
    try {
      const env = selectedName ? envByName[selectedName] : undefined;
      const res = await fdeApi.editStagedFields(selectedName, {
        description: fieldDraft.description,
        triggers: fieldDraft.triggers
          .split(",")
          .map((s) => s.trim())
          .filter(Boolean),
        env,
      });
      applyMutation(res);
      setNotice({ type: "success", message: "已保存并重新自检。" });
    } catch (error) {
      setNotice({ type: "error", message: `保存失败：${errMsg(error)}` });
    } finally {
      setBusy(null);
    }
  }, [selectedName, fieldDraft, envByName, applyMutation]);

  const handleSaveCode = useCallback(async () => {
    if (!selectedName) return;
    const files = Object.entries(codeEdits).map(([path, content]) => ({
      path,
      content,
    }));
    if (files.length === 0) {
      setNotice({ type: "info", message: "没有改动的文件。" });
      return;
    }
    setBusy("save-code");
    try {
      const res = await fdeApi.editStagedFiles(selectedName, files);
      applyMutation(res);
      setCodeEdits({});
      setNotice({ type: "success", message: "代码已保存并重新自检。" });
    } catch (error) {
      setNotice({ type: "error", message: `保存失败：${errMsg(error)}` });
    } finally {
      setBusy(null);
    }
  }, [selectedName, codeEdits, applyMutation]);

  const handleReview = useCallback(
    async (action: "approve" | "reset") => {
      if (!selectedName) return;
      setBusy(`review-${action}`);
      try {
        const res = await fdeApi.reviewStaged(selectedName, action);
        applyMutation(res);
        setNotice({
          type: "success",
          message: action === "approve" ? "已标记审查通过。" : "已撤回审查。",
        });
      } catch (error) {
        setNotice({ type: "error", message: `操作失败：${errMsg(error)}` });
      } finally {
        setBusy(null);
      }
    },
    [selectedName, applyMutation],
  );
```

- [ ] **Step 4: Replace the right-column detail block**

Replace the entire `) : (` … `</>` detail branch (lines ~1093-1305, the `<>...</>` after `!detail ?`) with the Layout A structure: status strip (name + install target + 2 gate badges), tab bar, tab panels (概览 = SelfcheckReport + guided fields; 代码 = tree + textarea; 试跑 = probe), and a sticky footer. Keep the existing `agentOptions` select, `envFields`/`updateEnvValue`, `handleProbe`, `handleDiscard`, `runInstall` wiring.

```tsx
            <section className="fde-section fde-board">
              {/* 常驻状态条 */}
              <div className="fde-strip">
                <span className="fde-strip-name">{detail.skill_name}</span>
                <label className="fde-install-target">
                  安装到
                  <select
                    className="fde-field"
                    value={installTarget || targetWorkspace}
                    onChange={(e) => {
                      if (e.target.value === NEW_AGENT_SENTINEL) {
                        setCreateAgentFor("install");
                      } else {
                        setInstallTarget(e.target.value);
                      }
                    }}
                  >
                    {agentOptions(installTarget || targetWorkspace)}
                  </select>
                </label>
                <span className="fde-strip-gap" />
                <span
                  className={`fde-gate ${aiOk ? "is-ok" : "is-bad"}`}
                  title="AI 自检（域审查 + 安全扫描 + 语法）"
                >
                  AI自检 {aiOk ? "✓ 通过" : "✗ 未过"}
                </span>
                <span
                  className={`fde-gate ${
                    reviewOk
                      ? "is-ok"
                      : review?.effective === "stale"
                        ? "is-warn"
                        : "is-wait"
                  }`}
                  title="人工审查闸门"
                >
                  人工审查{" "}
                  {reviewOk
                    ? "✓ 通过"
                    : review?.effective === "stale"
                      ? "⚠ 已失效"
                      : "○ 待审"}
                </span>
              </div>

              {/* Tabs */}
              <div className="fde-tabs">
                {(
                  [
                    ["overview", "概览"],
                    ["code", `代码 · ${detail.files.length}`],
                    ["probe", "试跑"],
                  ] as const
                ).map(([key, label]) => (
                  <button
                    key={key}
                    type="button"
                    className={`fde-tab${tab === key ? " is-on" : ""}`}
                    onClick={() => setTab(key)}
                  >
                    {label}
                  </button>
                ))}
              </div>

              {tab === "overview" ? (
                <div className="fde-tabpane">
                  <SelfcheckReport result={detail.selfcheck} />
                  <div className="fde-guide">
                    <div className="fde-guide-head">
                      引导字段
                      <span className="fde-report-hint">
                        改完点「保存并重检」
                      </span>
                    </div>
                    <label className="fde-guide-row">
                      <span className="fde-guide-key">描述</span>
                      <input
                        className="fde-field"
                        value={fieldDraft.description}
                        onChange={(e) =>
                          setFieldDraft((d) => ({
                            ...d,
                            description: e.target.value,
                          }))
                        }
                      />
                    </label>
                    <label className="fde-guide-row">
                      <span className="fde-guide-key">触发词</span>
                      <input
                        className="fde-field"
                        placeholder="逗号分隔"
                        value={fieldDraft.triggers}
                        onChange={(e) =>
                          setFieldDraft((d) => ({
                            ...d,
                            triggers: e.target.value,
                          }))
                        }
                      />
                    </label>
                    {envFields.map((field) => (
                      <label className="fde-guide-row" key={field.key}>
                        <span className="fde-guide-key">{field.key}</span>
                        <input
                          className="fde-field"
                          type={
                            /token|secret|password|cookie|key|auth/i.test(
                              field.key,
                            )
                              ? "password"
                              : "text"
                          }
                          placeholder={
                            field.default || "（留空表示暂不配置）"
                          }
                          value={envValuesForSelected[field.key] || ""}
                          onChange={(e) =>
                            updateEnvValue(field.key, e.target.value)
                          }
                          autoComplete="off"
                          spellCheck={false}
                        />
                      </label>
                    ))}
                  </div>
                </div>
              ) : tab === "code" ? (
                <div className="fde-tabpane fde-code">
                  <div className="fde-code-tree">
                    {detail.files.map((f) => (
                      <button
                        key={f.path}
                        type="button"
                        className={`fde-code-file${
                          activeFile === f.path ? " is-active" : ""
                        }${codeEdits[f.path] != null ? " is-dirty" : ""}`}
                        onClick={() => setActiveFile(f.path)}
                        title={f.path}
                      >
                        {f.path}
                        {codeEdits[f.path] != null ? " ●" : ""}
                      </button>
                    ))}
                  </div>
                  {(() => {
                    const file = detail.files.find(
                      (f) => f.path === activeFile,
                    );
                    const editable =
                      file && !file.binary && !file.truncated;
                    const value =
                      activeFile != null && codeEdits[activeFile] != null
                        ? codeEdits[activeFile]
                        : (activeFileContent ?? "");
                    return (
                      <textarea
                        className="fde-code-edit"
                        value={value}
                        readOnly={!editable}
                        spellCheck={false}
                        onChange={(e) => {
                          if (!activeFile) return;
                          const v = e.target.value;
                          setCodeEdits((prev) => ({
                            ...prev,
                            [activeFile]: v,
                          }));
                        }}
                      />
                    );
                  })()}
                </div>
              ) : (
                <div className="fde-tabpane">
                  <button
                    type="button"
                    className="fde-btn fde-btn--ghost"
                    onClick={() => void handleProbe()}
                    disabled={busy === "probe"}
                  >
                    <i
                      className={`fas ${
                        busy === "probe" ? "fa-spinner fa-spin" : "fa-play"
                      }`}
                    />
                    {busy === "probe" ? "试跑中…" : "沙箱试跑 diagnose"}
                  </button>
                  {probe ? (
                    <div
                      className={`fde-terminal${probe.ok ? "" : " is-error"}`}
                    >
                      <pre>
                        {probe.ok
                          ? probe.stdout || "(无输出)"
                          : probe.error ||
                            probe.stderr ||
                            probe.stdout ||
                            "(失败，无输出)"}
                      </pre>
                    </div>
                  ) : null}
                </div>
              )}

              {/* Sticky footer：双闸门 + 安装 */}
              <div className="fde-foot">
                <button
                  type="button"
                  className="fde-btn fde-btn--ghost"
                  onClick={() =>
                    void (tab === "code"
                      ? handleSaveCode()
                      : handleSaveFields())
                  }
                  disabled={busy === "save-fields" || busy === "save-code"}
                >
                  {busy === "save-fields" || busy === "save-code"
                    ? "保存中…"
                    : "保存并重检"}
                </button>
                <span className="fde-foot-gap" />
                {reviewOk ? (
                  <button
                    type="button"
                    className="fde-btn fde-btn--ghost"
                    onClick={() => void handleReview("reset")}
                    disabled={busy === "review-reset"}
                  >
                    撤回审查
                  </button>
                ) : (
                  <button
                    type="button"
                    className="fde-btn fde-btn--warn"
                    onClick={() => void handleReview("approve")}
                    disabled={busy === "review-approve" || !aiOk}
                    title={aiOk ? undefined : "AI 自检未通过，先修正"}
                  >
                    {busy === "review-approve" ? "标记中…" : "审查通过 ▸"}
                  </button>
                )}
                <button
                  type="button"
                  className="fde-btn fde-btn--primary"
                  onClick={() => void handleInstall()}
                  disabled={
                    busy === "install" ||
                    busy === "install-force" ||
                    !aiOk ||
                    !reviewOk
                  }
                  title={
                    !aiOk
                      ? "AI 自检未通过"
                      : !reviewOk
                        ? "人工审查未通过"
                        : undefined
                  }
                >
                  {busy === "install"
                    ? "安装中…"
                    : `确认安装到 ${installTarget || targetWorkspace || "?"}`}
                </button>
                {domainBlocked ? (
                  <button
                    type="button"
                    className="fde-btn fde-btn--warn"
                    onClick={() => void handleForceInstall()}
                    disabled={busy === "install" || busy === "install-force"}
                  >
                    {busy === "install-force"
                      ? "强制安装中…"
                      : "强制安装（领域审核暂不可用）"}
                  </button>
                ) : null}
                <button
                  type="button"
                  className="fde-btn fde-btn--danger"
                  onClick={() => void handleDiscard()}
                  disabled={busy === "discard"}
                >
                  丢弃
                </button>
              </div>
            </section>
```

Remove the now-unused `SelfcheckBanner` function (lines 78-125) and its usage; `SelfcheckReport` replaces it. Leave `currentStep`/`PIPELINE_STEPS` as-is (top pipeline strip unaffected).

- [ ] **Step 5: Append CSS** to `portal/src/pages/fde-workbench.css`

```css
/* --- Layout A：状态条 / Tabs / 引导字段 / 编辑器 / 底栏 --- */
.fde-strip { display: flex; align-items: center; gap: 10px;
  flex-wrap: wrap; padding-bottom: 8px; }
.fde-strip-name { font-weight: 700; font-size: 14px; }
.fde-strip-gap { flex: 1; }
.fde-gate { border: 1px solid rgba(128,128,128,.5); border-radius: 999px;
  padding: 2px 10px; font-size: 11px; }
.fde-gate.is-ok { border-color: #3aa76d; color: #3aa76d; }
.fde-gate.is-wait { border-color: #c89a2b; color: #c89a2b; }
.fde-gate.is-warn { border-color: #e0a82e; color: #e0a82e; }
.fde-gate.is-bad { border-color: #d9534f; color: #d9534f; }
.fde-tabs { display: flex; gap: 2px; border-bottom: 1px solid
  rgba(128,128,128,.4); margin-bottom: 10px; }
.fde-tab { padding: 5px 14px; border: 1px solid transparent;
  border-bottom: none; border-radius: 8px 8px 0 0; font-size: 12px;
  opacity: .7; background: none; cursor: pointer; }
.fde-tab.is-on { background: rgba(128,128,128,.14);
  border-color: rgba(128,128,128,.4); opacity: 1; font-weight: 600; }
.fde-tabpane { display: flex; flex-direction: column; gap: 12px; }
.fde-guide { border: 1px solid rgba(128,128,128,.4); border-radius: 10px;
  padding: 10px 12px; display: flex; flex-direction: column; gap: 8px; }
.fde-guide-head { display: flex; justify-content: space-between;
  align-items: center; font-weight: 600; font-size: 12px; }
.fde-guide-row { display: flex; gap: 8px; align-items: center; }
.fde-guide-key { width: 96px; flex: none; font-size: 11px; opacity: .7;
  font-family: ui-monospace, monospace; }
.fde-code-edit { flex: 1; min-height: 320px; width: 100%; resize: vertical;
  font-family: ui-monospace, Menlo, Consolas, monospace; font-size: 12px;
  line-height: 1.5; padding: 10px; border: 1px solid rgba(128,128,128,.4);
  border-radius: 8px; background: var(--fde-code-bg, rgba(0,0,0,.18)); }
.fde-code-file.is-dirty { color: #c89a2b; }
.fde-foot { position: sticky; bottom: 0; display: flex; align-items: center;
  gap: 8px; padding: 10px 0 2px; margin-top: 10px;
  border-top: 1px solid rgba(128,128,128,.4);
  background: var(--fde-panel-bg, inherit); }
.fde-foot-gap { flex: 1; }
```

- [ ] **Step 6: Typecheck + build**

Run: `cd portal && pnpm build`
Expected: tsc passes, build succeeds. Fix any unused-import/type errors (e.g. drop `FdeSelfcheckResult` import if no longer referenced after removing `SelfcheckBanner`, keep it if `applyMutation` signature uses it).

- [ ] **Step 7: Commit**

```bash
git add portal/src/pages/digital-employee/fdeWorkbenchPanel.tsx portal/src/pages/fde-workbench.css
git commit -m "feat(portal): FDE workbench Layout A — gates, tabs, inline edit, review footer"
```

---

## Phase 6 — integration verification

### Task 6.1: sync, run full backend suite, build portal, click-through

- [ ] **Step 1: Full extensions test run**

Run: `.venv/bin/python -m pytest tests/unit/extensions/api/ -v`
Expected: all green (new + existing). If `test_fde_workbench.py` shows order sensitivity, also run it alone: `.venv/bin/python -m pytest tests/unit/extensions/api/test_fde_workbench.py -v`.

- [ ] **Step 2: Pre-commit**

Run: `pre-commit run --all-files` (black 79 / flake8 / mypy on changed py). Re-stage and rerun until clean.

- [ ] **Step 3: Sync workspace runtime so the live backend picks up the enriched `_scan()`**

Run: `./sync-qwenpaw-working.sh` then restart the backend (the enriched finding fields only reach the running app after the `fde` workspace runtime is synced). Portal: ensure `pnpm build` artifact / dev server reloaded.

- [ ] **Step 4: Manual click-through** (the real proof)

Generate or select a staged skill → 概览 shows findings with snippet/修复建议; edit 描述/触发词 → 保存并重检 → report refreshes, 人工审查 badge stays ○; 代码 tab → edit a file → 保存并重检; click 审查通过 → badge turns ✓ and 确认安装 enables; edit again → 审查 badge flips to ⚠已失效 and 确认安装 disables; install succeeds only with both gates green.

- [ ] **Step 5: Final commit (if pre-commit reformatted anything)**

```bash
git add -A
git commit -m "chore(fde): lint/format pass for review-edit-scan feature"
```

---

## Self-Review

**Spec coverage:**
- 缺口B (rich findings) → Task 1.1 + SelfcheckReport (5.2). ✓
- 缺口A 引导字段 → `edit_staged_fields` (3.4) + guided fields UI (5.3); 高级直改 → `edit_staged_files` (3.4) + code textarea (5.3). ✓
- 缺口C 持久化+digest → digest (2.1), review state (2.2), approve/reset (4.1); install gate (4.2); gate badges + footer (5.3). ✓
- D4 secret-emptying → `_update_env_example` (3.2). ✓
- Path-safety → `_safe_staged_target` (3.3). ✓
- Routes + models → 4.3 / 4.4. ✓
- State machine (edit → stale → re-review) → tested in 2.2 + 4.2; UI in 5.3. ✓
- Out of scope (工作面二, per-file marks) → not planned, correct. ✓

**Placeholder scan:** No TBD/"handle errors"/"similar to" — every code step is complete. ✓

**Type/name consistency:** `_staged_content_digest`, `_load_staged_meta`/`_save_staged_meta`, `_review_state`, `_rewrite_frontmatter`, `_render_fm_line`/`_yaml_dq`, `_is_secret_env_key`/`_update_env_example`, `_safe_staged_target`, `edit_staged_fields`/`edit_staged_files`, `staged_detail_with_review`/`_mutation_result`, `set_staged_review`, `_now_iso` — referenced consistently across tasks. Frontend: `editStagedFields`/`editStagedFiles`/`reviewStaged`, `FdeReviewState`/`FdeScanFinding`/`FdeStagedMutationResult`, `SelfcheckReport`, `applyMutation` — consistent. The install gate's `meta` variable remains in scope for the rest of `install_staged_skill` (target_workspace = meta.get(...)). ✓

**One risk flagged for execution:** Task 4.2 makes ~9 existing install tests depend on `set_staged_review(..., "approve")`, which runs a real `selfcheck_staged_skill` subprocess (domain LLM unavailable → `ready_for_review` stays true, so it passes offline — same path the existing lifecycle test already relies on). If the test host can't run the fde_tools subprocess at all, the *existing* suite was already failing; this plan doesn't add a new external dependency beyond what `generate_skill` already needs.
