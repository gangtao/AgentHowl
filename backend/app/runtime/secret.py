"""站点密钥（issue #114）：只用于派生分享 token。环境变量 > data/secret.key > 生成落盘（0600）。"""

from __future__ import annotations

import hmac
import logging
import os
import secrets
from collections.abc import Mapping
from pathlib import Path

logger = logging.getLogger(__name__)

SECRET_ENV = "AGENTHOWL_SECRET_KEY"
SECRET_FILE = "secret.key"
SHARE_TOKEN_LEN = 32
MIN_SECRET_LEN = 32


def load_secret(data_dir: Path, *, env: Mapping[str, str] | None = None) -> bytes:
    """环境变量（strip 后）> data/secret.key（原样字节，绝不 strip）> 生成 token_hex(32) 文本落盘（0600）。

    两个来源都须至少 32 字节，否则启动即抛 ValueError（短密钥可被伪造 HMAC）。
    """
    environ = os.environ if env is None else env
    raw = environ.get(SECRET_ENV, "").strip()
    if raw:
        return _check_len(raw.encode("utf-8"))
    path = data_dir / SECRET_FILE
    if path.exists():
        return _check_len(path.read_bytes())
    data_dir.mkdir(parents=True, exist_ok=True)
    key = secrets.token_hex(32).encode("ascii")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(key)
    logger.info("已生成站点密钥 %s（分享链接签名用）", path)
    return key


def _check_len(key: bytes) -> bytes:
    if len(key) < MIN_SECRET_LEN:
        raise ValueError("站点密钥过短：AGENTHOWL_SECRET_KEY 或 data/secret.key 须至少 32 字节")
    return key


def share_token(secret: bytes, game_id: str) -> str:
    return hmac.new(secret, f"share:{game_id}".encode(), "sha256").hexdigest()[:SHARE_TOKEN_LEN]


def verify_share_token(secret: bytes, game_id: str, token: str) -> bool:
    """按 bytes 比较：compare_digest 对非 ASCII str 会抛 TypeError。"""
    expected = share_token(secret, game_id).encode()
    return bool(token) and hmac.compare_digest(expected, token.encode())
