#!/usr/bin/env bash
set -euo pipefail

# Fix and verify knowledge-base skill Python dependencies in the QwenPaw env.
#
# Common container usage:
#   bash scripts/fix_knowledge_base_deps.sh
#
# Check imports without installing:
#   bash scripts/fix_knowledge_base_deps.sh --check-only
#
# Optional overrides:
#   QWENPAW_PYTHON=/app/venv/bin/python
#   QWENPAW_KNOWLEDGE_BASE_SKILL_ROOT=/app/working/workspaces/knowledge/skills/knowledge-base
#   PYPI_MIRROR=https://mirrors.aliyun.com/pypi/simple

usage() {
  cat <<'EOF'
Usage:
  bash scripts/fix_knowledge_base_deps.sh [--check-only]

Installs knowledge-base/requirements.txt into the Python environment running QwenPaw,
then verifies imports for jieba, sqlite_vec, tiktoken, and api.serializers.

Options:
  --check-only   Skip installation and only verify imports.
  -h, --help     Show this help.

Environment overrides:
  QWENPAW_PYTHON=/app/venv/bin/python
  QWENPAW_KNOWLEDGE_BASE_SKILL_ROOT=/app/working/workspaces/knowledge/skills/knowledge-base
  PYPI_MIRROR=https://mirrors.aliyun.com/pypi/simple
EOF
}

CHECK_ONLY=0
case "${1:-}" in
  "")
    ;;
  --check-only)
    CHECK_ONLY=1
    ;;
  -h|--help)
    usage
    exit 0
    ;;
  *)
    echo "ERROR: unknown argument: $1" >&2
    usage >&2
    exit 2
    ;;
esac

if [[ $# -gt 1 ]]; then
  echo "ERROR: too many arguments." >&2
  usage >&2
  exit 2
fi

PYPI_MIRROR="${PYPI_MIRROR:-https://mirrors.aliyun.com/pypi/simple}"

pick_python() {
  if [[ -n "${QWENPAW_PYTHON:-}" ]]; then
    printf '%s\n' "$QWENPAW_PYTHON"
  elif [[ -x /app/venv/bin/python ]]; then
    printf '%s\n' /app/venv/bin/python
  elif [[ -x .venv/bin/python ]]; then
    printf '%s\n' .venv/bin/python
  elif [[ -x venv/bin/python ]]; then
    printf '%s\n' venv/bin/python
  elif command -v python3 >/dev/null 2>&1; then
    command -v python3
  else
    return 1
  fi
}

pick_skill_root() {
  if [[ -n "${QWENPAW_KNOWLEDGE_BASE_SKILL_ROOT:-}" ]]; then
    printf '%s\n' "$QWENPAW_KNOWLEDGE_BASE_SKILL_ROOT"
  elif [[ -d /app/working/workspaces/knowledge/skills/knowledge-base ]]; then
    printf '%s\n' /app/working/workspaces/knowledge/skills/knowledge-base
  elif [[ -d deploy-all/qwenpaw/working/workspaces/knowledge/skills/knowledge-base ]]; then
    printf '%s\n' deploy-all/qwenpaw/working/workspaces/knowledge/skills/knowledge-base
  elif [[ -d working/workspaces/knowledge/skills/knowledge-base ]]; then
    printf '%s\n' working/workspaces/knowledge/skills/knowledge-base
  else
    return 1
  fi
}

PYTHON_BIN="$(pick_python)" || {
  echo "ERROR: Python not found. Set QWENPAW_PYTHON=/path/to/python." >&2
  exit 1
}

KB_ROOT="$(pick_skill_root)" || {
  echo "ERROR: knowledge-base skill root not found." >&2
  echo "Set QWENPAW_KNOWLEDGE_BASE_SKILL_ROOT=/app/working/workspaces/knowledge/skills/knowledge-base." >&2
  exit 1
}

REQ_FILE="${KB_ROOT}/requirements.txt"
SERIALIZERS_FILE="${KB_ROOT}/api/serializers.py"

if [[ ! -f "$REQ_FILE" ]]; then
  echo "ERROR: requirements.txt not found: $REQ_FILE" >&2
  exit 1
fi

if [[ ! -f "$SERIALIZERS_FILE" ]]; then
  echo "ERROR: api/serializers.py not found: $SERIALIZERS_FILE" >&2
  echo "This is a deployment content problem. Re-sync the knowledge-base skill files." >&2
  exit 1
fi

echo "Using Python: $PYTHON_BIN"
"$PYTHON_BIN" -c 'import sys; print("Python executable:", sys.executable); print("Python version:", sys.version.replace("\n", " "))'
echo "Using knowledge-base root: $KB_ROOT"

install_args=("--disable-pip-version-check" "--no-input" "-r" "$REQ_FILE")
uv_args=("-r" "$REQ_FILE")

if [[ -n "${PYPI_MIRROR:-}" ]]; then
  install_args=("--index-url" "$PYPI_MIRROR" "${install_args[@]}")
  uv_args=("--index-url" "$PYPI_MIRROR" "${uv_args[@]}")
fi

if [[ "$CHECK_ONLY" -eq 1 ]]; then
  echo "Check-only mode: skipping dependency installation."
else
  if "$PYTHON_BIN" -m pip --version >/dev/null 2>&1; then
    echo "Installing requirements with pip..."
    "$PYTHON_BIN" -m pip install "${install_args[@]}"
  else
    if command -v uv >/dev/null 2>&1; then
      UV_BIN="$(command -v uv)"
    elif [[ -x /bin/uv ]]; then
      UV_BIN=/bin/uv
    else
      echo "ERROR: pip is unavailable and uv was not found." >&2
      echo "Install pip/uv or run uv pip install --python \"$PYTHON_BIN\" -r \"$REQ_FILE\" manually." >&2
      exit 1
    fi
    echo "pip unavailable; installing requirements with uv: $UV_BIN"
    "$UV_BIN" pip install --python "$PYTHON_BIN" "${uv_args[@]}"
  fi
fi

export KB_ROOT_FOR_CHECK="$KB_ROOT"
"$PYTHON_BIN" - <<'PY'
import importlib
import os
import sys
from pathlib import Path

root = Path(os.environ["KB_ROOT_FOR_CHECK"]).resolve()
sys.path.insert(0, str(root))

for module_name in ["jieba", "sqlite_vec", "tiktoken", "pypdf", "docx", "PIL", "pytesseract"]:
    module = importlib.import_module(module_name)
    location = getattr(module, "__file__", "<built-in>")
    print(f"OK import {module_name}: {location}")

from api import serializers

print(f"OK import api.serializers: {serializers.__file__}")
assert hasattr(serializers, "serialize_query_response")
PY

echo "Knowledge-base dependencies and serializers import verified."
echo "Restart QwenPaw after this script if the service was already running."
