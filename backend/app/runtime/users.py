"""用户、会话与邮箱验证码（issue #114）。IO 层：标准库 sqlite3，零新依赖。

密码：scrypt(n=2**14, r=8, p=1, dklen=32) + 16 字节随机盐，格式
``scrypt$<n>$<r>$<p>$<salt_b64>$<hash_b64>``。password_hash 永不进响应 / 日志（repr=False）。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import re
import secrets
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

USERNAME_RE = re.compile(r"^[a-z0-9_]{3,32}$")
MAX_EMAIL_LEN = 254
MIN_PASSWORD_LEN = 8
MAX_PASSWORD_LEN = 128
SCRYPT_N = 2**14
SCRYPT_R = 8
SCRYPT_P = 1
SESSION_TTL = timedelta(days=30)
EMAIL_CODE_TTL = timedelta(minutes=15)
EMAIL_CODE_MAX_ATTEMPTS = 5

Role = Literal["admin", "user"]
Status = Literal["active", "disabled"]


class UserConflictError(ValueError):
    """用户名或邮箱已被占用。"""


class User(BaseModel):
    model_config = ConfigDict(frozen=True)

    user_id: str
    username: str
    email: str
    password_hash: str = Field(repr=False)
    role: Role = "user"
    status: Status = "active"
    email_verified_at: str | None = None
    created_at: str

    def public(self) -> UserPublic:
        return UserPublic(
            user_id=self.user_id,
            username=self.username,
            email=self.email,
            role=self.role,
            status=self.status,
            email_verified=self.email_verified_at is not None,
            created_at=self.created_at,
        )


class UserPublic(BaseModel):
    """API 响应：永不含 password_hash。"""

    model_config = ConfigDict(frozen=True)

    user_id: str
    username: str
    email: str
    role: Role
    status: Status
    email_verified: bool
    created_at: str


class Session(BaseModel):
    model_config = ConfigDict(frozen=True)

    session_id: str = Field(repr=False)
    user_id: str
    created_at: str
    expires_at: str


class EmailCode(BaseModel):
    model_config = ConfigDict(frozen=True)

    user_id: str
    code_hash: str = Field(repr=False)
    expires_at: str
    attempts: int = 0


# ---------- 工具 ----------


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _iso_after(delta: timedelta) -> str:
    return (datetime.now(UTC) + delta).isoformat(timespec="seconds")


def is_expired(iso: str) -> bool:
    return datetime.fromisoformat(iso) <= datetime.now(UTC)


def new_user_id() -> str:
    return f"u_{secrets.token_hex(4)}"


def new_session(user_id: str) -> Session:
    return Session(
        session_id=secrets.token_urlsafe(32),
        user_id=user_id,
        created_at=now_iso(),
        expires_at=_iso_after(SESSION_TTL),
    )


def new_email_code(user_id: str) -> tuple[str, EmailCode]:
    """返回 (明文 6 位码, 入库记录)。明文只用于发邮件。"""
    code = f"{secrets.randbelow(1_000_000):06d}"
    return code, EmailCode(
        user_id=user_id, code_hash=hash_code(code), expires_at=_iso_after(EMAIL_CODE_TTL)
    )


def hash_code(code: str) -> str:
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def normalize_username(raw: str) -> str:
    return raw.strip().lower()


def normalize_email(raw: str) -> str:
    return raw.strip().lower()


def validate_username(username: str) -> None:
    if not USERNAME_RE.fullmatch(username):
        raise ValueError("用户名须为 3–32 位小写字母、数字或下划线")


def validate_email(email: str) -> None:
    if not email or len(email) > MAX_EMAIL_LEN or "@" not in email:
        raise ValueError("邮箱格式不正确")


def validate_password(password: str) -> None:
    if not (MIN_PASSWORD_LEN <= len(password) <= MAX_PASSWORD_LEN):
        raise ValueError(f"密码长度须在 {MIN_PASSWORD_LEN}–{MAX_PASSWORD_LEN} 个字符之间")


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, dklen=32
    )
    return "$".join(
        (
            "scrypt",
            str(SCRYPT_N),
            str(SCRYPT_R),
            str(SCRYPT_P),
            base64.b64encode(salt).decode("ascii"),
            base64.b64encode(digest).decode("ascii"),
        )
    )


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, n, r, p, salt_b64, hash_b64 = stored.split("$")
        if algo != "scrypt":
            return False
        salt = base64.b64decode(salt_b64, validate=True)
        expected = base64.b64decode(hash_b64, validate=True)
        digest = hashlib.scrypt(
            password.encode("utf-8"), salt=salt, n=int(n), r=int(r), p=int(p), dklen=len(expected)
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(digest, expected)


# ---------- 存储 ----------


class UserStore(Protocol):
    def get(self, user_id: str) -> User | None: ...
    def get_by_username(self, username: str) -> User | None: ...
    def get_by_email(self, email: str) -> User | None: ...
    def list(self) -> list[User]: ...
    def put(self, user: User) -> None: ...
    def count(self) -> int: ...
    def create_session(self, session: Session) -> None: ...
    def get_session(self, session_id: str) -> Session | None: ...
    def delete_session(self, session_id: str) -> None: ...
    def delete_sessions_of(self, user_id: str) -> None: ...
    def put_email_code(self, code: EmailCode) -> None: ...
    def get_email_code(self, user_id: str) -> EmailCode | None: ...
    def delete_email_code(self, user_id: str) -> None: ...


class InMemoryUserStore:
    def __init__(self) -> None:
        self._users: dict[str, User] = {}
        self._sessions: dict[str, Session] = {}
        self._codes: dict[str, EmailCode] = {}

    def get(self, user_id: str) -> User | None:
        return self._users.get(user_id)

    def get_by_username(self, username: str) -> User | None:
        return next((u for u in self._users.values() if u.username == username), None)

    def get_by_email(self, email: str) -> User | None:
        return next((u for u in self._users.values() if u.email == email), None)

    def list(self) -> list[User]:
        return sorted(self._users.values(), key=lambda u: (u.created_at, u.user_id))

    def put(self, user: User) -> None:
        for other in self._users.values():
            if other.user_id != user.user_id and (
                other.username == user.username or other.email == user.email
            ):
                raise UserConflictError("用户名或邮箱已被占用")
        self._users[user.user_id] = user

    def count(self) -> int:
        return len(self._users)

    def create_session(self, session: Session) -> None:
        self._sessions[session.session_id] = session

    def get_session(self, session_id: str) -> Session | None:
        s = self._sessions.get(session_id)
        if s is None:
            return None
        if is_expired(s.expires_at):
            del self._sessions[session_id]
            return None
        return s

    def delete_session(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)

    def delete_sessions_of(self, user_id: str) -> None:
        for sid in [k for k, s in self._sessions.items() if s.user_id == user_id]:
            del self._sessions[sid]

    def put_email_code(self, code: EmailCode) -> None:
        self._codes[code.user_id] = code

    def get_email_code(self, user_id: str) -> EmailCode | None:
        return self._codes.get(user_id)

    def delete_email_code(self, user_id: str) -> None:
        self._codes.pop(user_id, None)


_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  user_id TEXT PRIMARY KEY,
  username TEXT NOT NULL UNIQUE,
  email TEXT NOT NULL UNIQUE,
  password_hash TEXT NOT NULL,
  role TEXT NOT NULL,
  status TEXT NOT NULL,
  email_verified_at TEXT,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
  session_id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  created_at TEXT NOT NULL,
  expires_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS sessions_user ON sessions(user_id);
CREATE TABLE IF NOT EXISTS email_codes (
  user_id TEXT PRIMARY KEY,
  code_hash TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  attempts INTEGER NOT NULL DEFAULT 0
);
"""

_USER_COLS = "user_id, username, email, password_hash, role, status, email_verified_at, created_at"


def _row_user(row: sqlite3.Row) -> User:
    return User(
        user_id=row["user_id"],
        username=row["username"],
        email=row["email"],
        password_hash=row["password_hash"],
        role=row["role"],
        status=row["status"],
        email_verified_at=row["email_verified_at"],
        created_at=row["created_at"],
    )


class SqliteUserStore:
    """每次调用开关连接（单进程低频写，省掉线程问题）；文件 0600。"""

    def __init__(self, path: Path) -> None:
        self._path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as conn:
            conn.executescript(_SCHEMA)
        os.chmod(path, 0o600)

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self._path)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _one(self, sql: str, args: tuple[object, ...]) -> User | None:
        with self._conn() as conn:
            row = conn.execute(sql, args).fetchone()
        return None if row is None else _row_user(row)

    def get(self, user_id: str) -> User | None:
        return self._one(f"SELECT {_USER_COLS} FROM users WHERE user_id=?", (user_id,))

    def get_by_username(self, username: str) -> User | None:
        return self._one(f"SELECT {_USER_COLS} FROM users WHERE username=?", (username,))

    def get_by_email(self, email: str) -> User | None:
        return self._one(f"SELECT {_USER_COLS} FROM users WHERE email=?", (email,))

    def list(self) -> list[User]:
        with self._conn() as conn:
            rows = conn.execute(
                f"SELECT {_USER_COLS} FROM users ORDER BY created_at, user_id"
            ).fetchall()
        return [_row_user(r) for r in rows]

    def put(self, user: User) -> None:
        with self._conn() as conn:
            clash = conn.execute(
                "SELECT 1 FROM users WHERE (username=? OR email=?) AND user_id<>?",
                (user.username, user.email, user.user_id),
            ).fetchone()
            if clash is not None:
                raise UserConflictError("用户名或邮箱已被占用")
            conn.execute(
                f"INSERT INTO users ({_USER_COLS}) VALUES (?,?,?,?,?,?,?,?) "
                "ON CONFLICT(user_id) DO UPDATE SET username=excluded.username, "
                "email=excluded.email, password_hash=excluded.password_hash, role=excluded.role, "
                "status=excluded.status, email_verified_at=excluded.email_verified_at",
                (
                    user.user_id,
                    user.username,
                    user.email,
                    user.password_hash,
                    user.role,
                    user.status,
                    user.email_verified_at,
                    user.created_at,
                ),
            )

    def count(self) -> int:
        with self._conn() as conn:
            n = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        return int(n)

    def create_session(self, session: Session) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO sessions VALUES (?,?,?,?)",
                (session.session_id, session.user_id, session.created_at, session.expires_at),
            )

    def get_session(self, session_id: str) -> Session | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT session_id, user_id, created_at, expires_at FROM sessions "
                "WHERE session_id=?",
                (session_id,),
            ).fetchone()
            if row is None:
                return None
            if is_expired(row["expires_at"]):
                conn.execute("DELETE FROM sessions WHERE session_id=?", (session_id,))
                return None
        return Session(
            session_id=row["session_id"],
            user_id=row["user_id"],
            created_at=row["created_at"],
            expires_at=row["expires_at"],
        )

    def delete_session(self, session_id: str) -> None:
        with self._conn() as conn:
            conn.execute("DELETE FROM sessions WHERE session_id=?", (session_id,))

    def delete_sessions_of(self, user_id: str) -> None:
        with self._conn() as conn:
            conn.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))

    def put_email_code(self, code: EmailCode) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO email_codes VALUES (?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET "
                "code_hash=excluded.code_hash, expires_at=excluded.expires_at, "
                "attempts=excluded.attempts",
                (code.user_id, code.code_hash, code.expires_at, code.attempts),
            )

    def get_email_code(self, user_id: str) -> EmailCode | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT user_id, code_hash, expires_at, attempts FROM email_codes WHERE user_id=?",
                (user_id,),
            ).fetchone()
        if row is None:
            return None
        return EmailCode(
            user_id=row["user_id"],
            code_hash=row["code_hash"],
            expires_at=row["expires_at"],
            attempts=int(row["attempts"]),
        )

    def delete_email_code(self, user_id: str) -> None:
        with self._conn() as conn:
            conn.execute("DELETE FROM email_codes WHERE user_id=?", (user_id,))


def bootstrap_admin(store: UserStore, *, username: str, email: str, password: str) -> User | None:
    """环境变量引导的管理员：用户名已存在 → None（不改密码）；否则创建已验证 admin。"""
    name = normalize_username(username)
    mail = normalize_email(email)
    validate_username(name)
    validate_email(mail)
    validate_password(password)
    if store.get_by_username(name) is not None:
        return None
    user = User(
        user_id=new_user_id(),
        username=name,
        email=mail,
        password_hash=hash_password(password),
        role="admin",
        email_verified_at=now_iso(),
        created_at=now_iso(),
    )
    store.put(user)
    return user
