# -*- coding: utf-8 -*-
"""Tests for the outgoing-message redactor (extensions/security)."""
from __future__ import annotations

import os

import pytest

from qwenpaw.extensions.security.output_guard import redactor
from qwenpaw.extensions.security.output_guard.redactor import (
    OutputGuardSettings,
    mask_value,
    redact,
)


@pytest.fixture(autouse=True)
def _reset_caches():
    redactor.clear_caches()
    yield
    redactor.clear_caches()


# ---------------------------------------------------------------------------
# mask_value
# ---------------------------------------------------------------------------
def test_mask_value_keeps_prefix_suffix():
    out = mask_value("hunter22secret", keep_prefix=4, keep_suffix=2)
    assert out.startswith("hunt")
    assert out.endswith("et")
    assert "*" in out
    assert len(out) == len("hunter22secret")


def test_mask_value_short_string_collapses():
    assert mask_value("abc") == "***"


# ---------------------------------------------------------------------------
# built-in patterns
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "pattern_id,sample,visible,hidden",
    [
        (
            "openai_dashscope_key",
            "key is sk-test1234567890abcdefghijklmn ok",
            "sk-tes",
            "1234567890abcdefghijklm",
        ),
        (
            "anthropic_key",
            "use sk-ant-abcdefghijklmnopqrstuvwx now",
            "sk-ant-ab",
            "efghijklmnopqrstuv",
        ),
        (
            "aliyun_ak_id",
            "ak LTAI4Fabcdefghijkl done",
            "LTAI4F",
            "abcdefghij",
        ),
        (
            "aws_ak_id",
            "id AKIAIOSFODNN7EXAMPLE end",
            "AKIAIO",
            "SFODNN7EXAMP",
        ),
        (
            "github_token",
            "tok ghp_abcdefghijklmnopqrstuvwxyz012345 x",
            "ghp_ab",
            "cdefghijklmnopqrstuvwxyz0123",
        ),
        (
            "bearer_token",
            "Authorization: Bearer abcdef1234567890XYZ",
            "Bearer abcd",
            "ef1234567890X",
        ),
        (
            "kv_secret_assignment",
            "password = hunter22secret",
            "hunt",
            "er22secr",
        ),
        (
            "cn_mobile",
            "联系 13812345678 即可",
            "138",
            "1234",
        ),
    ],
)
def test_builtin_patterns_mask(pattern_id, sample, visible, hidden):
    masked, hits = redact(sample)
    assert pattern_id in hits
    assert visible in masked
    assert hidden not in masked
    assert "*" in masked


def test_pem_private_key_block_fixed_mask():
    # Marker assembled at runtime so the pre-commit
    # detect-private-key hook does not flag this test file.
    begin = "-----BEGIN RSA " + "PRIVATE KEY-----"
    end = "-----END RSA " + "PRIVATE KEY-----"
    text = f"here:\n{begin}\nMIIEpAIBAAKCAQEA7\nmore\n{end}\ndone"
    masked, hits = redact(text)
    assert "pem_private_key" in hits
    assert "[REDACTED PRIVATE KEY]" in masked
    assert "MIIEpAIBAAKCAQEA7" not in masked


def test_jwt_fixed_mask():
    jwt = ".".join(
        ["eyJhbGciOiJIUzI1NiJ9", "eyJzdWIiOiIxIn0", "abcdefghijklmnop"],
    )
    masked, hits = redact(f"token: {jwt}")
    assert "jwt" in hits
    assert "eyJ***.[REDACTED-JWT]" in masked
    assert "eyJzdWIiOiIxIn0" not in masked


def test_db_uri_password_masked():
    masked, hits = redact("dsn=postgres://admin:S3cretPw@db.local:5432/x")
    assert "db_uri_password" in hits
    assert "S3cretPw" not in masked
    assert "admin" in masked  # username stays visible
    assert "db.local" in masked


def test_redact_idempotent():
    sample = (
        "sk-test1234567890abcdefghijklmn and password=hunter22secret "
        "and 13812345678 and postgres://u:topsecret9@h/db"
    )
    once, hits = redact(sample)
    assert hits
    twice, hits2 = redact(once)
    assert twice == once
    assert not hits2


def test_clean_text_untouched():
    text = "网元 NE-01 的 CPU 利用率为 85%，建议扩容。"
    masked, hits = redact(text)
    assert masked == text
    assert not hits


# ---------------------------------------------------------------------------
# settings: disable / off
# ---------------------------------------------------------------------------
def test_disabled_patterns_honored():
    cfg = OutputGuardSettings(disabled_patterns=("kv_secret_assignment",))
    masked, hits = redact("password = hunter22secret", cfg=cfg)
    assert masked == "password = hunter22secret"
    assert not hits


def test_mode_off_passthrough():
    cfg = OutputGuardSettings(mode="off")
    sample = "sk-test1234567890abcdefghijklmn"
    masked, hits = redact(sample, cfg=cfg)
    assert masked == sample
    assert not hits


def test_disabled_passthrough():
    cfg = OutputGuardSettings(enabled=False)
    sample = "sk-test1234567890abcdefghijklmn"
    masked, _ = redact(sample, cfg=cfg)
    assert masked == sample


# ---------------------------------------------------------------------------
# lexicon
# ---------------------------------------------------------------------------
def _write_lexicon(tmp_path, content: str):
    path = tmp_path / "lexicon.yaml"
    path.write_text(content, encoding="utf-8")
    return path


def test_lexicon_literal_word(tmp_path):
    path = _write_lexicon(tmp_path, 'words:\n  - "内部项目天穹"\n')
    cfg = OutputGuardSettings(lexicon_path=str(path))
    masked, hits = redact("关于内部项目天穹的进展", cfg=cfg)
    assert "内部项目天穹" not in masked
    assert any(h.startswith("lexicon:") for h in hits)


def test_lexicon_word_with_custom_mask(tmp_path):
    path = _write_lexicon(
        tmp_path,
        'words:\n  - text: "客户XX集团"\n    mask: "客户***"\n',
    )
    cfg = OutputGuardSettings(lexicon_path=str(path))
    masked, _ = redact("客户XX集团 的工单", cfg=cfg)
    assert "客户***" in masked
    assert "客户XX集团" not in masked


def test_lexicon_regex_styles(tmp_path):
    path = _write_lexicon(
        tmp_path,
        "regexes:\n"
        '  - pattern: "PRJ-\\\\d{4,}"\n'
        "    style: partial\n"
        "    keep_prefix: 4\n"
        '  - pattern: "(?i)contract\\\\s+no\\\\.?\\\\s*\\\\S+"\n'
        "    style: fixed\n"
        '    replacement: "[合同编号已脱敏]"\n',
    )
    cfg = OutputGuardSettings(lexicon_path=str(path))
    masked, _ = redact("PRJ-20260601 and Contract No. ABC-9", cfg=cfg)
    assert "PRJ-" in masked
    assert "20260601" not in masked
    assert "[合同编号已脱敏]" in masked


def test_lexicon_hot_reload(tmp_path):
    path = _write_lexicon(tmp_path, 'words:\n  - "旧词"\n')
    cfg = OutputGuardSettings(lexicon_path=str(path))
    masked, _ = redact("旧词 新词", cfg=cfg)
    assert "旧词" not in masked
    assert "新词" in masked

    path.write_text('words:\n  - "新词"\n', encoding="utf-8")
    st = path.stat()
    os.utime(path, (st.st_atime + 5, st.st_mtime + 5))
    masked, _ = redact("旧词 新词", cfg=cfg)
    assert "旧词" in masked
    assert "新词" not in masked


def test_lexicon_invalid_regex_skipped(tmp_path):
    content = "\n".join(
        ["regexes:", '  - pattern: "([bad"', "words:", '  - "敏感词"', ""],
    )
    path = _write_lexicon(tmp_path, content)
    cfg = OutputGuardSettings(lexicon_path=str(path))
    masked, _ = redact("敏感词 sk-test1234567890abcdefghijklmn", cfg=cfg)
    assert "敏感词" not in masked  # valid entries still applied
    assert "1234567890abcdefghijklm" not in masked  # builtins intact


def test_lexicon_malformed_yaml_fail_open(tmp_path):
    path = _write_lexicon(tmp_path, ": : :\n\t- broken")
    cfg = OutputGuardSettings(lexicon_path=str(path))
    masked, hits = redact("sk-test1234567890abcdefghijklmn", cfg=cfg)
    assert "openai_dashscope_key" in hits
    assert "1234567890abcdefghijklm" not in masked


def test_lexicon_missing_file_fail_open(tmp_path):
    cfg = OutputGuardSettings(lexicon_path=str(tmp_path / "nope.yaml"))
    _, hits = redact("sk-test1234567890abcdefghijklmn", cfg=cfg)
    assert "openai_dashscope_key" in hits


# ---------------------------------------------------------------------------
# streaming tail guard
# ---------------------------------------------------------------------------
def test_tail_guard_masks_partial_key_in_delta():
    text = "你的密钥是 sk-abc"
    masked, hits = redact(text, streaming_tail_guard=True)
    assert "streaming_tail_guard" in hits
    assert not masked.endswith("sk-abc")


def test_tail_guard_inactive_without_flag():
    text = "你的密钥是 sk-abc"
    masked, hits = redact(text)
    assert masked == text
    assert not hits


def test_tail_guard_masks_unfinished_password_assignment():
    masked, hits = redact("config: password=hu", streaming_tail_guard=True)
    assert "streaming_tail_guard" in hits
    assert "password=hu" not in masked
