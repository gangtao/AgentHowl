"""站点密钥与分享 token（issue #114）。"""

import os
from pathlib import Path

from app.runtime.secret import load_secret, share_token, verify_share_token


def test_env_wins(tmp_path: Path) -> None:
    assert load_secret(tmp_path, env={"AGENTHOWL_SECRET_KEY": "abc"}) == b"abc"
    assert not (tmp_path / "secret.key").exists()


def test_generated_and_persisted_0600(tmp_path: Path) -> None:
    a = load_secret(tmp_path, env={})
    assert len(a) == 32
    path = tmp_path / "secret.key"
    assert oct(os.stat(path).st_mode & 0o777) == "0o600"
    assert load_secret(tmp_path, env={}) == a  # 第二次读文件


def test_share_token_stable_and_verifies() -> None:
    t = share_token(b"k", "g_1")
    assert len(t) == 32 and t == share_token(b"k", "g_1")
    assert t != share_token(b"k", "g_2") and t != share_token(b"k2", "g_1")
    assert verify_share_token(b"k", "g_1", t)
    assert not verify_share_token(b"k", "g_1", t[:-1] + "0")
    assert not verify_share_token(b"k", "g_1", "")
