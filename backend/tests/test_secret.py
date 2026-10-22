"""站点密钥与分享 token（issue #114）。"""

import os

import pytest
from pathlib import Path

from app.runtime.secret import load_secret, share_token, verify_share_token


def test_env_wins(tmp_path: Path) -> None:
    key = "k" * 40
    assert load_secret(tmp_path, env={"AGENTHOWL_SECRET_KEY": f" {key}\n"}) == key.encode()
    assert not (tmp_path / "secret.key").exists()


def test_generated_and_persisted_0600(tmp_path: Path) -> None:
    a = load_secret(tmp_path, env={})
    assert len(a) == 64 and int(a, 16) >= 0  # 64 位 hex 文本
    path = tmp_path / "secret.key"
    assert oct(os.stat(path).st_mode & 0o777) == "0o600"
    assert load_secret(tmp_path, env={}) == a  # 第二次读文件


def test_binary_key_with_newlines_not_stripped(tmp_path: Path) -> None:
    key = b"\n" + bytes(range(1, 31)) + b"\n"
    (tmp_path / "secret.key").write_bytes(key)
    assert load_secret(tmp_path, env={}) == key
    assert load_secret(tmp_path, env={}) == key


def test_short_or_empty_secret_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="站点密钥过短"):
        load_secret(tmp_path, env={"AGENTHOWL_SECRET_KEY": "abc"})
    (tmp_path / "secret.key").write_bytes(b"")
    with pytest.raises(ValueError, match="站点密钥过短"):
        load_secret(tmp_path, env={})


def test_share_token_stable_and_verifies() -> None:
    t = share_token(b"k", "g_1")
    assert len(t) == 32 and t == share_token(b"k", "g_1")
    assert t != share_token(b"k", "g_2") and t != share_token(b"k2", "g_1")
    assert verify_share_token(b"k", "g_1", t)
    assert not verify_share_token(b"k", "g_1", t[:-1] + "0")
    assert not verify_share_token(b"k", "g_1", "")


def test_verify_rejects_non_ascii_and_wrong_length() -> None:
    assert not verify_share_token(b"k", "g_1", "é" * 32)
    assert not verify_share_token(b"k", "g_1", "x" * 31)
