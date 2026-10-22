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


def load_secret(data_dir: Path, *, env: Mapping[str, str] | None = None) -> bytes:
    environ = os.environ if env is None else env
    raw = environ.get(SECRET_ENV, "").strip()
    if raw:
        return raw.encode("utf-8")
    path = data_dir / SECRET_FILE
    if path.exists():
        return path.read_bytes().strip()
    data_dir.mkdir(parents=True, exist_ok=True)
    key = secrets.token_bytes(32)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(key)
    logger.info("已生成站点密钥 %s（分享链接签名用）", path)
    return key


def share_token(secret: bytes, game_id: str) -> str:
    return hmac.new(secret, f"share:{game_id}".encode(), "sha256").hexdigest()[:SHARE_TOKEN_LEN]


def verify_share_token(secret: bytes, game_id: str, token: str) -> bool:
    return bool(token) and hmac.compare_digest(share_token(secret, game_id), token)
