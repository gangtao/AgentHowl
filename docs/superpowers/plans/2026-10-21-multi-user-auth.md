# 多用户登录与资源归属 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 平台从单用户本机部署变为公网开放注册的多用户站点：注册 / 邮箱验证 / 登录，对局、Agent、Provider 按创建者归属，admin 全权限，分享链接匿名可看。

**Architecture:** 新增用户子系统（`app/runtime/users.py` SQLite 存储 + `app/api/auth.py` cookie 会话与依赖注入），三类实体加 `owner_id`，REST/WS 的视角解析统一为 `resolve_viewer`（对局 token → HMAC 分享 token → 会话归属）。前端加登录态 store 与登录 / 管理页，路由 `?spec=` 改 `?share=`，裸 `#/g/{id}` 走登录态 GM 视角。引擎 `app/engine` 零改动。

**Tech Stack:** Python 3.11 / FastAPI / Pydantic v2 / 标准库 `sqlite3`、`hashlib.scrypt`、`smtplib`、`hmac`；React 18 + TS + Zustand + Vitest。零新依赖。

**Spec:** `docs/superpowers/specs/2026-10-21-multi-user-auth-design.md`

## Global Constraints

- 引擎 `backend/app/engine/` 零改动（`git diff --stat main -- backend/app/engine` 为空）。
- `app/runtime`、`app/api`、`app/cli` 不得模块级 import litellm；守卫 `tests/test_agent_profile.py::test_importing_registry_does_not_load_litellm`。
- 信息隔离只在服务端（`visible_events`）；前端零过滤。
- `password_hash`、`session_id`、验证码明文、provider `api_key` 永不进响应 / 日志 / 异常文案。
- 零新依赖：用户库 `sqlite3`，密码 `hashlib.scrypt(n=2**14, r=8, p=1, dklen=32)`，邮件 `smtplib`，分享 token `hmac.sha256`。
- 用户名 `^[a-z0-9_]{3,32}$`（入库前 `strip().lower()`）；邮箱 `strip().lower()`、含 `@`、≤ 254；密码 8–128 字符。
- 会话 cookie 名 `agenthowl_session`，HttpOnly、SameSite=Lax、Path=/、Max-Age 30 天；`Secure` 由 `AGENTHOWL_COOKIE_SECURE`（默认 `1`）决定。
- 跨 owner 访问一律 **404**；登录失败文案统一「用户名或密码错误」；`/auth/resend` 对不存在 / 已验证邮箱同样 200。
- 文案：中文；代码标识符英文；ruff 100 列；mypy strict。
- 后端命令在 `backend/` 下：`uv run pytest`、`uv run ruff check . && uv run ruff format --check .`、`uv run mypy app`；前端 `frontend/` 下 `npm run check`。
- 提交信息末尾加 `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`，题目带 `(issue #114)`。
- 已知 flaky：`tests/test_api_e2e.py::test_acceptance_human_can_take_any_seat[5]`（#74）；全量跑用 `--ignore=tests/test_api_e2e.py`，e2e 单独跑一次。

## Review Focus

1. **会话 cookie 指向已被禁用 / 删除的用户**：任何请求都应视为未登录（401），且该会话被删除 → Task 3 `test_disabled_user_session_rejected`。
2. **同一用户名大小写 / 首尾空白不同的重复注册**：`Alice ` 与 `alice` 视为同一用户名 → 409 → Task 3 `test_register_normalizes_username_and_email`。
3. **旧数据（无 owner_id）在普通用户视角**：列表不出现、按 id 访问 404，admin 可见 → Task 5 `test_legacy_ownerless_only_admin`，Task 6 `test_legacy_game_only_admin`。
4. **分享 token 在 `allow_spectators=False` 的直播局**：直播期间 403，终局后放行 → Task 6 `test_share_blocked_live_when_spectators_disabled`。
5. **admin 自锁**：最后一个 admin 不能被降级 / 禁用，admin 不能改自己 → Task 8 `test_admin_cannot_lock_itself_out`。

## 文件结构

| 文件 | 职责 |
|---|---|
| `backend/app/runtime/users.py`（新） | User / Session / EmailCode 模型，UserStore Protocol，InMemory + Sqlite 实现，密码哈希，校验与归一化，`bootstrap_admin` |
| `backend/app/runtime/secret.py`（新） | 站点密钥加载 / 生成；`share_token` / `verify_share_token` |
| `backend/app/runtime/ratelimit.py`（新） | 内存滑动窗口限流 |
| `backend/app/runtime/mailer.py`（新） | `MailConfig.from_env`、`Mailer` Protocol、`NullMailer` / `RecordingMailer` / `SmtpMailer` |
| `backend/app/api/auth.py`（新） | `/auth/*` 路由；`current_user` / `require_user` / `require_admin` / `can_access` / `user_from_cookie` |
| `backend/app/api/admin.py`（新） | `/admin/users*` |
| `backend/app/cli/claim.py`（新） | 无主数据划归 |
| `backend/app/api/deps.py` | `TokenInfo.user_id` |
| `backend/app/api/rest.py` | 建局 / 列表 / 删除 / 入座鉴权；`resolve_viewer`；删 `public_history`；`/health` |
| `backend/app/api/ws.py` | 三种入口解析 |
| `backend/app/api/agents.py`、`providers.py`、`avatars.py`、`voices.py` | 登录与归属 |
| `backend/app/store/event_store.py`、`runtime/agent_library.py`、`agent/provider.py` | `owner_id` 字段 |
| `backend/app/runtime/registry.py`、`game_runner.py`、`history.py` | owner 透传、按 owner 的经验存储、摘要字段 |
| `backend/app/main.py` | 装配、admin 引导、`/health`、删 `AGENTHOWL_PUBLIC_HISTORY` |
| `backend/tests/conftest.py` | `make_app` / `login_as` 夹具 |
| `frontend/src/api/auth.ts`、`store/auth.ts`、`pages/LoginPage.tsx`、`pages/AdminUsers.tsx`（新） | 登录态与页面 |
| `frontend/src/api/tokens.ts`、`rest.ts`、`ws.ts`、`history.ts`、`App.tsx`、`pages/GamePage.tsx`、`pages/History.tsx`、`pages/Lobby.tsx`、`components/HistoryTable`、`components/ShareDialog`、`store/voice.ts` | share / cookie 模式 |
| `.env.example`、`README.md`、`Dockerfile`、`docs/specs/requirements.md` | 文档与部署 |

---

### Task 1: 用户模型、密码哈希与 UserStore（InMemory + Sqlite）

**Files:**
- Create: `backend/app/runtime/users.py`
- Test: `backend/tests/test_users_store.py`、`backend/tests/test_password.py`

**Interfaces:**
- Produces: `User`, `UserPublic`, `Session`, `EmailCode`, `UserStore`, `InMemoryUserStore`, `SqliteUserStore(path: Path)`, `UserConflictError`, `hash_password(pw) -> str`, `verify_password(pw, stored) -> bool`, `normalize_username`, `normalize_email`, `validate_username`, `validate_email`, `validate_password`（三者抛 `ValueError`）, `now_iso()`, `new_user_id()`, `new_session(user_id) -> Session`, `bootstrap_admin(store, *, username, email, password) -> User | None`, 常量 `SESSION_TTL`, `EMAIL_CODE_TTL`, `EMAIL_CODE_MAX_ATTEMPTS = 5`。

- [ ] **Step 1: 写密码哈希测试**

`backend/tests/test_password.py`：

```python
"""密码哈希（issue #114）：scrypt + 随机盐；校验失败不抛。"""

from app.runtime.users import hash_password, verify_password


def test_hash_roundtrip_and_salted() -> None:
    a = hash_password("correct horse")
    b = hash_password("correct horse")
    assert a != b  # 随机盐
    assert a.startswith("scrypt$16384$8$1$")
    assert verify_password("correct horse", a)
    assert verify_password("correct horse", b)
    assert not verify_password("wrong", a)


def test_verify_malformed_returns_false() -> None:
    assert not verify_password("x", "")
    assert not verify_password("x", "scrypt$bad")
    assert not verify_password("x", "scrypt$16384$8$1$!!!$!!!")
```

- [ ] **Step 2: 写 UserStore 契约测试（两实现参数化）**

`backend/tests/test_users_store.py`：

```python
"""UserStore 契约（issue #114）：InMemory 与 Sqlite 行为一致。"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.runtime.users import (
    EMAIL_CODE_MAX_ATTEMPTS,
    EmailCode,
    InMemoryUserStore,
    Session,
    SqliteUserStore,
    User,
    UserConflictError,
    UserStore,
    bootstrap_admin,
    hash_password,
    new_session,
    normalize_email,
    normalize_username,
    now_iso,
    validate_email,
    validate_password,
    validate_username,
)


@pytest.fixture(params=["memory", "sqlite"])
def store(request: pytest.FixtureRequest, tmp_path: Path) -> UserStore:
    if request.param == "memory":
        return InMemoryUserStore()
    return SqliteUserStore(tmp_path / "users.db")


def _user(uid: str, name: str, email: str, **kw: object) -> User:
    return User(
        user_id=uid,
        username=name,
        email=email,
        password_hash=hash_password("password1"),
        created_at=now_iso(),
        **kw,  # type: ignore[arg-type]
    )


def test_put_get_by_keys(store: UserStore) -> None:
    store.put(_user("u_1", "alice", "a@x.io"))
    assert store.get("u_1") is not None
    assert store.get_by_username("alice") is not None
    assert store.get_by_email("a@x.io") is not None
    assert store.get("nope") is None
    assert store.count() == 1
    assert [u.user_id for u in store.list()] == ["u_1"]


def test_unique_username_and_email(store: UserStore) -> None:
    store.put(_user("u_1", "alice", "a@x.io"))
    with pytest.raises(UserConflictError):
        store.put(_user("u_2", "alice", "b@x.io"))
    with pytest.raises(UserConflictError):
        store.put(_user("u_3", "bob", "a@x.io"))
    # 同 user_id 整体替换不算冲突
    store.put(_user("u_1", "alice", "a@x.io", role="admin"))
    got = store.get("u_1")
    assert got is not None and got.role == "admin"


def test_session_expiry(store: UserStore) -> None:
    store.put(_user("u_1", "alice", "a@x.io"))
    live = new_session("u_1")
    store.create_session(live)
    assert store.get_session(live.session_id) is not None
    past = (datetime.now(UTC) - timedelta(seconds=1)).isoformat(timespec="seconds")
    dead = Session(session_id="s_dead", user_id="u_1", created_at=past, expires_at=past)
    store.create_session(dead)
    assert store.get_session("s_dead") is None  # 过期即 None，并已删除
    store.delete_sessions_of("u_1")
    assert store.get_session(live.session_id) is None


def test_email_code_single_per_user(store: UserStore) -> None:
    exp = (datetime.now(UTC) + timedelta(minutes=15)).isoformat(timespec="seconds")
    store.put_email_code(EmailCode(user_id="u_1", code_hash="h1", expires_at=exp))
    store.put_email_code(EmailCode(user_id="u_1", code_hash="h2", expires_at=exp, attempts=2))
    got = store.get_email_code("u_1")
    assert got is not None and got.code_hash == "h2" and got.attempts == 2
    store.delete_email_code("u_1")
    assert store.get_email_code("u_1") is None
    assert EMAIL_CODE_MAX_ATTEMPTS == 5


def test_sqlite_file_mode_0600(tmp_path: Path) -> None:
    path = tmp_path / "users.db"
    SqliteUserStore(path).count()
    assert oct(os.stat(path).st_mode & 0o777) == "0o600"


def test_sqlite_survives_reopen(tmp_path: Path) -> None:
    path = tmp_path / "users.db"
    SqliteUserStore(path).put(_user("u_1", "alice", "a@x.io"))
    assert SqliteUserStore(path).get_by_username("alice") is not None


def test_normalize_and_validate() -> None:
    assert normalize_username("  Alice ") == "alice"
    assert normalize_email(" A@X.IO ") == "a@x.io"
    validate_username("alice_01")
    for bad in ("ab", "a" * 33, "has space", "Üñï"):
        with pytest.raises(ValueError):
            validate_username(bad)
    validate_email("a@x.io")
    for bad in ("", "noat", "a@" + "x" * 260):
        with pytest.raises(ValueError):
            validate_email(bad)
    validate_password("12345678")
    for bad in ("1234567", "x" * 129):
        with pytest.raises(ValueError):
            validate_password(bad)


def test_bootstrap_admin_idempotent(store: UserStore) -> None:
    created = bootstrap_admin(store, username="Root", email="R@x.io", password="password1")
    assert created is not None and created.role == "admin" and created.email_verified_at
    assert created.username == "root" and created.email == "r@x.io"
    assert bootstrap_admin(store, username="root", email="r@x.io", password="other123") is None
    assert store.count() == 1
```

- [ ] **Step 3: 跑测试确认失败**

Run: `cd backend && uv run pytest tests/test_password.py tests/test_users_store.py -q`
Expected: FAIL `ModuleNotFoundError: app.runtime.users`

- [ ] **Step 4: 实现 `backend/app/runtime/users.py`**

```python
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

_USER_COLS = (
    "user_id, username, email, password_hash, role, status, email_verified_at, created_at"
)


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


def bootstrap_admin(
    store: UserStore, *, username: str, email: str, password: str
) -> User | None:
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
```

- [ ] **Step 5: 跑测试、lint、mypy**

Run: `cd backend && uv run pytest tests/test_password.py tests/test_users_store.py -q && uv run ruff check app/runtime/users.py tests/test_users_store.py tests/test_password.py && uv run ruff format app tests && uv run mypy app`
Expected: 全部 PASS，无 lint/mypy 错误。

- [ ] **Step 6: Commit**

```bash
git add backend/app/runtime/users.py backend/tests/test_users_store.py backend/tests/test_password.py
git commit -m "feat(users): 用户/会话/验证码模型与 InMemory+Sqlite 存储、scrypt 密码哈希 (issue #114)"
```

---

### Task 2: 站点密钥与分享 token、限流、邮件

**Files:**
- Create: `backend/app/runtime/secret.py`、`backend/app/runtime/ratelimit.py`、`backend/app/runtime/mailer.py`
- Test: `backend/tests/test_secret.py`、`backend/tests/test_ratelimit.py`、`backend/tests/test_mailer.py`

**Interfaces:**
- Produces: `load_secret(data_dir: Path, *, env: Mapping[str, str] | None = None) -> bytes`、`share_token(secret: bytes, game_id: str) -> str`、`verify_share_token(secret, game_id, token) -> bool`；`RateLimiter(rules, *, clock=time.monotonic)`、`.check(rule, key) -> bool`、`RateLimiter.disabled()`、`DEFAULT_RULES`；`MailConfig`、`MailConfig.from_env(env=None) -> MailConfig | None`、`Mailer` Protocol（`enabled: bool`，`async send(to, subject, body)`）、`NullMailer`、`RecordingMailer`、`SmtpMailer(config)`、`MailError`。

- [ ] **Step 1: 写测试**

`backend/tests/test_secret.py`：

```python
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
```

`backend/tests/test_ratelimit.py`：

```python
"""内存滑动窗口限流（issue #114）。"""

from app.runtime.ratelimit import DEFAULT_RULES, RateLimiter


def test_window_and_keys() -> None:
    t = [0.0]
    rl = RateLimiter({"login": (2, 10.0)}, clock=lambda: t[0])
    assert rl.check("login", "1.1.1.1")
    assert rl.check("login", "1.1.1.1")
    assert not rl.check("login", "1.1.1.1")
    assert rl.check("login", "2.2.2.2")  # 不同 key 独立
    t[0] = 10.1
    assert rl.check("login", "1.1.1.1")  # 窗口滑过


def test_unknown_rule_allows_and_disabled() -> None:
    rl = RateLimiter({})
    assert rl.check("nope", "x")
    off = RateLimiter.disabled()
    assert all(off.check("login", "x") for _ in range(100))
    assert set(DEFAULT_RULES) == {"register", "login", "resend", "verify"}
```

`backend/tests/test_mailer.py`：

```python
"""邮件配置与 Mailer（issue #114）。"""

import pytest

from app.runtime.mailer import MailConfig, NullMailer, RecordingMailer


def test_from_env_none_when_no_host() -> None:
    assert MailConfig.from_env({}) is None
    assert MailConfig.from_env({"AGENTHOWL_SMTP_HOST": "  "}) is None


def test_from_env_requires_from() -> None:
    with pytest.raises(ValueError):
        MailConfig.from_env({"AGENTHOWL_SMTP_HOST": "smtp.x"})


def test_from_env_full() -> None:
    cfg = MailConfig.from_env(
        {
            "AGENTHOWL_SMTP_HOST": "smtp.x",
            "AGENTHOWL_SMTP_PORT": "2525",
            "AGENTHOWL_SMTP_USER": "u",
            "AGENTHOWL_SMTP_PASSWORD": "p",
            "AGENTHOWL_SMTP_FROM": "noreply@x",
            "AGENTHOWL_SMTP_STARTTLS": "0",
        }
    )
    assert cfg is not None
    assert (cfg.host, cfg.port, cfg.user, cfg.sender, cfg.starttls) == (
        "smtp.x",
        2525,
        "u",
        "noreply@x",
        False,
    )
    assert "p" not in repr(cfg)


@pytest.mark.asyncio
async def test_null_and_recording() -> None:
    null = NullMailer()
    assert null.enabled is False
    await null.send("a@x", "s", "b")
    rec = RecordingMailer()
    assert rec.enabled is True
    await rec.send("a@x", "s", "b")
    assert rec.sent == [("a@x", "s", "b")]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && uv run pytest tests/test_secret.py tests/test_ratelimit.py tests/test_mailer.py -q`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 实现三个模块**

`backend/app/runtime/secret.py`：

```python
"""站点密钥（issue #114）：只用于派生分享 token。环境变量 > data/secret.key > 生成并落盘（0600）。"""

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
```

`backend/app/runtime/ratelimit.py`：

```python
"""内存滑动窗口限流（issue #114）：只防暴力，不是配额系统。单进程假设与 token 登记表一致。"""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable, Mapping

DEFAULT_RULES: dict[str, tuple[int, float]] = {
    "register": (5, 3600.0),
    "login": (10, 60.0),
    "resend": (3, 3600.0),
    "verify": (10, 60.0),
}


class RateLimiter:
    def __init__(
        self,
        rules: Mapping[str, tuple[int, float]],
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._rules = dict(rules)
        self._clock = clock
        self._hits: dict[tuple[str, str], deque[float]] = {}

    @classmethod
    def disabled(cls) -> RateLimiter:
        return cls({})

    def check(self, rule: str, key: str) -> bool:
        """允许则记一次并返回 True；未配置的 rule 一律放行。"""
        spec = self._rules.get(rule)
        if spec is None:
            return True
        limit, window = spec
        now = self._clock()
        q = self._hits.setdefault((rule, key), deque())
        while q and now - q[0] >= window:
            q.popleft()
        if len(q) >= limit:
            return False
        q.append(now)
        return True
```

`backend/app/runtime/mailer.py`：

```python
"""邮件发送（issue #114）：标准库 smtplib，在线程里发；未配置 SMTP → NullMailer（注册免验证）。"""

from __future__ import annotations

import asyncio
import logging
import os
import smtplib
from collections.abc import Mapping
from email.message import EmailMessage
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)


class MailError(RuntimeError):
    """发送失败（网络 / 认证）；文案不含密码。"""


class MailConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    host: str
    port: int = 587
    user: str | None = None
    password: str | None = Field(default=None, repr=False)
    sender: str
    starttls: bool = True

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> MailConfig | None:
        e = os.environ if env is None else env
        host = e.get("AGENTHOWL_SMTP_HOST", "").strip()
        if not host:
            return None
        sender = e.get("AGENTHOWL_SMTP_FROM", "").strip()
        if not sender:
            raise ValueError("配置了 AGENTHOWL_SMTP_HOST 就必须配置 AGENTHOWL_SMTP_FROM")
        return cls(
            host=host,
            port=int(e.get("AGENTHOWL_SMTP_PORT", "587")),
            user=e.get("AGENTHOWL_SMTP_USER") or None,
            password=e.get("AGENTHOWL_SMTP_PASSWORD") or None,
            sender=sender,
            starttls=e.get("AGENTHOWL_SMTP_STARTTLS", "1").strip().lower()
            not in ("0", "false", "no", "off"),
        )


class Mailer(Protocol):
    @property
    def enabled(self) -> bool: ...

    async def send(self, to: str, subject: str, body: str) -> None: ...


class NullMailer:
    """未配置 SMTP：不发信；注册流程据 enabled=False 自动验证。"""

    enabled = False

    async def send(self, to: str, subject: str, body: str) -> None:
        logger.debug("NullMailer 丢弃邮件 to=%s subject=%s", to, subject)


class RecordingMailer:
    """测试用：当作已配置的 Mailer，记录发送。"""

    enabled = True

    def __init__(self) -> None:
        self.sent: list[tuple[str, str, str]] = []

    async def send(self, to: str, subject: str, body: str) -> None:
        self.sent.append((to, subject, body))


class SmtpMailer:
    enabled = True

    def __init__(self, config: MailConfig) -> None:
        self._cfg = config

    def _send_sync(self, to: str, subject: str, body: str) -> None:
        msg = EmailMessage()
        msg["From"] = self._cfg.sender
        msg["To"] = to
        msg["Subject"] = subject
        msg.set_content(body)
        try:
            with smtplib.SMTP(self._cfg.host, self._cfg.port, timeout=15) as smtp:
                if self._cfg.starttls:
                    smtp.starttls()
                if self._cfg.user:
                    smtp.login(self._cfg.user, self._cfg.password or "")
                smtp.send_message(msg)
        except (smtplib.SMTPException, OSError) as exc:
            raise MailError(f"SMTP 发送失败：{type(exc).__name__}") from exc

    async def send(self, to: str, subject: str, body: str) -> None:
        await asyncio.to_thread(self._send_sync, to, subject, body)
```

- [ ] **Step 4: 跑测试 + lint + mypy**

Run: `cd backend && uv run pytest tests/test_secret.py tests/test_ratelimit.py tests/test_mailer.py -q && uv run ruff check . && uv run ruff format . && uv run mypy app`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/runtime/secret.py backend/app/runtime/ratelimit.py backend/app/runtime/mailer.py backend/tests/test_secret.py backend/tests/test_ratelimit.py backend/tests/test_mailer.py
git commit -m "feat(runtime): 站点密钥与 HMAC 分享 token、内存限流、SMTP/Null/Recording Mailer (issue #114)"
```

---

### Task 3: 认证 API、依赖注入、create_app 装配、测试夹具

**Files:**
- Create: `backend/app/api/auth.py`
- Modify: `backend/app/main.py`（create_app 参数与装配；`/health`）
- Create: `backend/tests/conftest.py`（覆盖现有的一行 docstring 文件）
- Test: `backend/tests/test_api_auth.py`

**Interfaces:**
- Consumes: Task 1 的 `users.py` 全部；Task 2 的 `RateLimiter`、`DEFAULT_RULES`、`Mailer`、`NullMailer`、`SmtpMailer`、`MailConfig`、`load_secret`。
- Produces: `SESSION_COOKIE = "agenthowl_session"`；依赖 `get_users(request) -> UserStore`、`current_user(request) -> User | None`、`require_user(...) -> User`、`require_admin(...) -> User`；纯函数 `can_access(user: User, owner_id: str | None) -> bool`、`user_from_cookie(users: UserStore, cookies: Mapping[str, str]) -> User | None`、`client_ip(request) -> str`；`create_app(..., user_store=, users_db=, mailer=, secret=, rate_limiter=, cookie_secure=)`；`app.state.users / mailer / secret / rate_limiter / cookie_secure`；`GET /api/v1/health`；夹具 `make_app(**kwargs) -> FastAPI`、`login_as(client, username, *, role="user") -> dict`（返回 UserPublic JSON）。

- [ ] **Step 1: 写夹具 `backend/tests/conftest.py`**

```python
"""pytest 共享夹具。引擎测试零 IO、零 mock；API 测试用内存用户库 + 免验证 + 关限流（issue #114）。"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.main import create_app
from app.runtime.mailer import NullMailer
from app.runtime.ratelimit import RateLimiter
from app.runtime.users import InMemoryUserStore, User, hash_password, new_user_id, now_iso
from app.store.event_store import InMemoryEventStore

TEST_PASSWORD = "password1"


def make_app(**kwargs: Any) -> FastAPI:
    """create_app 的测试默认：内存事件库、内存用户库、NullMailer（注册免验证）、限流关、
    cookie 不带 Secure（TestClient 走 http）。kwargs 覆盖任一默认。"""
    defaults: dict[str, Any] = {
        "store": InMemoryEventStore(),
        "user_store": InMemoryUserStore(),
        "mailer": NullMailer(),
        "rate_limiter": RateLimiter.disabled(),
        "secret": b"test-secret",
        "cookie_secure": False,
    }
    defaults.update(kwargs)
    return create_app(**defaults)


def login_as(client: TestClient, username: str, *, role: str = "user") -> dict[str, Any]:
    """直接写入已验证用户并登录；TestClient 自动保存 cookie。返回 /auth/me 的 JSON。"""
    users = client.app.state.users  # type: ignore[attr-defined]
    if users.get_by_username(username) is None:
        users.put(
            User(
                user_id=new_user_id(),
                username=username,
                email=f"{username}@test.local",
                password_hash=hash_password(TEST_PASSWORD),
                role=role,  # type: ignore[arg-type]
                email_verified_at=now_iso(),
                created_at=now_iso(),
            )
        )
    r = client.post(
        "/api/v1/auth/login", json={"identifier": username, "password": TEST_PASSWORD}
    )
    assert r.status_code == 200, r.text
    me: dict[str, Any] = client.get("/api/v1/auth/me").json()
    return me
```

- [ ] **Step 2: 写 `backend/tests/test_api_auth.py`**

```python
"""认证端点（issue #114）：注册 → 验证 → 登录 → me → 登出；auto 模式；限流；禁用。"""

from __future__ import annotations

import re
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.runtime.mailer import RecordingMailer
from app.runtime.ratelimit import RateLimiter
from app.runtime.users import InMemoryUserStore
from tests.conftest import login_as, make_app


@pytest.fixture()
def mailer() -> RecordingMailer:
    return RecordingMailer()


@pytest.fixture()
def client(mailer: RecordingMailer) -> Iterator[TestClient]:
    with TestClient(make_app(mailer=mailer)) as c:
        yield c


def _code_from(mailer: RecordingMailer) -> str:
    m = re.search(r"验证码：(\d{6})", mailer.sent[-1][2])
    assert m is not None
    return m.group(1)


def test_register_verify_login_me_logout(client: TestClient, mailer: RecordingMailer) -> None:
    r = client.post(
        "/api/v1/auth/register",
        json={"username": "Alice", "email": "A@X.io", "password": "password1"},
    )
    assert r.status_code == 201, r.text
    assert r.json()["verification"] == "email"
    assert r.json()["user"]["username"] == "alice"
    assert "password" not in r.text.lower().replace("password1", "")
    assert mailer.sent[-1][0] == "a@x.io"
    # 未验证不能登录
    r = client.post("/api/v1/auth/login", json={"identifier": "alice", "password": "password1"})
    assert r.status_code == 401 and r.json()["reason"] == "unverified"
    # 错码
    r = client.post("/api/v1/auth/verify", json={"email": "a@x.io", "code": "000000"})
    assert r.status_code == 400
    r = client.post("/api/v1/auth/verify", json={"email": "a@x.io", "code": _code_from(mailer)})
    assert r.status_code == 200 and "agenthowl_session" in client.cookies
    me = client.get("/api/v1/auth/me")
    assert me.status_code == 200 and me.json()["email_verified"] is True
    assert client.post("/api/v1/auth/logout").status_code == 204
    assert client.get("/api/v1/auth/me").status_code == 401


def test_register_normalizes_username_and_email(client: TestClient) -> None:
    body = {"username": "Alice ", "email": "a@x.io", "password": "password1"}
    assert client.post("/api/v1/auth/register", json=body).status_code == 201
    body2 = {"username": "alice", "email": "B@x.io", "password": "password1"}
    assert client.post("/api/v1/auth/register", json=body2).status_code == 409
    body3 = {"username": "bob", "email": " A@X.IO ", "password": "password1"}
    assert client.post("/api/v1/auth/register", json=body3).status_code == 409


def test_register_validation_422(client: TestClient) -> None:
    for body in (
        {"username": "ab", "email": "a@x.io", "password": "password1"},
        {"username": "alice", "email": "nope", "password": "password1"},
        {"username": "alice", "email": "a@x.io", "password": "short"},
    ):
        assert client.post("/api/v1/auth/register", json=body).status_code == 422


def test_auto_verification_without_smtp() -> None:
    with TestClient(make_app()) as c:  # NullMailer
        r = c.post(
            "/api/v1/auth/register",
            json={"username": "alice", "email": "a@x.io", "password": "password1"},
        )
        assert r.status_code == 201 and r.json()["verification"] == "auto"
        assert "agenthowl_session" not in c.cookies
        r = c.post("/api/v1/auth/login", json={"identifier": "a@x.io", "password": "password1"})
        assert r.status_code == 200 and r.json()["user"]["username"] == "alice"


def test_login_generic_error_and_resend_opaque(client: TestClient, mailer: RecordingMailer) -> None:
    r = client.post("/api/v1/auth/login", json={"identifier": "ghost", "password": "password1"})
    assert r.status_code == 401 and r.json()["detail"] == "用户名或密码错误"
    client.post(
        "/api/v1/auth/register",
        json={"username": "alice", "email": "a@x.io", "password": "password1"},
    )
    r = client.post("/api/v1/auth/login", json={"identifier": "alice", "password": "wrong-pass"})
    assert r.status_code == 401 and r.json()["detail"] == "用户名或密码错误"
    n = len(mailer.sent)
    assert client.post("/api/v1/auth/resend", json={"email": "nobody@x.io"}).status_code == 200
    assert len(mailer.sent) == n
    assert client.post("/api/v1/auth/resend", json={"email": "a@x.io"}).status_code == 200
    assert len(mailer.sent) == n + 1


def test_verify_attempts_exhausted(client: TestClient, mailer: RecordingMailer) -> None:
    client.post(
        "/api/v1/auth/register",
        json={"username": "alice", "email": "a@x.io", "password": "password1"},
    )
    code = _code_from(mailer)
    for _ in range(5):
        assert client.post("/api/v1/auth/verify", json={"email": "a@x.io", "code": "999999"}).status_code == 400
    # 第 6 次即使码对也作废
    assert client.post("/api/v1/auth/verify", json={"email": "a@x.io", "code": code}).status_code == 400


def test_disabled_user_session_rejected() -> None:
    with TestClient(make_app()) as c:
        login_as(c, "alice")
        users = c.app.state.users  # type: ignore[attr-defined]
        u = users.get_by_username("alice")
        users.put(u.model_copy(update={"status": "disabled"}))
        assert c.get("/api/v1/auth/me").status_code == 401
        r = c.post("/api/v1/auth/login", json={"identifier": "alice", "password": "password1"})
        assert r.status_code == 403


def test_rate_limit_429() -> None:
    rl = RateLimiter({"login": (2, 60.0)})
    with TestClient(make_app(rate_limiter=rl)) as c:
        body = {"identifier": "x", "password": "password1"}
        assert c.post("/api/v1/auth/login", json=body).status_code == 401
        assert c.post("/api/v1/auth/login", json=body).status_code == 401
        assert c.post("/api/v1/auth/login", json=body).status_code == 429


def test_cookie_flags() -> None:
    with TestClient(make_app(cookie_secure=True)) as c:
        store = c.app.state.users  # type: ignore[attr-defined]
        assert isinstance(store, InMemoryUserStore)
        c.post(
            "/api/v1/auth/register",
            json={"username": "alice", "email": "a@x.io", "password": "password1"},
        )
        r = c.post("/api/v1/auth/login", json={"identifier": "alice", "password": "password1"})
        cookie = r.headers["set-cookie"].lower()
        assert "httponly" in cookie and "samesite=lax" in cookie and "secure" in cookie
        assert "max-age=2592000" in cookie


def test_admin_bootstrap_and_health(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENTHOWL_ADMIN_USERNAME", "root")
    monkeypatch.setenv("AGENTHOWL_ADMIN_EMAIL", "root@x.io")
    monkeypatch.setenv("AGENTHOWL_ADMIN_PASSWORD", "password1")
    with TestClient(make_app()) as c:
        assert c.get("/api/v1/health").json() == {"ok": True}
        r = c.post("/api/v1/auth/login", json={"identifier": "root", "password": "password1"})
        assert r.status_code == 200 and r.json()["user"]["role"] == "admin"
    monkeypatch.delenv("AGENTHOWL_ADMIN_PASSWORD")
    with pytest.raises(ValueError):
        make_app()


def test_require_user_401_for_protected(client: TestClient) -> None:
    assert client.get("/api/v1/presets").status_code == 401
    assert client.get("/api/v1/skills").status_code == 401
    assert client.get("/api/v1/tts/status").status_code == 401
```

（`/presets`、`/skills`、`/tts/status` 的 401 在 Task 5/6 落地；本任务先把这三条断言留在文件里，若在本任务跑红，允许用 `pytest.mark.xfail(strict=True, reason="Task 5/6")` 标记并在对应任务移除。）

- [ ] **Step 3: 跑测试确认失败**

Run: `cd backend && uv run pytest tests/test_api_auth.py -q`
Expected: FAIL（`create_app` 不认识 `user_store` 等参数 / `app.api.auth` 不存在）

- [ ] **Step 4: 实现 `backend/app/api/auth.py`**

```python
"""认证（issue #114）：注册 / 邮箱验证 / 登录 / 登出 / me，cookie 会话，依赖注入。

安全口径：登录失败统一文案；/resend 不泄露邮箱存在性；禁用账号 403 且会话即时失效；
password_hash / session_id / 验证码明文永不进响应与日志。
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from app.runtime.mailer import MailError, Mailer
from app.runtime.ratelimit import RateLimiter
from app.runtime.users import (
    EMAIL_CODE_MAX_ATTEMPTS,
    User,
    UserConflictError,
    UserPublic,
    UserStore,
    hash_code,
    hash_password,
    is_expired,
    new_email_code,
    new_session,
    new_user_id,
    normalize_email,
    normalize_username,
    now_iso,
    validate_email,
    validate_password,
    validate_username,
    verify_password,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

SESSION_COOKIE = "agenthowl_session"
SESSION_MAX_AGE = 30 * 24 * 3600
VERIFY_SUBJECT = "AgentHowl 邮箱验证码"


class UnverifiedError(Exception):
    """登录时邮箱未验证；main.py 映射为 401 {"detail": "邮箱未验证", "reason": "unverified"}。"""


# ---------- 依赖 ----------


def get_users(request: Request) -> UserStore:
    users: UserStore = request.app.state.users
    return users


def user_from_cookie(users: UserStore, cookies: Mapping[str, str]) -> User | None:
    """cookie → 会话 → 用户；过期 / 用户不存在 / 已禁用 → None（并删掉该会话）。REST 与 WS 共用。"""
    sid = cookies.get(SESSION_COOKIE)
    if not sid:
        return None
    session = users.get_session(sid)
    if session is None:
        return None
    user = users.get(session.user_id)
    if user is None or user.status != "active":
        users.delete_session(sid)
        return None
    return user


def current_user(request: Request) -> User | None:
    return user_from_cookie(get_users(request), request.cookies)


def require_user(user: User | None = Depends(current_user)) -> User:
    if user is None:
        raise HTTPException(status_code=401, detail="未登录")
    return user


def require_admin(user: User = Depends(require_user)) -> User:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return user


def can_access(user: User, owner_id: str | None) -> bool:
    """归属规则（spec §5）：admin 恒 True；否则只看自己的；无主（旧数据）只有 admin 可见。"""
    return user.role == "admin" or (owner_id is not None and owner_id == user.user_id)


def client_ip(request: Request) -> str:
    if getattr(request.app.state, "trust_proxy", False):
        fwd = request.headers.get("x-forwarded-for")
        if fwd:
            return fwd.split(",")[0].strip()
    return request.client.host if request.client is not None else "unknown"


def _limit(request: Request, rule: str) -> None:
    limiter: RateLimiter = request.app.state.rate_limiter
    if not limiter.check(rule, client_ip(request)):
        raise HTTPException(status_code=429, detail="请求过于频繁，请稍后再试")


def _set_session(request: Request, response: Response, user: User) -> None:
    session = new_session(user.user_id)
    get_users(request).create_session(session)
    response.set_cookie(
        SESSION_COOKIE,
        session.session_id,
        max_age=SESSION_MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=bool(request.app.state.cookie_secure),
        path="/",
    )


async def _send_code(request: Request, user: User) -> None:
    users = get_users(request)
    mailer: Mailer = request.app.state.mailer
    code, record = new_email_code(user.user_id)
    users.put_email_code(record)
    try:
        await mailer.send(
            user.email, VERIFY_SUBJECT, f"您的 AgentHowl 验证码：{code}，15 分钟内有效。"
        )
    except MailError as exc:
        logger.error("验证码邮件发送失败 user=%s：%s", user.username, exc)


# ---------- 请求 / 响应 ----------


class RegisterRequest(BaseModel):
    username: str
    email: str
    password: str


class RegisterResponse(BaseModel):
    user: UserPublic
    verification: Literal["email", "auto"]


class VerifyRequest(BaseModel):
    email: str
    code: str


class ResendRequest(BaseModel):
    email: str


class LoginRequest(BaseModel):
    identifier: str
    password: str


class LoginResponse(BaseModel):
    user: UserPublic


class OkResponse(BaseModel):
    ok: bool = True


# ---------- 端点 ----------


@router.post("/register", status_code=201)
async def register(req: RegisterRequest, request: Request) -> RegisterResponse:
    _limit(request, "register")
    username = normalize_username(req.username)
    email = normalize_email(req.email)
    try:
        validate_username(username)
        validate_email(email)
        validate_password(req.password)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    users = get_users(request)
    mailer: Mailer = request.app.state.mailer
    user = User(
        user_id=new_user_id(),
        username=username,
        email=email,
        password_hash=hash_password(req.password),
        email_verified_at=None if mailer.enabled else now_iso(),
        created_at=now_iso(),
    )
    try:
        users.put(user)
    except UserConflictError as exc:
        raise HTTPException(status_code=409, detail="用户名或邮箱已被占用") from exc
    if mailer.enabled:
        await _send_code(request, user)
        return RegisterResponse(user=user.public(), verification="email")
    return RegisterResponse(user=user.public(), verification="auto")


@router.post("/verify")
def verify(req: VerifyRequest, request: Request, response: Response) -> OkResponse:
    _limit(request, "verify")
    users = get_users(request)
    bad = HTTPException(status_code=400, detail="验证码无效或已过期")
    user = users.get_by_email(normalize_email(req.email))
    if user is None or user.email_verified_at is not None:
        raise bad
    record = users.get_email_code(user.user_id)
    if record is None or record.attempts >= EMAIL_CODE_MAX_ATTEMPTS:
        raise bad
    if is_expired(record.expires_at) or record.code_hash != hash_code(req.code.strip()):
        users.put_email_code(record.model_copy(update={"attempts": record.attempts + 1}))
        raise bad
    users.delete_email_code(user.user_id)
    verified = user.model_copy(update={"email_verified_at": now_iso()})
    users.put(verified)
    _set_session(request, response, verified)
    return OkResponse()


@router.post("/resend")
async def resend(req: ResendRequest, request: Request) -> OkResponse:
    _limit(request, "resend")
    users = get_users(request)
    mailer: Mailer = request.app.state.mailer
    user = users.get_by_email(normalize_email(req.email))
    if user is not None and user.email_verified_at is None and mailer.enabled:
        await _send_code(request, user)
    return OkResponse()  # 存在与否同样 200


@router.post("/login")
def login(req: LoginRequest, request: Request, response: Response) -> LoginResponse:
    _limit(request, "login")
    users = get_users(request)
    ident = req.identifier.strip()
    user = users.get_by_username(normalize_username(ident)) or users.get_by_email(
        normalize_email(ident)
    )
    if user is None or not verify_password(req.password, user.password_hash):
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    if user.status != "active":
        raise HTTPException(status_code=403, detail="账号已被禁用")
    if user.email_verified_at is None:
        raise UnverifiedError()
    _set_session(request, response, user)
    return LoginResponse(user=user.public())


@router.post("/logout", status_code=204, response_class=Response)
def logout(request: Request) -> Response:
    sid = request.cookies.get(SESSION_COOKIE)
    if sid:
        get_users(request).delete_session(sid)
    resp = Response(status_code=204)
    resp.delete_cookie(SESSION_COOKIE, path="/")
    return resp


@router.get("/me")
def me(user: User = Depends(require_user)) -> UserPublic:
    return user.public()
```

`UnverifiedError` 在 `create_app` 注册（`from app.api.auth import UnverifiedError`）：

```python
    async def _unverified(request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(status_code=401, content={"detail": "邮箱未验证", "reason": "unverified"})

    app.add_exception_handler(UnverifiedError, _unverified)
```


- [ ] **Step 5: 修改 `backend/app/main.py`**

导入处追加：

```python
from app.api import admin, agents, auth, avatars, providers, rest, voices, ws
from app.runtime.mailer import MailConfig, Mailer, NullMailer, SmtpMailer
from app.runtime.ratelimit import DEFAULT_RULES, RateLimiter
from app.runtime.secret import load_secret
from app.runtime.users import SqliteUserStore, UserStore, bootstrap_admin
```

（`admin` 模块在 Task 8 创建；本任务先不 import / include `admin`，Task 8 再加。）

`create_app` 签名：删除 `public_history: bool | None = None`，追加

```python
    user_store: UserStore | None = None,
    users_db: Path | None = None,
    mailer: Mailer | None = None,
    secret: bytes | None = None,
    rate_limiter: RateLimiter | None = None,
    cookie_secure: bool | None = None,
```

函数体：删除 `public_history` 三行（`if public_history is None: ... app.state.public_history = public_history`）。在 `app.state.tokens = TokenRegistry()` 之后插入：

```python
    # 用户与会话（issue #114）
    base_dir = Path("data")
    app.state.users = user_store or SqliteUserStore(
        users_db or Path(os.environ.get("AGENTHOWL_USERS_DB", "data/users.db"))
    )
    if mailer is None:
        mail_cfg = MailConfig.from_env()  # HOST 有而 FROM 无 → ValueError（fail-loud）
        if mail_cfg is None:
            logging.getLogger(__name__).warning("未配置 AGENTHOWL_SMTP_HOST：注册免邮箱验证")
            mailer = NullMailer()
        else:
            mailer = SmtpMailer(mail_cfg)
    app.state.mailer = mailer
    app.state.secret = secret if secret is not None else load_secret(base_dir)
    app.state.rate_limiter = rate_limiter or RateLimiter(DEFAULT_RULES)
    if cookie_secure is None:
        cookie_secure = os.environ.get("AGENTHOWL_COOKIE_SECURE", "1").strip().lower() not in (
            "0",
            "false",
            "no",
            "off",
        )
    app.state.cookie_secure = cookie_secure
    app.state.trust_proxy = os.environ.get("AGENTHOWL_TRUST_PROXY", "0").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )
    _bootstrap_admin_from_env(app.state.users)
```

模块级新增：

```python
def _bootstrap_admin_from_env(users: UserStore) -> None:
    """AGENTHOWL_ADMIN_USERNAME/EMAIL/PASSWORD 三者齐全 → 建 admin；只配了部分 → fail-loud。"""
    keys = ("AGENTHOWL_ADMIN_USERNAME", "AGENTHOWL_ADMIN_EMAIL", "AGENTHOWL_ADMIN_PASSWORD")
    vals = [os.environ.get(k, "").strip() for k in keys]
    if any(vals) and not all(vals):
        raise ValueError(f"管理员引导变量须同时配置：{', '.join(keys)}")
    if all(vals):
        created = bootstrap_admin(users, username=vals[0], email=vals[1], password=vals[2])
        if created is not None:
            logging.getLogger(__name__).info("已创建管理员 %s", created.username)
    if not any(u.role == "admin" for u in users.list()):
        logging.getLogger(__name__).warning(
            "用户表里没有管理员：配置 AGENTHOWL_ADMIN_* 或用 app.cli.claim 后再提升"
        )
```

路由装配处追加 `app.include_router(auth.router, prefix="/api/v1")`，并在 `rest.router` 之前注册健康检查：

```python
    @app.get("/api/v1/health")
    def health() -> dict[str, bool]:
        return {"ok": True}
```

异常处理器追加 `UnverifiedError` 映射（见 Step 4 末尾）。

`_MaskTokenFilter` 的正则改为 `re.compile(r"((?:token|share)=)[^&\s\"]+")`，替换串不变。

- [ ] **Step 6: 跑测试 + 全量 + lint + mypy**

Run: `cd backend && uv run pytest tests/test_api_auth.py -q && uv run pytest -q --ignore=tests/test_api_e2e.py && uv run ruff check . && uv run ruff format . && uv run mypy app`
Expected: `test_api_auth.py` 全绿（三条受保护端点断言按 Step 2 备注处理）。注意 `tests/test_api_history.py` 里 `public_history=` 参数会报 TypeError —— 本任务允许该文件暂时红；Task 6 重写它。其余现有测试仍应通过（建局此时尚未要求登录）。

- [ ] **Step 7: Commit**

```bash
git add backend/app/api/auth.py backend/app/main.py backend/app/runtime/users.py backend/tests/conftest.py backend/tests/test_api_auth.py
git commit -m "feat(api): 注册/邮箱验证/登录/登出/me 与 cookie 会话、admin 引导、/health (issue #114)"
```

---

### Task 4: 归属字段与运行时透传（GameMeta / StoredAgent / Provider / GameSummary / registry）

**Files:**
- Modify: `backend/app/store/event_store.py:55-67`（GameMeta）
- Modify: `backend/app/runtime/agent_library.py:24-30`（StoredAgent）
- Modify: `backend/app/agent/provider.py:56-68`（Provider）
- Modify: `backend/app/runtime/history.py:31-42, 49-78`（GameSummary + summarize_game）
- Modify: `backend/app/runtime/registry.py`（GameHandle.owner_id、create(owner_id, allowed_providers)、experience_store_for）
- Modify: `backend/app/runtime/game_runner.py:88-95, 118-145, 155-162`（GameLobby.game_meta / GameRunner owner_id）
- Test: `backend/tests/test_event_store.py`（追加）、`backend/tests/test_history.py`（追加）、`backend/tests/test_registry_owner.py`（新）

**Interfaces:**
- Produces: `GameMeta.owner_id: str | None = None`；`StoredAgent.owner_id: str | None = None`；`Provider.owner_id: str | None = None`；`GameSummary.owner_id / owner_name / share_token: str | None = None`；`GameHandle.owner_id`；`GameRegistry.create(..., owner_id: str | None = None, allowed_providers: Collection[str] | None = None)`；`GameRegistry(..., experience_store_for: Callable[[str], ExperienceStore] | None = None)`；`GameRunner(..., owner_id: str | None = None)`。

- [ ] **Step 1: 写测试**

追加到 `backend/tests/test_event_store.py` 末尾：

```python
def test_game_meta_owner_id_roundtrip_and_legacy_default(tmp_path: Path) -> None:
    from app.engine.config import build_preset
    from app.store.event_store import GameMeta, JsonFileEventStore, SeatName

    store = JsonFileEventStore(tmp_path)
    meta = GameMeta(
        game_id="g_owner",
        config=build_preset("std_9_kill_side"),
        roster=tuple(SeatName(seat=i, display_name=f"P{i}") for i in range(9)),
        owner_id="u_1",
    )
    store.create_game(meta)
    assert JsonFileEventStore(tmp_path).load_meta("g_owner").owner_id == "u_1"
    # 旧文件（首行无 owner_id）→ None
    assert GameMeta.model_validate(
        {"game_id": "g_old", "config": meta.config.model_dump(mode="json"), "roster": []}
    ).owner_id is None
```

（若该文件没有 `Path` 导入，补 `from pathlib import Path`。）

追加到 `backend/tests/test_history.py`：

```python
def test_summary_carries_owner_id() -> None:
    from app.engine.config import build_preset
    from app.runtime.history import summarize_game
    from app.store.event_store import GameMeta

    meta = GameMeta(game_id="g_1", config=build_preset("std_9_kill_side"), roster=(), owner_id="u_9")
    s = summarize_game(meta, [], live=False)
    assert s.owner_id == "u_9" and s.owner_name is None and s.share_token is None
```

新建 `backend/tests/test_registry_owner.py`：

```python
"""registry 的归属透传（issue #114）：owner_id 进 GameMeta；经验存储按 owner 分；provider 白名单。"""

from __future__ import annotations

import asyncio

import pytest

from app.agent.experience import AgentExperience
from app.agent.profile import AgentProfile
from app.agent.provider import Provider
from app.engine.config import build_preset
from app.runtime.experience_store import InMemoryExperienceStore
from app.runtime.game_runner import RunnerTimeouts
from app.runtime.player_port import BotPlayerPort
from app.runtime.provider_store import InMemoryProviderStore
from app.runtime.registry import GameRegistry
from app.store.event_store import InMemoryEventStore


def _provider(pid: str, owner: str | None) -> Provider:
    return Provider(
        provider_id=pid,
        name=pid,
        kind="openai_compatible",
        api_base="http://x",
        api_key=None,
        default_model="m",
        created_at="t",
        updated_at="t",
        owner_id=owner,
    )


def test_owner_id_written_to_meta() -> None:
    async def run() -> None:
        store = InMemoryEventStore()
        reg = GameRegistry(store=store, timeouts=RunnerTimeouts(speech_sec=0.01, action_sec=0.01))
        h = reg.create(build_preset("std_9_kill_side"), allow_spectators=True, owner_id="u_1")
        assert h.owner_id == "u_1"
        reg.start(h)
        assert h.task is not None
        await h.task
        assert store.load_meta(h.game_id).owner_id == "u_1"

    asyncio.run(run())


def test_experience_store_per_owner() -> None:
    stores: dict[str, InMemoryExperienceStore] = {}

    def for_owner(owner_id: str) -> InMemoryExperienceStore:
        return stores.setdefault(owner_id, InMemoryExperienceStore())

    async def run() -> None:
        root = InMemoryExperienceStore()
        reg = GameRegistry(
            store=InMemoryEventStore(),
            timeouts=RunnerTimeouts(speech_sec=0.01, action_sec=0.01),
            experience_store=root,
            experience_store_for=for_owner,
            agent_port_factory=lambda seat, handle: BotPlayerPort(
                state_provider=lambda: handle.live_state()
            ),
        )
        profile = AgentProfile(model="m", memory_id="mem1")
        cfg = build_preset("std_9_kill_side")
        h = reg.create(cfg, allow_spectators=True, agents={"0": profile}, owner_id="u_1")
        reg.start(h)
        assert "u_1" in stores and isinstance(h.experiences[0], AgentExperience)
        assert root.saves == 0
        h2 = reg.create(cfg, allow_spectators=True, agents={"0": profile})
        reg.start(h2)  # owner None → 根存储（CLI / 旧数据）
        assert h2.experiences[0].memory_id == "mem1"
        assert h.task is not None and h2.task is not None
        await h.task
        await h2.task

    asyncio.run(run())


def test_allowed_providers_restricts_profile_reference() -> None:
    ps = InMemoryProviderStore()
    ps.put(_provider("p_a", "u_1"))
    ps.put(_provider("p_b", "u_2"))
    reg = GameRegistry(store=InMemoryEventStore(), provider_store=ps)
    cfg = build_preset("std_9_kill_side")
    reg.create(cfg, allow_spectators=True, agents={"0": AgentProfile(model="m", provider="p_a")}, allowed_providers={"p_a"})
    with pytest.raises(ValueError):
        reg.create(
            cfg,
            allow_spectators=True,
            agents={"0": AgentProfile(model="m", provider="p_b")},
            allowed_providers={"p_a"},
        )
    # None = 不限制（admin / CLI）
    reg.create(cfg, allow_spectators=True, agents={"0": AgentProfile(model="m", provider="p_b")})
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && uv run pytest tests/test_registry_owner.py tests/test_event_store.py tests/test_history.py -q`
Expected: FAIL（未知字段 / 未知参数）

- [ ] **Step 3: 加字段**

`event_store.py` `GameMeta` 加 `owner_id: str | None = None`（docstring 追加一句「owner_id（issue #114）：建局者 user_id；旧文件缺省 None = 无主，仅 admin 可见」）。
`agent_library.py` `StoredAgent` 加 `owner_id: str | None = None`。
`agent/provider.py` `Provider` 加 `owner_id: str | None = None`（`ProviderPublic` 不加）。
`history.py` `GameSummary` 加三行：

```python
    owner_id: str | None = None
    owner_name: str | None = None  # rest 层按 UserStore 补；普通用户列表里就是自己
    share_token: str | None = None  # rest 层按站点密钥补
```

`summarize_game` 的 `GameSummary(...)` 构造加 `owner_id=meta.owner_id,`。

- [ ] **Step 4: registry / runner 透传**

`registry.py`：
- `GameHandle.__init__` 加关键字参数 `owner_id: str | None = None`，存 `self.owner_id = owner_id`。
- `GameRegistry.__init__` 加 `experience_store_for: Callable[[str], ExperienceStore] | None = None`，存 `self._experience_store_for`。新增方法：

```python
    def experience_store_of(self, owner_id: str | None) -> ExperienceStore:
        """按归属取经验存储（issue #114）：有 owner 且配置了工厂 → 该 owner 的；否则根存储。"""
        if owner_id is not None and self._experience_store_for is not None:
            return self._experience_store_for(owner_id)
        return self._experience_store
```

- `create(...)` 加 `owner_id: str | None = None, allowed_providers: Collection[str] | None = None`；`providers = {p.provider_id for p in self._provider_store.list()}` 改为：

```python
        providers = {p.provider_id for p in self._provider_store.list()}
        if allowed_providers is not None:
            providers &= set(allowed_providers)
```

`GameHandle(...)` 构造传 `owner_id=owner_id`。
- `start()`：`handle.experiences[seat] = self._experience_store.load(mid)` 改为 `self.experience_store_of(handle.owner_id).load(mid)`；`GameRunner(...)` 调用加 `owner_id=handle.owner_id`；`_schedule_postgame` 的 `store=self._experience_store` 改为 `store=self.experience_store_of(handle.owner_id)`。
- 顶部 `from collections.abc import Callable` 已有则补 `Collection`。

`game_runner.py`：
- `GameLobby.game_meta(self, agents=None, owner_id: str | None = None)`，构造加 `owner_id=owner_id`。
- `GameRunner.__init__` 加 `owner_id: str | None = None`，存 `self._owner_id`；`run()` 里 `GameMeta(...)` 加 `owner_id=self._owner_id`。

`main.py` 的 `GameRegistry(...)` 装配加：

```python
        experience_store_for=lambda owner_id: JsonFileExperienceStore(
            (memory_dir or Path("data/agent_memory")) / owner_id
        ),
```

（当调用方显式传了 `experience_store` 时也保留该工厂：测试用内存根存储 + 文件工厂的组合不会出现，因为 API 测试走 `make_app`；若需要可再传 `experience_store_for`。）

- [ ] **Step 5: 跑测试 + 全量 + lint + mypy**

Run: `cd backend && uv run pytest tests/test_registry_owner.py tests/test_event_store.py tests/test_history.py -q && uv run pytest -q --ignore=tests/test_api_e2e.py --deselect tests/test_api_history.py && uv run ruff check . && uv run ruff format . && uv run mypy app && git diff --stat main -- app/engine`
Expected: PASS；引擎 diff 为空。

- [ ] **Step 6: Commit**

```bash
git add backend/app backend/tests
git commit -m "feat(runtime): GameMeta/StoredAgent/Provider/GameSummary 加 owner_id；registry 按 owner 的经验存储与 provider 白名单 (issue #114)"
```

---

### Task 5: Agent 库 / Provider / 头像 / 声线 / 只读元数据的登录与归属

**Files:**
- Modify: `backend/app/api/agents.py`、`backend/app/api/providers.py`、`backend/app/api/avatars.py:21`、`backend/app/api/voices.py:31`、`backend/app/api/rest.py:599`（`tts/status`）
- Test: `backend/tests/test_api_ownership.py`（新，agents/providers 部分）；改 `backend/tests/test_api_agents.py`、`test_api_providers.py`、`test_api_avatars.py`、`test_api_voice.py` 使用 `make_app` + `login_as`

**Interfaces:**
- Consumes: Task 3 `require_user`、`can_access`、`User`；Task 4 `StoredAgent.owner_id`、`Provider.owner_id`。
- Produces: agents / providers 端点全部 `Depends(require_user)`；`_visible_agents(lib, user) -> list[StoredAgent]`、`visible_providers(store, user) -> list[Provider]`、`_get_owned_agent(lib, user, id) -> StoredAgent`（404）、`_get_owned_provider(store, user, id) -> Provider`（404）。Task 6 的建局复用 `visible_providers`（公开名，无下划线）。

- [ ] **Step 1: 写 `backend/tests/test_api_ownership.py`（agents/providers 部分）**

```python
"""归属隔离（issue #114）：两个普通用户 + admin。跨 owner 一律 404。"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.agent.provider import Provider
from app.runtime.agent_library import StoredAgent
from app.agent.profile import AgentProfile
from tests.conftest import login_as, make_app

PROVIDER = {"name": "mine", "kind": "openai_compatible", "api_base": "http://x", "api_key": "k"}


def _agent(name: str, **extra: Any) -> dict[str, Any]:
    return {"name": name, "model": "m", **extra}


@pytest.fixture()
def app() -> Any:
    return make_app()


def _client(app: Any) -> TestClient:
    return TestClient(app)


def test_anonymous_401(app: Any) -> None:
    with _client(app) as c:
        assert c.get("/api/v1/agents").status_code == 401
        assert c.post("/api/v1/agents", json=_agent("a")).status_code == 401
        assert c.get("/api/v1/providers").status_code == 401
        assert c.put("/api/v1/avatars", content=b"x").status_code == 401
        assert c.post("/api/v1/voices/design", json={"style": "x"}).status_code == 401
        assert c.get("/api/v1/presets").status_code == 401
        assert c.get("/api/v1/skills").status_code == 401
        assert c.get("/api/v1/tts/status").status_code == 401


def test_agents_isolated_between_users(app: Any) -> None:
    with _client(app) as alice, _client(app) as bob, _client(app) as root:
        login_as(alice, "alice")
        login_as(bob, "bob")
        login_as(root, "root", role="admin")
        a = alice.post("/api/v1/agents", json=_agent("a1")).json()
        assert a["owner_id"] == alice.get("/api/v1/auth/me").json()["user_id"]
        b = bob.post("/api/v1/agents", json=_agent("b1")).json()
        assert [x["agent_id"] for x in alice.get("/api/v1/agents").json()] == [a["agent_id"]]
        assert [x["agent_id"] for x in bob.get("/api/v1/agents").json()] == [b["agent_id"]]
        assert {x["agent_id"] for x in root.get("/api/v1/agents").json()} == {a["agent_id"], b["agent_id"]}
        # 跨 owner 全 404
        assert bob.get(f"/api/v1/agents/{a['agent_id']}").status_code == 404
        assert bob.put(f"/api/v1/agents/{a['agent_id']}", json=_agent("x")).status_code == 404
        assert bob.delete(f"/api/v1/agents/{a['agent_id']}").status_code == 404
        assert root.get(f"/api/v1/agents/{a['agent_id']}").status_code == 200
        # 同名按 owner 唯一：bob 可以也叫 a1，alice 自己不能重复
        assert bob.post("/api/v1/agents", json=_agent("a1")).status_code == 201
        assert alice.post("/api/v1/agents", json=_agent("a1")).status_code == 409
        # memory_id 同理
        assert alice.post("/api/v1/agents", json=_agent("m1", memory_id="mem")).status_code == 201
        assert bob.post("/api/v1/agents", json=_agent("m2", memory_id="mem")).status_code == 201
        assert alice.post("/api/v1/agents", json=_agent("m3", memory_id="mem")).status_code == 409


def test_agent_can_only_reference_own_provider(app: Any) -> None:
    with _client(app) as alice, _client(app) as bob, _client(app) as root:
        login_as(alice, "alice")
        login_as(bob, "bob")
        login_as(root, "root", role="admin")
        pa = alice.post("/api/v1/providers", json=PROVIDER).json()["provider_id"]
        assert alice.post("/api/v1/agents", json=_agent("ok", provider=pa)).status_code == 201
        r = bob.post("/api/v1/agents", json=_agent("no", provider=pa))
        assert r.status_code == 400 and "provider" in r.json()["detail"]
        assert root.post("/api/v1/agents", json=_agent("adm", provider=pa)).status_code == 201


def test_providers_isolated_and_public_never_has_key(app: Any) -> None:
    with _client(app) as alice, _client(app) as bob, _client(app) as root:
        login_as(alice, "alice")
        login_as(bob, "bob")
        login_as(root, "root", role="admin")
        pa = alice.post("/api/v1/providers", json=PROVIDER).json()
        assert "api_key" not in pa and pa["has_key"] is True
        assert bob.get("/api/v1/providers").json() == []
        assert bob.get(f"/api/v1/providers/{pa['provider_id']}").status_code == 404
        assert bob.put(f"/api/v1/providers/{pa['provider_id']}", json=PROVIDER).status_code == 404
        assert bob.delete(f"/api/v1/providers/{pa['provider_id']}").status_code == 404
        assert bob.post(f"/api/v1/providers/{pa['provider_id']}/test", json={}).status_code == 404
        assert bob.get(f"/api/v1/providers/{pa['provider_id']}/models").status_code == 404
        assert bob.post("/api/v1/providers", json=PROVIDER).status_code == 201  # 同名跨 owner 允许
        assert alice.post("/api/v1/providers", json=PROVIDER).status_code == 409
        assert len(root.get("/api/v1/providers").json()) == 2
        assert root.delete(f"/api/v1/providers/{pa['provider_id']}").status_code == 204


def test_legacy_ownerless_only_admin(app: Any) -> None:
    lib = app.state.agent_library
    lib.put(
        StoredAgent(agent_id="a_old", profile=AgentProfile(name="old", model="m"), created_at="t", updated_at="t")
    )
    app.state.provider_store.put(
        Provider(
            provider_id="p_old",
            name="old",
            kind="openai_compatible",
            api_base="http://x",
            api_key=None,
            default_model=None,
            created_at="t",
            updated_at="t",
        )
    )
    with _client(app) as alice, _client(app) as root:
        login_as(alice, "alice")
        login_as(root, "root", role="admin")
        assert alice.get("/api/v1/agents").json() == []
        assert alice.get("/api/v1/agents/a_old").status_code == 404
        assert alice.get("/api/v1/providers").json() == []
        assert root.get("/api/v1/agents/a_old").status_code == 200
        assert root.get("/api/v1/providers/p_old").status_code == 200
        # 普通用户可以用与无主档案相同的名字（唯一性只在自己的集合里）
        assert alice.post("/api/v1/agents", json=_agent("old")).status_code == 201


def test_avatar_and_voice_require_login_but_get_public(app: Any) -> None:
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
    with _client(app) as alice, _client(app) as anon:
        login_as(alice, "alice")
        r = alice.put("/api/v1/avatars", content=png, headers={"Content-Type": "image/png"})
        assert r.status_code == 200
        aid = r.json()["avatar_id"]
        assert anon.get(f"/api/v1/avatars/{aid}").status_code == 200
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && uv run pytest tests/test_api_ownership.py -q`
Expected: FAIL（401 断言不成立等）

- [ ] **Step 3: 改 `agents.py`**

模块 docstring 改为「登录后按归属访问（issue #114）」。导入加 `from app.api.auth import can_access, require_user` 与 `from app.runtime.users import User`。

新增两个辅助（放在 `_check_profile` 之前）：

```python
def _visible_agents(lib: AgentLibraryStore, user: User) -> list[StoredAgent]:
    return [s for s in lib.list() if can_access(user, s.owner_id)]


def _get_owned_agent(lib: AgentLibraryStore, user: User, agent_id: str) -> StoredAgent:
    stored = lib.get(agent_id)
    if stored is None or not can_access(user, stored.owner_id):
        raise HTTPException(status_code=404, detail=f"档案不存在：{agent_id}")
    return stored
```

`_check_profile` 签名改为 `(profile, lib, skills, providers, *, user: User, exclude_id)`：
- 唯一性循环改为 `for other in lib.list(): if other.agent_id == exclude_id or other.owner_id != owner_scope: continue`，其中 `owner_scope = user.user_id`（admin 创建的档案归 admin 自己，唯一性也只在 admin 自己的集合里）。
- provider 校验改为：

```python
    if profile.provider is not None:
        p = providers.get(profile.provider)
        if p is None or not can_access(user, p.owner_id):
            raise HTTPException(status_code=400, detail=f"provider 不存在：{profile.provider}")
```

端点：
- `list_agents(user: User = Depends(require_user), lib=...)` → `return _visible_agents(lib, user)`。
- `create_agent(..., user: User = Depends(require_user))`：`_check_profile(..., user=user, exclude_id=None)`；`StoredAgent(..., owner_id=user.user_id)`。
- `get_agent` / `update_agent` / `delete_agent` 加 `user: User = Depends(require_user)`，用 `_get_owned_agent`（delete：先 `_get_owned_agent` 再 `lib.delete`）。`update_agent` 的 `_check_profile(..., user=user, exclude_id=agent_id)`，`model_copy` 保留原 `owner_id`。
- `list_skills`、`list_presets` 加 `_: User = Depends(require_user)`。

- [ ] **Step 4: 改 `providers.py`**

导入同上。新增：

```python
def visible_providers(store: ProviderStore, user: User) -> list[Provider]:
    return [p for p in store.list() if can_access(user, p.owner_id)]


def _get_owned_provider(store: ProviderStore, user: User, provider_id: str) -> Provider:
    p = store.get(provider_id)
    if p is None or not can_access(user, p.owner_id):
        raise HTTPException(status_code=404, detail=f"provider 不存在：{provider_id}")
    return p
```

`_check_name_unique(name, store, *, owner_id: str, exclude_id)`：只在 `other.owner_id == owner_id` 的集合里查重。

端点全部加 `user: User = Depends(require_user)`：
- `list_providers` → `[ProviderPublic.from_provider(p) for p in visible_providers(store, user)]`。
- `create_provider`：`_check_name_unique(body.name, store, owner_id=user.user_id, exclude_id=None)`；`Provider(..., owner_id=user.user_id)`。
- `get_provider` / `update_provider` / `delete_provider` / `test_provider` / `list_provider_models` 用 `_get_owned_provider`。`update_provider` 的唯一性按 `existing.owner_id or user.user_id`；`model_copy` 保留 `owner_id`。`delete_provider` 的引用扫描保持全库扫描（无论谁引用都不能删）。

- [ ] **Step 5: `avatars.py` / `voices.py` / `tts/status`**

- `upload_avatar(request: Request, _: User = Depends(require_user))`；`fetch_avatar` 不变。docstring 改「上传需登录；读取公开（内容寻址，id 不可猜）」。
- `design_voice(req, request, _: User = Depends(require_user))`；`fetch_voice` 不变。
- `rest.py` 的 `tts_status_endpoint(request, _: User = Depends(require_user))`。（`rest.py` 顶部 import `from app.api.auth import require_user` 与 `from app.runtime.users import User`；Task 6 会再加更多。）

- [ ] **Step 6: 改现有测试**

`tests/test_api_agents.py`、`test_api_providers.py`、`test_api_avatars.py`、`test_api_voice.py`：把各自的 `create_app(...)` 换成 `make_app(...)`（保留原有 kwargs），在 `TestClient` 进入后调用 `login_as(c, "tester")`。只做最小改动：若某个 fixture 产出 client，就在 yield 前登录。涉及「同名 409」的断言不变（同一用户内仍唯一）。

- [ ] **Step 7: 跑测试 + lint + mypy**

Run: `cd backend && uv run pytest tests/test_api_ownership.py tests/test_api_agents.py tests/test_api_providers.py tests/test_api_avatars.py tests/test_api_voice.py tests/test_api_auth.py -q && uv run ruff check . && uv run ruff format . && uv run mypy app`
Expected: PASS（`test_api_auth.py` 里 Task 3 的 xfail 标记此时移除）。

- [ ] **Step 8: Commit**

```bash
git add backend/app/api backend/tests
git commit -m "feat(api): Agent 库 / Provider / 头像 / 声线 / 元数据按登录与归属访问，跨 owner 404 (issue #114)"
```

---

### Task 6: 对局 REST：建局归属、列表过滤、删除、入座鉴权、`resolve_viewer`、分享 token

**Files:**
- Modify: `backend/app/api/deps.py:16-21`（`TokenInfo.user_id`）
- Modify: `backend/app/schemas/games.py:24-32`（`spectator_token` → `share_token`）
- Modify: `backend/app/api/rest.py`（大改：65-175 建局 / 入座 / 列表 / 删除；210-285 删 `_finished_or_handle` 等；288-596 各读端点改 `resolve_viewer`）
- Test: `backend/tests/test_api_share.py`（新）；`backend/tests/test_api_ownership.py`（追加 games 部分）；重写 `tests/test_api_history.py`；改 `test_api_lobby.py`、`test_api_play.py`、`test_api_ws.py`、`test_api_e2e.py`、`test_acceptance_m25.py`、`test_api_voice.py`（`spectator_token` → `share_token`、登录、join 带 host_token）

**Interfaces:**
- Consumes: Task 3 `current_user`、`require_user`、`can_access`、`user_from_cookie`；Task 2 `share_token`、`verify_share_token`；Task 4 `GameMeta.owner_id`、`GameHandle.owner_id`、`GameSummary` 新字段、`registry.create(owner_id, allowed_providers)`；Task 5 `visible_providers`。
- Produces: `TokenInfo.user_id: str | None = None`；`CreateGameResponse.share_token: str | None`；依赖 `resolve_viewer(game_id, request, token=Query, share=Query, creds=Depends(_bearer)) -> TokenInfo`（kind ∈ HOST/PLAYER/GM/SPECTATOR；会话归属 → GM）；`POST /games/{id}/join` 接受会话或 Bearer host_token；`GET /games` 按归属过滤并补 `owner_name` / `share_token`。WS（Task 7）复用 `_share_viewer(games, game_id, share) -> TokenInfo | None` 与 `_session_viewer(...)` 两个纯函数。

- [ ] **Step 1: 写 `backend/tests/test_api_share.py`**

```python
"""视角解析（issue #114）：对局 token / 分享 token / 会话归属；allow_spectators；终局放行。"""

from __future__ import annotations

import time
from typing import Any

from fastapi.testclient import TestClient

from app.runtime.secret import share_token
from tests.conftest import login_as, make_app

PRESET = {"preset": "std_9_kill_side", "config_override": {"seed": 1}}


def _wait_over(client: TestClient, gid: str, timeout: float = 30.0) -> None:
    registry = client.app.state.games  # type: ignore[attr-defined]
    h = registry.get(gid)
    deadline = time.time() + timeout
    while not (h.task is not None and h.task.done()):
        assert time.time() < deadline, "对局未在超时内结束"
        time.sleep(0.05)


def _create(client: TestClient, **extra: Any) -> dict[str, Any]:
    r = client.post("/api/v1/games", json={**PRESET, **extra})
    assert r.status_code == 200, r.text
    return r.json()


def test_share_token_is_hmac_and_viewer_spectator() -> None:
    app = make_app()
    with TestClient(app) as owner, TestClient(app) as anon:
        login_as(owner, "alice")
        created = _create(owner)
        gid = created["game_id"]
        assert created["share_token"] == share_token(b"test-secret", gid)
        owner.post(f"/api/v1/games/{gid}/start", json={}, headers={"Authorization": f"Bearer {created['host_token']}"})
        r = anon.get(f"/api/v1/games/{gid}/state", params={"share": created["share_token"]})
        assert r.status_code == 200 and "seats" in r.json() and "players" not in r.json()
        assert anon.get(f"/api/v1/games/{gid}/state", params={"share": "bad"}).status_code == 401
        assert anon.get(f"/api/v1/games/{gid}/state").status_code == 401
        assert anon.get(f"/api/v1/games/{gid}/speeches", params={"share": created["share_token"]}).status_code == 200
        assert anon.get(f"/api/v1/games/{gid}/audio", params={"share": created["share_token"]}).status_code == 200


def test_share_blocked_live_when_spectators_disabled() -> None:
    app = make_app()
    with TestClient(app) as owner, TestClient(app) as anon:
        login_as(owner, "alice")
        created = _create(owner, allow_spectators=False)
        gid = created["game_id"]
        assert created["share_token"] is None
        tok = share_token(b"test-secret", gid)
        # 未开局（handle 在、未终局）：分享链接被挡在视角解析层，不会走到 409
        assert anon.get(f"/api/v1/games/{gid}/state", params={"share": tok}).status_code == 403
        owner.post(f"/api/v1/games/{gid}/start", json={}, headers={"Authorization": f"Bearer {created['host_token']}"})
        _wait_over(owner, gid)
        assert anon.get(f"/api/v1/games/{gid}/replay", params={"share": tok}).status_code == 200
        assert anon.get(f"/api/v1/games/{gid}/meta", params={"share": tok}).status_code == 200


def test_session_owner_is_gm_and_other_user_404() -> None:
    app = make_app()
    with TestClient(app) as owner, TestClient(app) as bob, TestClient(app) as root:
        login_as(owner, "alice")
        login_as(bob, "bob")
        login_as(root, "root", role="admin")
        created = _create(owner)
        gid = created["game_id"]
        owner.post(f"/api/v1/games/{gid}/start", json={}, headers={"Authorization": f"Bearer {created['host_token']}"})
        r = owner.get(f"/api/v1/games/{gid}/state")  # 仅 cookie
        assert r.status_code == 200 and "players" in r.json()  # GM 全量
        assert owner.get(f"/api/v1/games/{gid}/events").status_code == 200
        assert bob.get(f"/api/v1/games/{gid}/state").status_code == 404
        assert bob.get(f"/api/v1/games/{gid}/events").status_code == 404
        assert root.get(f"/api/v1/games/{gid}/state").status_code == 200
        _wait_over(owner, gid)
        assert owner.get(f"/api/v1/games/{gid}/replay").status_code == 200
        assert bob.get(f"/api/v1/games/{gid}/replay").status_code == 404


def test_replay_before_game_over_403_for_gm_token() -> None:
    app = make_app()
    with TestClient(app) as owner:
        login_as(owner, "alice")
        created = _create(owner)
        gid = created["game_id"]
        # 不开局：handle 在但未终局 → 403（开局后 9 个 bot 几秒就打完，断言会漂）
        r = owner.get(f"/api/v1/games/{gid}/replay", headers={"Authorization": f"Bearer {created['gm_token']}"})
        assert r.status_code == 403


def test_game_token_for_wrong_game_403() -> None:
    app = make_app()
    with TestClient(app) as owner:
        login_as(owner, "alice")
        a = _create(owner)
        b = _create(owner)
        owner.post(f"/api/v1/games/{b['game_id']}/start", json={}, headers={"Authorization": f"Bearer {b['host_token']}"})
        r = owner.get(f"/api/v1/games/{b['game_id']}/state", headers={"Authorization": f"Bearer {a['gm_token']}"})
        assert r.status_code == 403


def test_audio_part_accepts_share_query() -> None:
    app = make_app()
    with TestClient(app) as owner, TestClient(app) as anon:
        login_as(owner, "alice")
        created = _create(owner)
        gid = created["game_id"]
        owner.post(f"/api/v1/games/{gid}/start", json={}, headers={"Authorization": f"Bearer {created['host_token']}"})
        r = anon.get(f"/api/v1/games/{gid}/audio/1/0", params={"share": created["share_token"]})
        assert r.status_code == 404  # 没开语音：文件不存在，但鉴权已通过（不是 401）
        assert anon.get(f"/api/v1/games/{gid}/audio/1/0").status_code == 401
```

- [ ] **Step 2: 追加 games 部分到 `tests/test_api_ownership.py`**

```python
def test_games_create_requires_login_and_owner_filtering(app: Any) -> None:
    body = {"preset": "std_9_kill_side", "config_override": {"seed": 1}}
    with _client(app) as anon, _client(app) as alice, _client(app) as bob, _client(app) as root:
        assert anon.post("/api/v1/games", json=body).status_code == 401
        assert anon.get("/api/v1/games").status_code == 401
        alice_me = login_as(alice, "alice")
        login_as(bob, "bob")
        login_as(root, "root", role="admin")
        ga = alice.post("/api/v1/games", json=body).json()
        gb = bob.post("/api/v1/games", json=body).json()
        for c, g in ((alice, ga), (bob, gb)):
            c.post(f"/api/v1/games/{g['game_id']}/start", json={}, headers={"Authorization": f"Bearer {g['host_token']}"})
        mine = alice.get("/api/v1/games").json()
        assert [g["game_id"] for g in mine] == [ga["game_id"]]
        assert mine[0]["owner_id"] == alice_me["user_id"] and mine[0]["owner_name"] == "alice"
        assert mine[0]["share_token"] == ga["share_token"]
        assert [g["game_id"] for g in bob.get("/api/v1/games").json()] == [gb["game_id"]]
        assert {g["game_id"] for g in root.get("/api/v1/games").json()} == {ga["game_id"], gb["game_id"]}
        # 删除：跨 owner 404；未开局 / 进行中 409（用未开局的局断言，开局的 bot 局几秒就完）
        gc = alice.post("/api/v1/games", json=body).json()
        assert bob.delete(f"/api/v1/games/{ga['game_id']}").status_code == 404
        assert alice.delete(f"/api/v1/games/{gc['game_id']}").status_code == 409


def test_create_game_provider_must_be_own(app: Any) -> None:
    with _client(app) as alice, _client(app) as bob:
        login_as(alice, "alice")
        login_as(bob, "bob")
        pa = alice.post("/api/v1/providers", json=PROVIDER).json()["provider_id"]
        body = {"preset": "std_9_kill_side", "agents": {"*": {"model": "m", "provider": pa}}}
        assert alice.post("/api/v1/games", json=body).status_code == 200
        r = bob.post("/api/v1/games", json=body)
        assert r.status_code == 400 and "provider" in r.json()["detail"]


def test_legacy_game_only_admin(app: Any) -> None:
    from app.engine.config import build_preset
    from app.store.event_store import GameMeta, SeatName

    store = app.state.games.store
    store.create_game(
        GameMeta(
            game_id="g_legacy",
            config=build_preset("std_9_kill_side"),
            roster=tuple(SeatName(seat=i, display_name=f"P{i}") for i in range(9)),
        )
    )
    with _client(app) as alice, _client(app) as root:
        login_as(alice, "alice")
        login_as(root, "root", role="admin")
        assert alice.get("/api/v1/games").json() == []
        assert alice.get("/api/v1/games/g_legacy/replay").status_code == 404
        assert alice.delete("/api/v1/games/g_legacy").status_code == 404
        assert [g["game_id"] for g in root.get("/api/v1/games").json()] == ["g_legacy"]
        assert root.get("/api/v1/games/g_legacy/replay").status_code == 403  # 无 GAME_OVER
        assert root.delete("/api/v1/games/g_legacy").status_code == 204


def test_join_requires_session_or_host_token(app: Any) -> None:
    body = {"preset": "std_9_kill_side", "num_ai_players": 8}
    with _client(app) as alice, _client(app) as anon, _client(app) as bob:
        me = login_as(alice, "alice")
        login_as(bob, "bob")
        g = alice.post("/api/v1/games", json=body).json()
        gid = g["game_id"]
        assert anon.post(f"/api/v1/games/{gid}/join", json={"display_name": "x"}).status_code == 401
        # 外部 Agent 客户端：持 host_token 入座
        r = anon.post(f"/api/v1/games/{gid}/join", json={"display_name": "bot"}, headers={"Authorization": f"Bearer {g['host_token']}"})
        assert r.status_code == 200
        tokens = app.state.tokens
        assert tokens.resolve(r.json()["player_token"]).user_id is None
        # gm_token 不算
        r = anon.post(f"/api/v1/games/{gid}/join", json={"display_name": "y"}, headers={"Authorization": f"Bearer {g['gm_token']}"})
        assert r.status_code == 401
        # 登录用户入座：记录 user_id（为 #115 多人铺路，本期不限制谁能入座）
        r = bob.post(f"/api/v1/games/{gid}/join", json={"display_name": "bob"})
        assert r.status_code == 200
        assert tokens.resolve(r.json()["player_token"]).user_id == bob.get("/api/v1/auth/me").json()["user_id"]
        assert me["username"] == "alice"
```

- [ ] **Step 3: 跑新测试确认失败**

Run: `cd backend && uv run pytest tests/test_api_share.py tests/test_api_ownership.py -q`
Expected: FAIL

- [ ] **Step 4: `deps.py` 与 `schemas/games.py`**

`TokenInfo` 加 `user_id: str | None = None  # 登录者（建局 / 登录入座）；外部 Agent 入座为 None（issue #114）`。
`CreateGameResponse`：`spectator_token: str | None` → `share_token: str | None  # HMAC 分享 token（issue #114）；allow_spectators=False → None`。

- [ ] **Step 5: 重写 `rest.py` 的鉴权骨架**

删除：`_public_history`、`_require_history_access`、`_finished_from_store`、`_finished_or_handle`、`_viewer_for`。保留 `_handle_for`、`_audio_visible_seqs`（内部 `_viewer_for(info)` 改为 `viewer_of(info)`）。

新增（放在 `_handle_for` 之后）：

```python
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from app.api.auth import can_access, current_user, require_user
from app.runtime.secret import share_token, verify_share_token
from app.runtime.users import User, UserStore

_bearer = HTTPBearer(auto_error=False)


def viewer_of(info: TokenInfo) -> Any:
    """token → 可见性 viewer：座位号 / "SPECTATOR" / "GM"。"""
    if info.kind == "PLAYER":
        return info.seat
    return "GM" if info.kind == "GM" else "SPECTATOR"


def _owner_of(games: GameRegistry, game_id: str) -> str | None:
    """对局归属：活 handle 优先；否则读事件文件首行；都没有 → 404。"""
    try:
        return games.get(game_id).owner_id
    except LookupError:
        pass
    try:
        return games.store.load_meta(game_id).owner_id
    except (LookupError, StoreError):
        raise HTTPException(status_code=404, detail=f"对局不存在：{game_id}") from None


def _finished(games: GameRegistry, game_id: str) -> bool:
    try:
        handle = games.get(game_id)
    except LookupError:
        return is_finished(games.store.load_events(game_id))
    return handle.started and handle.live_state().phase == Phase.GAME_OVER


def _share_viewer(games: GameRegistry, secret: bytes, game_id: str, share: str) -> TokenInfo:
    """分享 token（issue #114）：直播期间要求 allow_spectators；终局一律放行。"""
    if not verify_share_token(secret, game_id, share):
        raise HTTPException(status_code=401, detail="分享链接无效")
    try:
        handle: GameHandle | None = games.get(game_id)
    except LookupError:
        handle = None
    if handle is not None and not handle.allow_spectators and not _finished(games, game_id):
        raise HTTPException(status_code=403, detail="该对局不开放观战")
    return TokenInfo(game_id=game_id, seat=None, kind="SPECTATOR")


def _session_viewer(games: GameRegistry, user: User | None, game_id: str) -> TokenInfo:
    """登录态：建局者 / admin → GM；其他人 → 404（不泄露存在性）；未登录 → 401。"""
    if user is None:
        raise HTTPException(status_code=401, detail="请登录或使用分享链接")
    if not can_access(user, _owner_of(games, game_id)):
        raise HTTPException(status_code=404, detail=f"对局不存在：{game_id}")
    return TokenInfo(game_id=game_id, seat=None, kind="GM", user_id=user.user_id)


def resolve_viewer(
    game_id: str,
    request: Request,
    token: str | None = Query(default=None),
    share: str | None = Query(default=None),
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    user: User | None = Depends(current_user),
    games: GameRegistry = Depends(get_games),
    tokens: TokenRegistry = Depends(get_tokens),
) -> TokenInfo:
    """读端点统一视角解析（spec §6）：对局 token → 分享 token → 会话归属 → 401。
    `?token=` 与 Bearer 等价（<audio>/WS 发不出头）。"""
    raw = creds.credentials if creds is not None else token
    if raw:
        info = tokens.resolve(raw)
        if info is None:
            raise HTTPException(status_code=401, detail="token 无效")
        if info.game_id != game_id:
            raise HTTPException(status_code=403, detail="token 与对局不匹配")
        return info
    if share:
        return _share_viewer(games, request.app.state.secret, game_id, share)
    return _session_viewer(games, user, game_id)
```

- [ ] **Step 6: 改各端点**

- `create_game_endpoint`：加 `user: User = Depends(require_user)`；计算 `allowed = None if user.role == "admin" else {p.provider_id for p in _visible_providers(request.app.state.provider_store, user)}`（从 `app.api.providers` 导入 `_visible_providers`，并把它改名为公开的 `visible_providers`，Task 5 的两处调用同步）；`games.create(..., owner_id=user.user_id, allowed_providers=allowed)`；host/gm token 加 `user_id=user.user_id`；删除 `spectator_token = tokens.issue(...)`，改为 `share = share_token(request.app.state.secret, handle.game_id) if req.allow_spectators else None`；响应 `share_token=share`。
- `join_endpoint`：加 `request: Request`、`creds: HTTPAuthorizationCredentials | None = Depends(_bearer)`、`user: User | None = Depends(current_user)`：

```python
    user_id: str | None
    if user is not None:
        user_id = user.user_id
    else:
        info = tokens.resolve(creds.credentials) if creds is not None else None
        if info is None or info.kind != "HOST" or info.game_id != game_id:
            raise HTTPException(status_code=401, detail="入座需登录，或携带本局 host_token")
        user_id = None
    handle = games.get(game_id)
    seat = games.join(handle, req.display_name, req.player_type)
    token = tokens.issue(TokenInfo(game_id=game_id, seat=seat, kind="PLAYER", user_id=user_id))
```

- `list_games_endpoint(request, user: User = Depends(require_user), games=...)`：

```python
    users: UserStore = request.app.state.users
    secret: bytes = request.app.state.secret
    out: list[GameSummary] = []
    for s in list_history(games.store, games):
        if not can_access(user, s.owner_id):
            continue
        owner = users.get(s.owner_id) if s.owner_id else None
        out.append(
            s.model_copy(
                update={
                    "owner_name": owner.username if owner else None,
                    "share_token": share_token(secret, s.game_id),
                }
            )
        )
    return out
```

- `delete_game_endpoint`：加 `user: User = Depends(require_user)`；删除 `_public_history` 判断，改为开头 `if not can_access(user, _owner_of(games, game_id)): raise HTTPException(404, ...)`（`_owner_of` 对不存在的局已 404）。其余逻辑不变。
- `state_endpoint(game_id, info: TokenInfo = Depends(resolve_viewer), games=...)`：删掉 `require_kind(...)` 行，改为 `if info.kind == "HOST": raise HTTPException(status_code=403, detail="host_token 无读流权限")`（与 WS 口径一致）。
- `speeches_endpoint`：删 `_finished_or_handle(...)` 调用与 `request` 参数，加 `info: TokenInfo = Depends(resolve_viewer)`；后续 `handle` 查找与逻辑不变（无 handle 时仍读 store）。
- `events_endpoint`：`info: TokenInfo = Depends(resolve_viewer)`，HOST → 403，`viewer = viewer_of(info)`。
- `replay_endpoint` / `meta_endpoint`：`info: TokenInfo = Depends(resolve_viewer)`，然后 `if not _finished(games, game_id): raise HTTPException(status_code=403, detail="对局未结束，上帝视角回放未开放")`。`_finished` 内部在无 handle 且文件不存在时 `load_events` 抛 `StoreError` 子类 → 需在 `_finished` 里捕获 `(LookupError, StoreError)` 映射 404（与 `_owner_of` 同理；`resolve_viewer` 的会话分支已经先查过归属，所以这里只是兜底）。
- `avatars_endpoint`：`info: TokenInfo = Depends(resolve_viewer)`，删 `_finished_or_handle`。
- `audio_manifest_endpoint`：同上；`_audio_visible_seqs(games, game_id, info)` 不变。
- `audio_part_endpoint`：删掉手工 `token` 解析（`resolve_viewer` 已认 `?token=` 与 `?share=`），签名改为 `info: TokenInfo = Depends(resolve_viewer)`。
- `actions_endpoint` / `my_turn_endpoint` / `start_endpoint`：不变（仍 `require_token` + `require_kind`）。
- `_audio_visible_seqs` 里 `_viewer_for` → `viewer_of`；`info is None` 分支删掉（参数改为 `TokenInfo`）。

清理未用导入（`optional_token`、`GameMeta` 若仍被 `meta_endpoint` 返回类型使用则保留）。

- [ ] **Step 7: 改现有测试**

- `tests/test_api_history.py` 重写：删除全部 `public_history` 用例；保留「列表字段 / 排序 / 坏文件跳过 / 删除 409 / 删除 204 后 token 作废」的用例，client 改为 `make_app(store=...)` + `login_as(c, "alice")`；原「无 token 可回放」用例改为「本人 cookie 可回放、分享 token 可回放、他人 404」。
- `tests/test_api_lobby.py`、`test_api_play.py`、`test_api_ws.py`、`test_api_voice.py`、`test_acceptance_m25.py`、`test_api_e2e.py`：fixture 换 `make_app`，进入 client 后 `login_as(c, "host")`；`spectator_token` → `share_token`；所有 `/join` 调用加 `headers=_auth(host_token)`（这些测试模拟外部 Agent 客户端）。`test_api_ws.py` 里用 `spectator_token` 连接 WS 的用例改为 `?game_id=…&share=…`（Task 7 实现；本任务把该用例标 `xfail(strict=True, reason="Task 7")`，Task 7 移除）。

- [ ] **Step 8: 跑全量 + e2e + lint + mypy**

Run: `cd backend && uv run pytest -q --ignore=tests/test_api_e2e.py && uv run pytest -q tests/test_api_e2e.py && uv run ruff check . && uv run ruff format . && uv run mypy app`
Expected: PASS（除 Task 7 的 xfail）。

- [ ] **Step 9: Commit**

```bash
git add backend/app backend/tests
git commit -m "feat(api): 建局归属与列表过滤、入座鉴权、resolve_viewer（对局 token / HMAC 分享 / 会话 GM），废除 PUBLIC_HISTORY (issue #114)"
```

---

### Task 7: WebSocket 三种入口

**Files:**
- Modify: `backend/app/api/ws.py:75-104`
- Test: `backend/tests/test_api_ws.py`（追加 / 修改）

**Interfaces:**
- Consumes: Task 6 `_share_viewer`、`_session_viewer`、`viewer_of`（从 `app.api.rest` 导入）；Task 3 `user_from_cookie`。
- Produces: `/api/v1/ws?token=` | `?game_id=&share=` | `?game_id=`（cookie）。关闭码：4401 无凭据 / 无效；4403 HOST 或不开放观战；4404 不存在；4409 未开局。

- [ ] **Step 1: 写测试（追加到 `tests/test_api_ws.py`）**

```python
def test_ws_share_and_cookie_entries() -> None:
    from tests.conftest import login_as, make_app

    app = make_app()
    with TestClient(app) as owner, TestClient(app) as anon, TestClient(app) as bob:
        login_as(owner, "alice")
        login_as(bob, "bob")
        created = owner.post("/api/v1/games", json={"preset": "std_9_kill_side"}).json()
        gid = created["game_id"]
        owner.post(f"/api/v1/games/{gid}/start", json={}, headers={"Authorization": f"Bearer {created['host_token']}"})
        with anon.websocket_connect(f"/api/v1/ws?game_id={gid}&share={created['share_token']}") as ws:
            frame = ws.receive_json()
            assert frame["type"] == "game_event"
        with owner.websocket_connect(f"/api/v1/ws?game_id={gid}") as ws:  # cookie → GM
            frame = ws.receive_json()
            assert frame["type"] == "game_event"
        with pytest.raises(WebSocketDisconnect) as exc, bob.websocket_connect(f"/api/v1/ws?game_id={gid}"):
            pass
        assert exc.value.code == 4401
        with pytest.raises(WebSocketDisconnect) as exc2, anon.websocket_connect(f"/api/v1/ws?game_id={gid}&share=bad"):
            pass
        assert exc2.value.code == 4401
        with pytest.raises(WebSocketDisconnect) as exc3, anon.websocket_connect("/api/v1/ws"):
            pass
        assert exc3.value.code == 4401
```

（文件已有 `WebSocketDisconnect` / `pytest` 导入则复用；Task 6 标的 xfail 用例改为上述 share 形式并移除标记。若 TestClient 的 `websocket_connect` 不转发 cookie jar，则显式传 `headers={"cookie": f"agenthowl_session={sid}"}`，`sid` 取 `owner.cookies["agenthowl_session"]`。）

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && uv run pytest tests/test_api_ws.py -q`
Expected: FAIL

- [ ] **Step 3: 改 `ws.py`**

签名与解析段替换为：

```python
@router.websocket("/ws")
async def ws_endpoint(
    ws: WebSocket,
    token: str | None = Query(default=None),
    game_id: str | None = Query(default=None),
    share: str | None = Query(default=None),
    from_seq: int = Query(default=0),
) -> None:
    await ws.accept()

    tokens = ws.app.state.tokens
    games: GameRegistry = ws.app.state.games
    info: TokenInfo | None = None
    if token:
        info = tokens.resolve(token)
    elif game_id:
        try:
            if share:
                info = _share_viewer(games, ws.app.state.secret, game_id, share)
            else:
                user = user_from_cookie(ws.app.state.users, ws.cookies)
                info = _session_viewer(games, user, game_id)
        except HTTPException as exc:
            await ws.close(code=4403 if exc.status_code == 403 else 4401)
            return
    if info is None:
        await ws.close(code=4401)
        return
    if info.kind not in ("PLAYER", "SPECTATOR", "GM"):
        await ws.close(code=4403)
        return
    try:
        handle = games.get(info.game_id)
    except LookupError:
        await ws.close(code=4404)
        return
    if not handle.started or handle.connections is None:
        await ws.close(code=4409)
        return

    viewer: Any = viewer_of(info)
```

导入：`from fastapi import HTTPException`（已有 `Query`、`WebSocket`），`from app.api.auth import user_from_cookie`，`from app.api.rest import _session_viewer, _share_viewer, _your_turn_payload, viewer_of`。`_session_viewer` 对不存在的局抛 404 → 这里映射成 4401 之前先判断：把 `except HTTPException` 分支改为 `code = {403: 4403, 404: 4404}.get(exc.status_code, 4401)`。

- [ ] **Step 4: 跑测试 + lint + mypy**

Run: `cd backend && uv run pytest tests/test_api_ws.py tests/test_api_share.py -q && uv run ruff check . && uv run ruff format . && uv run mypy app`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/ws.py backend/tests/test_api_ws.py
git commit -m "feat(ws): 支持 game_id+share 与 cookie 会话入口，关闭码口径与 REST 一致 (issue #114)"
```

---

### Task 8: 管理员用户管理 API

**Files:**
- Create: `backend/app/api/admin.py`
- Modify: `backend/app/main.py`（import + include_router）
- Test: `backend/tests/test_api_admin.py`

**Interfaces:**
- Consumes: Task 3 `require_admin`、`get_users`、`UserPublic`。
- Produces: `GET /api/v1/admin/users`、`PATCH /api/v1/admin/users/{id}`（`{role?, status?}`）、`POST /api/v1/admin/users/{id}/verify`。

- [ ] **Step 1: 写测试**

```python
"""管理员用户管理（issue #114）：列表 / 改角色状态 / 手工验证；自锁守卫。"""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.conftest import login_as, make_app


def test_admin_only() -> None:
    app = make_app()
    with TestClient(app) as alice, TestClient(app) as anon:
        login_as(alice, "alice")
        assert anon.get("/api/v1/admin/users").status_code == 401
        assert alice.get("/api/v1/admin/users").status_code == 403


def test_list_patch_verify() -> None:
    app = make_app()
    with TestClient(app) as root, TestClient(app) as bob:
        login_as(root, "root", role="admin")
        bob_me = login_as(bob, "bob")
        users = root.get("/api/v1/admin/users").json()
        assert [u["username"] for u in users] == ["root", "bob"]
        assert all("password" not in u for u in users)
        # 禁用 → bob 会话立即失效
        r = root.patch(f"/api/v1/admin/users/{bob_me['user_id']}", json={"status": "disabled"})
        assert r.status_code == 200 and r.json()["status"] == "disabled"
        assert bob.get("/api/v1/auth/me").status_code == 401
        r = root.patch(f"/api/v1/admin/users/{bob_me['user_id']}", json={"status": "active", "role": "admin"})
        assert r.json()["role"] == "admin"
        assert root.patch("/api/v1/admin/users/u_nope", json={"role": "user"}).status_code == 404
        # 手工验证
        users_store = app.state.users
        u = users_store.get(bob_me["user_id"])
        users_store.put(u.model_copy(update={"email_verified_at": None}))
        r = root.post(f"/api/v1/admin/users/{bob_me['user_id']}/verify")
        assert r.status_code == 200 and r.json()["email_verified"] is True


def test_admin_cannot_lock_itself_out() -> None:
    app = make_app()
    with TestClient(app) as root, TestClient(app) as root2:
        me = login_as(root, "root", role="admin")
        assert root.patch(f"/api/v1/admin/users/{me['user_id']}", json={"role": "user"}).status_code == 400
        assert root.patch(f"/api/v1/admin/users/{me['user_id']}", json={"status": "disabled"}).status_code == 400
        me2 = login_as(root2, "root2", role="admin")
        # 两个 admin：可以降级另一个；之后只剩一个 admin，再降级它 → 400
        assert root.patch(f"/api/v1/admin/users/{me2['user_id']}", json={"role": "user"}).status_code == 200
        assert root2.get("/api/v1/admin/users").status_code == 403
        r = root2.patch(f"/api/v1/admin/users/{me['user_id']}", json={"role": "user"})
        assert r.status_code == 403
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && uv run pytest tests/test_api_admin.py -q`
Expected: FAIL 404（路由不存在）

- [ ] **Step 3: 实现 `backend/app/api/admin.py`**

```python
"""管理员用户管理（issue #114）。守卫：不能改自己；不能让 active admin 归零。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.api.auth import get_users, require_admin
from app.runtime.users import Role, Status, User, UserPublic, UserStore, now_iso

router = APIRouter(prefix="/admin", tags=["admin"])


class PatchUserRequest(BaseModel):
    role: Role | None = None
    status: Status | None = None


def _get(users: UserStore, user_id: str) -> User:
    u = users.get(user_id)
    if u is None:
        raise HTTPException(status_code=404, detail=f"用户不存在：{user_id}")
    return u


def _active_admins(users: UserStore) -> int:
    return sum(1 for u in users.list() if u.role == "admin" and u.status == "active")


@router.get("/users")
def list_users(
    _: User = Depends(require_admin), users: UserStore = Depends(get_users)
) -> list[UserPublic]:
    return [u.public() for u in users.list()]


@router.patch("/users/{user_id}")
def patch_user(
    user_id: str,
    body: PatchUserRequest,
    me: User = Depends(require_admin),
    users: UserStore = Depends(get_users),
) -> UserPublic:
    target = _get(users, user_id)
    if target.user_id == me.user_id:
        raise HTTPException(status_code=400, detail="不能修改自己的角色或状态")
    role = body.role if body.role is not None else target.role
    status = body.status if body.status is not None else target.status
    loses_admin = target.role == "admin" and target.status == "active"
    stays_admin = role == "admin" and status == "active"
    if loses_admin and not stays_admin and _active_admins(users) <= 1:
        raise HTTPException(status_code=400, detail="至少保留一个可用的管理员")
    updated = target.model_copy(update={"role": role, "status": status})
    users.put(updated)
    if status == "disabled":
        users.delete_sessions_of(target.user_id)
    return updated.public()


@router.post("/users/{user_id}/verify")
def verify_user(
    user_id: str, _: User = Depends(require_admin), users: UserStore = Depends(get_users)
) -> UserPublic:
    target = _get(users, user_id)
    if target.email_verified_at is None:
        target = target.model_copy(update={"email_verified_at": now_iso()})
        users.put(target)
        users.delete_email_code(target.user_id)
    return target.public()
```

`users.py` 需导出 `Role`、`Status` 类型别名（Task 1 已定义为模块级 `Literal`）。`main.py`：import `admin`，`app.include_router(admin.router, prefix="/api/v1")`。

- [ ] **Step 4: 跑测试 + lint + mypy**

Run: `cd backend && uv run pytest tests/test_api_admin.py -q && uv run ruff check . && uv run ruff format . && uv run mypy app`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/admin.py backend/app/main.py backend/tests/test_api_admin.py
git commit -m "feat(api): 管理员用户列表 / 角色状态 / 手工验证，含自锁守卫 (issue #114)"
```

---

### Task 9: 迁移 CLI `app.cli.claim`

**Files:**
- Create: `backend/app/cli/claim.py`
- Test: `backend/tests/test_cli_claim.py`

**Interfaces:**
- Consumes: `SqliteUserStore`、`JsonFileAgentLibrary`、`JsonFileProviderStore`、`GameMeta`。
- Produces: `python -m app.cli.claim --user <username> [--data-dir data] [--dry-run]`；`claim(data_dir: Path, username: str, *, dry_run: bool) -> dict[str, int]`（键 `games/agents/providers/memory`）。

- [ ] **Step 1: 写测试**

```python
"""claim CLI（issue #114）：无主数据划归指定用户；dry-run 不写。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.agent.profile import AgentProfile
from app.agent.provider import Provider
from app.cli.claim import claim, main
from app.engine.config import build_preset
from app.runtime.agent_library import JsonFileAgentLibrary, StoredAgent
from app.runtime.provider_store import JsonFileProviderStore
from app.runtime.users import SqliteUserStore, User, hash_password, now_iso
from app.store.event_store import GameMeta, JsonFileEventStore, SeatName


def _seed(data: Path) -> str:
    users = SqliteUserStore(data / "users.db")
    users.put(
        User(
            user_id="u_a", username="alice", email="a@x", password_hash=hash_password("password1"), created_at=now_iso()
        )
    )
    games = JsonFileEventStore(data / "games")
    games.create_game(
        GameMeta(game_id="g_old", config=build_preset("std_9_kill_side"), roster=(SeatName(seat=0, display_name="P0"),))
    )
    games.create_game(
        GameMeta(game_id="g_mine", config=build_preset("std_9_kill_side"), roster=(), owner_id="u_b")
    )
    JsonFileAgentLibrary(data / "agents").put(
        StoredAgent(agent_id="a_old", profile=AgentProfile(name="x", model="m"), created_at="t", updated_at="t")
    )
    JsonFileProviderStore(data / "providers").put(
        Provider(provider_id="p_old", name="p", kind="openai_compatible", api_base="http://x", api_key="k", default_model=None, created_at="t", updated_at="t")
    )
    (data / "agent_memory").mkdir()
    (data / "agent_memory" / "mem1.json").write_text('{"memory_id": "mem1"}', encoding="utf-8")
    return "u_a"


def test_claim_dry_run_then_real(tmp_path: Path) -> None:
    uid = _seed(tmp_path)
    assert claim(tmp_path, "alice", dry_run=True) == {"games": 1, "agents": 1, "providers": 1, "memory": 1}
    assert JsonFileEventStore(tmp_path / "games").load_meta("g_old").owner_id is None
    assert claim(tmp_path, "alice", dry_run=False) == {"games": 1, "agents": 1, "providers": 1, "memory": 1}
    assert JsonFileEventStore(tmp_path / "games").load_meta("g_old").owner_id == uid
    assert JsonFileEventStore(tmp_path / "games").load_meta("g_mine").owner_id == "u_b"
    assert JsonFileAgentLibrary(tmp_path / "agents").get("a_old").owner_id == uid  # type: ignore[union-attr]
    assert JsonFileProviderStore(tmp_path / "providers").get("p_old").owner_id == uid  # type: ignore[union-attr]
    assert (tmp_path / "agent_memory" / uid / "mem1.json").exists()
    assert not (tmp_path / "agent_memory" / "mem1.json").exists()
    # 幂等
    assert claim(tmp_path, "alice", dry_run=False) == {"games": 0, "agents": 0, "providers": 0, "memory": 0}
    # 事件文件其余行保持原样
    lines = (tmp_path / "games" / "g_old.jsonl").read_text(encoding="utf-8").splitlines()
    assert json.loads(lines[0])["kind"] == "meta" and len(lines) == 1


def test_claim_unknown_user(tmp_path: Path) -> None:
    _seed(tmp_path)
    with pytest.raises(SystemExit):
        main(["--user", "ghost", "--data-dir", str(tmp_path)])
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && uv run pytest tests/test_cli_claim.py -q`
Expected: FAIL

- [ ] **Step 3: 实现**

```python
"""无主数据划归（issue #114）：把 owner_id 为空的对局 / Agent / Provider 划给某用户，
并把根目录下的跨局记忆文件移入 <owner_id>/。用法：
    python -m app.cli.claim --user alice [--data-dir data] [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from app.runtime.agent_library import JsonFileAgentLibrary
from app.runtime.provider_store import JsonFileProviderStore
from app.runtime.users import SqliteUserStore


def _claim_games(games_dir: Path, owner_id: str, dry_run: bool) -> int:
    n = 0
    for path in sorted(games_dir.glob("*.jsonl")) if games_dir.is_dir() else []:
        lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
        if not lines:
            continue
        try:
            head = json.loads(lines[0])
        except json.JSONDecodeError:
            continue
        if head.get("kind") != "meta" or head.get("data", {}).get("owner_id") is not None:
            continue
        n += 1
        if dry_run:
            continue
        head["data"]["owner_id"] = owner_id
        lines[0] = json.dumps(head, ensure_ascii=False, separators=(",", ":")) + "\n"
        tmp = path.with_suffix(".jsonl.tmp")
        tmp.write_text("".join(lines), encoding="utf-8")
        os.replace(tmp, path)
    return n


def _claim_agents(agents_dir: Path, owner_id: str, dry_run: bool) -> int:
    lib = JsonFileAgentLibrary(agents_dir)
    n = 0
    for stored in lib.list():
        if stored.owner_id is not None:
            continue
        n += 1
        if not dry_run:
            lib.put(stored.model_copy(update={"owner_id": owner_id}))
    return n


def _claim_providers(providers_dir: Path, owner_id: str, dry_run: bool) -> int:
    store = JsonFileProviderStore(providers_dir)
    n = 0
    for p in store.list():
        if p.owner_id is not None:
            continue
        n += 1
        if not dry_run:
            store.put(p.model_copy(update={"owner_id": owner_id}))
    return n


def _claim_memory(memory_dir: Path, owner_id: str, dry_run: bool) -> int:
    if not memory_dir.is_dir():
        return 0
    files = sorted(p for p in memory_dir.glob("*.json") if p.is_file())
    if files and not dry_run:
        target = memory_dir / owner_id
        target.mkdir(parents=True, exist_ok=True)
        for f in files:
            os.replace(f, target / f.name)
    return len(files)


def claim(data_dir: Path, username: str, *, dry_run: bool) -> dict[str, int]:
    users = SqliteUserStore(data_dir / "users.db")
    user = users.get_by_username(username.strip().lower())
    if user is None:
        raise LookupError(f"用户不存在：{username}")
    return {
        "games": _claim_games(data_dir / "games", user.user_id, dry_run),
        "agents": _claim_agents(data_dir / "agents", user.user_id, dry_run),
        "providers": _claim_providers(data_dir / "providers", user.user_id, dry_run),
        "memory": _claim_memory(data_dir / "agent_memory", user.user_id, dry_run),
    }


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="app.cli.claim", description="无主数据划归某用户")
    parser.add_argument("--user", required=True, help="目标用户名")
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    try:
        counts = claim(Path(args.data_dir), args.user, dry_run=args.dry_run)
    except LookupError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(2)
    prefix = "[dry-run] " if args.dry_run else ""
    for k, v in counts.items():
        print(f"{prefix}{k}: {v}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: 跑测试 + lint + mypy + litellm 守卫**

Run: `cd backend && uv run pytest tests/test_cli_claim.py tests/test_agent_profile.py -q && uv run ruff check . && uv run ruff format . && uv run mypy app`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/cli/claim.py backend/tests/test_cli_claim.py
git commit -m "feat(cli): app.cli.claim 把无主对局/Agent/Provider/记忆划归指定用户 (issue #114)"
```

---

### Task 10: 前端登录态：auth API / store / 路由 / 登录页 / 导航 / 401 处理

**Files:**
- Create: `frontend/src/api/auth.ts`、`frontend/src/store/auth.ts`、`frontend/src/pages/LoginPage.tsx`、`frontend/src/pages/LoginPage.module.css`
- Modify: `frontend/src/api/rest.ts:30-60`（`credentials`、`reason`、401 回调）、`frontend/src/api/tokens.ts`（新路由）、`frontend/src/App.tsx`
- Test: `frontend/src/store/auth.test.ts`、`frontend/src/api/tokens.test.ts`（追加）、`frontend/src/pages/LoginPage.test.tsx`

**Interfaces:**
- Produces: `UserPublic`；`api/auth.ts`：`register(username, email, password) -> Promise<RegisterResponse>`、`verify(email, code)`、`resend(email)`、`login(identifier, password) -> Promise<UserPublic>`、`logout()`、`me() -> Promise<UserPublic>`；`store/auth.ts`：`useAuth` `{user, status: "loading"|"anon"|"authed", load(), login(), logout(), markAnon()}`；`rest.ts`：`ApiError.reason?: string`、`setUnauthorizedHandler(fn: () => void)`；`tokens.ts`：`Route` 增 `"login" | "register" | "verify" | "admin"`，`ParsedHash.share?: string`，`?spec=` → `?share=`，删 `replay`。
- Task 11 消费 `ParsedHash.share` 与裸 `#/g/{id}`；Task 12 消费 `useAuth` 与 `admin` 路由。

- [ ] **Step 1: 写测试**

追加到 `src/api/tokens.test.ts`（替换原 `?spec=` 与 `replay=1` 的用例）：

```ts
  it("auth 与 admin 路由", () => {
    expect(parseHash("#/login")).toEqual({ route: "login" });
    expect(parseHash("#/register")).toEqual({ route: "register" });
    expect(parseHash("#/verify")).toEqual({ route: "verify" });
    expect(parseHash("#/admin")).toEqual({ route: "admin" });
  });

  it("share 链接与裸 game 路由（issue #114）", () => {
    expect(parseHash("#/g/g_1?share=S")).toEqual({
      route: "game",
      gameId: "g_1",
      share: "S",
      viewer: "SPECTATOR",
    });
    // 裸路由：靠登录态走 GM 视角
    expect(parseHash("#/g/g_1")).toEqual({ route: "game", gameId: "g_1", viewer: "GM" });
    // gm 优先于 share
    expect(parseHash("#/g/g_1?gm=T&share=S")).toEqual({
      route: "game",
      gameId: "g_1",
      token: "T",
      viewer: "GM",
    });
    // 旧参数不再识别
    expect(parseHash("#/g/g_1?spec=T")).toEqual({ route: "game", gameId: "g_1", viewer: "GM" });
    expect(parseHash("#/g/g_1?replay=1")).toEqual({ route: "game", gameId: "g_1", viewer: "GM" });
  });
```

`src/store/auth.test.ts`：

```ts
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../api/rest";
import { useAuth } from "./auth";

const user = {
  user_id: "u_1",
  username: "alice",
  email: "a@x",
  role: "user" as const,
  status: "active" as const,
  email_verified: true,
  created_at: "t",
};

function mockFetch(handler: (url: string, init?: RequestInit) => Response): void {
  vi.stubGlobal("fetch", vi.fn((url: string, init?: RequestInit) => Promise.resolve(handler(url, init))));
}

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

describe("useAuth", () => {
  beforeEach(() => {
    useAuth.setState({ user: null, status: "loading" });
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("load：me 200 → authed；401 → anon", async () => {
    mockFetch(() => json(200, user));
    await useAuth.getState().load();
    expect(useAuth.getState()).toMatchObject({ status: "authed", user });
    mockFetch(() => json(401, { detail: "未登录" }));
    await useAuth.getState().load();
    expect(useAuth.getState()).toMatchObject({ status: "anon", user: null });
  });

  it("login 成功写入 user；失败抛 ApiError 带 reason", async () => {
    mockFetch(() => json(200, { user }));
    await useAuth.getState().login("alice", "password1");
    expect(useAuth.getState().user?.username).toBe("alice");
    mockFetch(() => json(401, { detail: "邮箱未验证", reason: "unverified" }));
    await expect(useAuth.getState().login("alice", "x")).rejects.toMatchObject({ reason: "unverified" });
  });

  it("logout 清空并置 anon", async () => {
    useAuth.setState({ user, status: "authed" });
    mockFetch(() => new Response(null, { status: 204 }));
    await useAuth.getState().logout();
    expect(useAuth.getState()).toMatchObject({ status: "anon", user: null });
  });

  it("fetch 带 credentials same-origin", async () => {
    mockFetch(() => json(200, user));
    await useAuth.getState().load();
    const call = (fetch as unknown as ReturnType<typeof vi.fn>).mock.calls[0] as [string, RequestInit];
    expect(call[1].credentials).toBe("same-origin");
    expect(new ApiError(401, "x")).toBeInstanceOf(Error);
  });
});
```

`src/pages/LoginPage.test.tsx`：

```tsx
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { useAuth } from "../store/auth";
import LoginPage from "./LoginPage";

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

describe("LoginPage", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    window.location.hash = "";
  });

  it("登录成功后跳回 next", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() =>
        Promise.resolve(
          json(200, {
            user: { user_id: "u", username: "alice", email: "a@x", role: "user", status: "active", email_verified: true, created_at: "t" },
          }),
        ),
      ),
    );
    render(<LoginPage mode="login" next="#/history" />);
    fireEvent.change(screen.getByLabelText("用户名或邮箱"), { target: { value: "alice" } });
    fireEvent.change(screen.getByLabelText("密码"), { target: { value: "password1" } });
    fireEvent.click(screen.getByRole("button", { name: "登录" }));
    await waitFor(() => expect(useAuth.getState().status).toBe("authed"));
    expect(window.location.hash).toBe("#/history");
  });

  it("未验证 → 切到验证页", async () => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(json(401, { detail: "邮箱未验证", reason: "unverified" }))));
    render(<LoginPage mode="login" />);
    fireEvent.change(screen.getByLabelText("用户名或邮箱"), { target: { value: "a@x" } });
    fireEvent.change(screen.getByLabelText("密码"), { target: { value: "password1" } });
    fireEvent.click(screen.getByRole("button", { name: "登录" }));
    await waitFor(() => expect(window.location.hash).toBe("#/verify"));
  });

  it("注册：auto 模式提示去登录；email 模式跳验证", async () => {
    const resp = { user: { user_id: "u", username: "alice", email: "a@x", role: "user", status: "active", email_verified: true, created_at: "t" }, verification: "auto" };
    vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(json(201, resp))));
    render(<LoginPage mode="register" />);
    fireEvent.change(screen.getByLabelText("用户名"), { target: { value: "alice" } });
    fireEvent.change(screen.getByLabelText("邮箱"), { target: { value: "a@x" } });
    fireEvent.change(screen.getByLabelText("密码"), { target: { value: "password1" } });
    fireEvent.click(screen.getByRole("button", { name: "注册" }));
    await waitFor(() => expect(screen.getByText(/注册成功/)).toBeInTheDocument());
  });
});
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd frontend && npx vitest run src/api/tokens.test.ts src/store/auth.test.ts src/pages/LoginPage.test.tsx`
Expected: FAIL

- [ ] **Step 3: `rest.ts`**

- `ApiError` 加 `reason?: string`；构造函数 `(status, detail, reason?)`。
- 模块级：

```ts
let onUnauthorized: (() => void) | null = null;
/** 401 回调（issue #114）：App 注册为「重新确认登录态」；避免 api 层 import store 造成环。 */
export function setUnauthorizedHandler(fn: (() => void) | null): void {
  onUnauthorized = fn;
}
```

- `ReqOptions` 加 `query?: Record<string, string>`；`req()`：URL 拼 `query`（`URLSearchParams`，有值才拼 `?`）；`fetch(..., { method, headers, body, credentials: "same-origin" })`；解析错误体时同时取 `reason`（字符串才取）；`throw new ApiError(res.status, detail, reason)`；在 throw 前：`if (res.status === 401 && !opts.token && onUnauthorized) onUnauthorized();`（带对局 token 的 401 是 token 问题，不是会话问题）。

- [ ] **Step 4: `api/auth.ts` 与 `store/auth.ts`**

`src/api/auth.ts`：

```ts
// 认证 API（issue #114）：cookie 会话由浏览器自动携带（req 已设 credentials）。

import { req } from "./rest";

export interface UserPublic {
  user_id: string;
  username: string;
  email: string;
  role: "admin" | "user";
  status: "active" | "disabled";
  email_verified: boolean;
  created_at: string;
}

export interface RegisterResponse {
  user: UserPublic;
  verification: "email" | "auto";
}

export function register(username: string, email: string, password: string): Promise<RegisterResponse> {
  return req<RegisterResponse>("POST", "/auth/register", { body: { username, email, password } });
}

export function verify(email: string, code: string): Promise<{ ok: boolean }> {
  return req<{ ok: boolean }>("POST", "/auth/verify", { body: { email, code } });
}

export function resend(email: string): Promise<{ ok: boolean }> {
  return req<{ ok: boolean }>("POST", "/auth/resend", { body: { email } });
}

export async function login(identifier: string, password: string): Promise<UserPublic> {
  const r = await req<{ user: UserPublic }>("POST", "/auth/login", { body: { identifier, password } });
  return r.user;
}

export function logout(): Promise<void> {
  return req<void>("POST", "/auth/logout");
}

export function me(): Promise<UserPublic> {
  return req<UserPublic>("GET", "/auth/me");
}
```

`src/store/auth.ts`：

```ts
// 登录态 store（issue #114）：启动 load() 一次；401 时 App 经 setUnauthorizedHandler 再调 load()。

import { create } from "zustand";
import * as api from "../api/auth";
import type { UserPublic } from "../api/auth";
import { ApiError } from "../api/rest";

export type AuthStatus = "loading" | "anon" | "authed";

interface AuthState {
  user: UserPublic | null;
  status: AuthStatus;
  load(): Promise<void>;
  login(identifier: string, password: string): Promise<void>;
  logout(): Promise<void>;
  markAnon(): void;
}

export const useAuth = create<AuthState>((set) => ({
  user: null,
  status: "loading",

  async load() {
    try {
      const user = await api.me();
      set({ user, status: "authed" });
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        set({ user: null, status: "anon" });
        return;
      }
      // 网络 / 5xx：不下结论，保持当前状态（首屏则停在 loading 由页面显示错误）
      set({ status: "anon", user: null });
    }
  },

  async login(identifier, password) {
    const user = await api.login(identifier, password);
    set({ user, status: "authed" });
  },

  async logout() {
    try {
      await api.logout();
    } finally {
      set({ user: null, status: "anon" });
    }
  },

  markAnon() {
    set({ user: null, status: "anon" });
  },
}));
```

- [ ] **Step 5: `tokens.ts`**

`Route` 改为 `"lobby" | "agents" | "providers" | "history" | "game" | "login" | "register" | "verify" | "admin"`；`ParsedHash` 删 `replay`，加 `share?: string`。`parseHash`：
- 在 history 判断后加四个 `startsWith` 分支（`/login`、`/register`、`/verify`、`/admin`，与 agents 同样的 `=== | ? | /` 三形式）。
- game 分支：`const gm = query.get("gm"); const share = query.get("share");` → gm 优先返回 `{route, gameId, token: gm, viewer: "GM"}`；share → `{route, gameId, share, viewer: "SPECTATOR"}`；否则 `{route: "game", gameId, viewer: "GM"}`。删除 `spec` 与 `replay` 分支。顶部注释同步。

- [ ] **Step 6: `LoginPage.tsx`**

```tsx
// 登录 / 注册 / 邮箱验证（issue #114）。三种 mode 由 hash 路由决定；成功后跳 next（默认 #/）。

import { useState } from "react";
import type { FormEvent } from "react";
import { register, resend, verify } from "../api/auth";
import { ApiError } from "../api/rest";
import { useAuth } from "../store/auth";
import styles from "./LoginPage.module.css";

export type LoginMode = "login" | "register" | "verify";

export interface LoginPageProps {
  mode: LoginMode;
  /** 登录成功后跳转的 hash；缺省 `#/`。 */
  next?: string;
}

function messageOf(err: unknown): string {
  if (err instanceof ApiError) return err.detail;
  return err instanceof Error ? err.message : String(err);
}

export default function LoginPage({ mode, next = "#/" }: LoginPageProps): JSX.Element {
  const login = useAuth((s) => s.login);
  const [identifier, setIdentifier] = useState("");
  const [username, setUsername] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  async function submit(e: FormEvent): Promise<void> {
    e.preventDefault();
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      if (mode === "login") {
        await login(identifier, password);
        window.location.hash = next;
      } else if (mode === "register") {
        const r = await register(username, email, password);
        if (r.verification === "auto") {
          setNotice("注册成功，请登录。");
        } else {
          sessionStorage.setItem("agenthowl.verify_email", email);
          window.location.hash = "#/verify";
        }
      } else {
        await verify(email, code);
        await useAuth.getState().load();
        window.location.hash = next;
      }
    } catch (err) {
      if (err instanceof ApiError && err.reason === "unverified") {
        sessionStorage.setItem("agenthowl.verify_email", identifier);
        window.location.hash = "#/verify";
        return;
      }
      setError(messageOf(err));
    } finally {
      setBusy(false);
    }
  }

  async function doResend(): Promise<void> {
    setError(null);
    try {
      await resend(email);
      setNotice("如果该邮箱已注册且未验证，验证码已重新发送。");
    } catch (err) {
      setError(messageOf(err));
    }
  }

  const title = mode === "login" ? "登录" : mode === "register" ? "注册" : "验证邮箱";

  return (
    <div className={styles.page}>
      <form className={styles.card} onSubmit={(e) => void submit(e)}>
        <h2 className={styles.title}>{title}</h2>
        {mode === "login" && (
          <div className="field">
            <label htmlFor="login-id">用户名或邮箱</label>
            <input id="login-id" className="input" value={identifier} onChange={(e) => setIdentifier(e.target.value)} autoComplete="username" />
          </div>
        )}
        {mode === "register" && (
          <div className="field">
            <label htmlFor="reg-name">用户名</label>
            <input id="reg-name" className="input" value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" />
            <span className="text-muted">3–32 位小写字母、数字或下划线</span>
          </div>
        )}
        {mode !== "login" && (
          <div className="field">
            <label htmlFor="auth-email">邮箱</label>
            <input id="auth-email" className="input" type="email" value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="email" />
          </div>
        )}
        {mode !== "verify" && (
          <div className="field">
            <label htmlFor="auth-pw">密码</label>
            <input id="auth-pw" className="input" type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete={mode === "login" ? "current-password" : "new-password"} />
          </div>
        )}
        {mode === "verify" && (
          <div className="field">
            <label htmlFor="auth-code">验证码</label>
            <input id="auth-code" className="input" inputMode="numeric" value={code} onChange={(e) => setCode(e.target.value)} />
          </div>
        )}
        {error !== null && <div className={styles.error}>{error}</div>}
        {notice !== null && <div className={styles.notice}>{notice}</div>}
        <div className={styles.actions}>
          <button type="submit" className="btn btn-primary" disabled={busy}>
            {title}
          </button>
          {mode === "verify" && (
            <button type="button" className="btn" onClick={() => void doResend()}>
              重发验证码
            </button>
          )}
        </div>
        <div className={styles.links}>
          {mode !== "login" && <a href="#/login">已有账号？登录</a>}
          {mode !== "register" && <a href="#/register">没有账号？注册</a>}
          {mode !== "verify" && <a href="#/verify">输入验证码</a>}
        </div>
      </form>
    </div>
  );
}
```

验证页初始 `email`：`useState(() => sessionStorage.getItem("agenthowl.verify_email") ?? "")`（try/catch 包一层，隐私模式下 sessionStorage 可能抛）。`LoginPage.module.css`：`.page`（居中 grid）、`.card`（max-width 400、padding 24、现有 `.card`/`.dialog` 同风格）、`.title`、`.error`（沿用 History.module.css 的错误条样式）、`.notice`、`.actions`（flex gap 8）、`.links`（flex gap 12，font-size 13）。

- [ ] **Step 7: `App.tsx`**

- 启动：`useEffect(() => { setUnauthorizedHandler(() => void useAuth.getState().load()); void useAuth.getState().load(); return () => setUnauthorizedHandler(null); }, []);`
- `const status = useAuth((s) => s.status); const user = useAuth((s) => s.user);`
- `game` 路由：渲染 `<GamePage gameId token share viewer />`（Task 11 改 props；本任务先把 `share` 传过去并在 GamePage props 里加可选 `share?: string`，暂不消费）。
- 登录相关路由：`login` / `register` / `verify` → `<LoginPage mode={route} next={...} />`，其中 `next` 取 `sessionStorage.getItem("agenthowl.next") ?? "#/"`。
- 受保护路由（lobby / history / agents / providers / admin）：`status === "loading"` → `<p className="text-muted">载入中…</p>`；`status === "anon"` → 记录 `sessionStorage.setItem("agenthowl.next", location.hash)` 后渲染 `<LoginPage mode="login" next={location.hash || "#/"} />`（不改 hash，刷新仍停在原路由）；`authed` → 原页面。`admin` 路由非 admin → `<Lobby />`。
- 导航：右侧（`marginLeft: "auto"`）`user ? <><span>{user.username}{user.role === "admin" ? " · admin" : ""}</span>{user.role === "admin" && <a href="#/admin">用户</a>}<button className="btn btn-ghost" onClick={() => void logout()}>登出</button></> : <a href="#/login">登录</a>`。登出后 `window.location.hash = "#/login"`。

- [ ] **Step 8: 跑 `npm run check`**

Run: `cd frontend && npm run check`
Expected: lint / tsc / vitest 全绿。tsc 若因 `GamePage` 的 `replay` prop 移除而报错，本任务一并把 `GamePage` 里 `replay` 分支删掉（Task 11 会重写引导逻辑，这里只保证编译：`replay` prop 删除，`effectiveViewer = viewer`，无 token 时暂时仍走 `auth` 错误态）。`GamePage.test.tsx` 里的 `replay` 用例先删除（Task 11 补 cookie 用例）。

- [ ] **Step 9: Commit**

```bash
git add frontend/src
git commit -m "feat(frontend): 登录态 store 与登录/注册/验证页、share 路由、401 回调、导航用户位 (issue #114)"
```

---

### Task 11: 前端 share / cookie 模式：GamePage、WS、音频、历史表、分享框、建局

**Files:**
- Modify: `frontend/src/api/rest.ts`（`GameAuth`、各 getter 签名、`audioUrl`）、`frontend/src/api/ws.ts:49-60, 72, 125, 152`、`frontend/src/store/voice.ts:56, 157-171`、`frontend/src/pages/GamePage.tsx`、`frontend/src/api/history.ts`、`frontend/src/components/HistoryTable/HistoryTable.tsx:100-110`、`frontend/src/pages/History.tsx`、`frontend/src/components/ShareDialog/ShareDialog.tsx`、`frontend/src/pages/Lobby.tsx:126-130, 380-392`
- Test: `frontend/src/api/rest.test.ts`、`src/api/ws.test.ts`、`src/pages/GamePage.test.tsx`、`src/components/HistoryTable/HistoryTable.test.tsx`、`src/components/ShareDialog/ShareDialog.test.tsx`（若无则新建）

**Interfaces:**
- Consumes: Task 10 `ParsedHash.share`、`req` 的 `query`。
- Produces: `export interface GameAuth { token?: string; share?: string }`；`getMeta(gameId, auth?)`、`getState(gameId, auth?)`、`getReplay(gameId, auth?)`、`getEvents(gameId, auth, fromSeq)`、`getGameAvatars(gameId, auth?)`、`getAudioManifest(gameId, auth?)`、`audioUrl(gameId, seq, part, auth?)`；`useLiveEvents({gameId, auth, enabled})`；`useVoice.playSeq(gameId, seq, parts, auth?)`；`GameSummary.owner_id / owner_name / share_token`；`CreateGameResponse.share_token`；`ShareDialogProps.shareToken`。

- [ ] **Step 1: 写 / 改测试**

`rest.test.ts` 追加：

```ts
it("GameAuth：token 走 Authorization，share 走 ?share=，都没有则裸请求带 cookie", async () => {
  const calls: [string, RequestInit][] = [];
  vi.stubGlobal("fetch", vi.fn((url: string, init: RequestInit) => { calls.push([url, init]); return Promise.resolve(new Response("{}", { status: 200 })); }));
  await getMeta("g_1", { token: "T" });
  await getMeta("g_1", { share: "S" });
  await getMeta("g_1");
  expect((calls[0][1].headers as Record<string, string>).Authorization).toBe("Bearer T");
  expect(calls[1][0]).toBe("/api/v1/games/g_1/meta?share=S");
  expect(calls[2][0]).toBe("/api/v1/games/g_1/meta");
  expect(calls[2][1].credentials).toBe("same-origin");
  expect(audioUrl("g_1", 3, 0, { share: "S" })).toBe("/api/v1/games/g_1/audio/3/0?share=S");
  expect(audioUrl("g_1", 3, 0, { token: "T" })).toBe("/api/v1/games/g_1/audio/3/0?token=T");
  expect(audioUrl("g_1", 3, 0)).toBe("/api/v1/games/g_1/audio/3/0");
});
```

`ws.test.ts`：把现有 URL 断言改为三种形式：`?token=T&from_seq=`、`?game_id=g_1&share=S&from_seq=`、`?game_id=g_1&from_seq=`（照现有测试的 WebSocket mock 写法）。

`HistoryTable.test.tsx`：finished 行链接为 `#/g/{id}`（登录态 GM）；带 `onShare` 时有「分享」按钮；`showOwner` 时多一列「创建者」显示 `owner_name`。

`GamePage.test.tsx`：删除 `replay=1` 用例；新增「无 token、viewer=GM：`/meta` 裸请求（cookie）→ 200 装入回放」与「`share` 模式：请求带 `?share=`」两条（mock fetch 的 URL 断言）。

`ShareDialog.test.tsx`：观众链接为 `#/g/{id}?share=S`；`shareToken=null` 时不显示观众链接。

- [ ] **Step 2: 跑测试确认失败**

Run: `cd frontend && npx vitest run src/api src/pages/GamePage.test.tsx src/components/HistoryTable src/components/ShareDialog`
Expected: FAIL

- [ ] **Step 3: `rest.ts`**

```ts
/** 对局读端点的凭据（issue #114）：对局 token（Bearer）或分享 token（?share=）；都没有 → 只靠 cookie 会话。 */
export interface GameAuth {
  token?: string;
  share?: string;
}

function gameOpts(auth: GameAuth | undefined, extra: ReqOptions = {}): ReqOptions {
  const o: ReqOptions = { ...extra };
  if (auth?.token) o.token = auth.token;
  else if (auth?.share) o.query = { ...(o.query ?? {}), share: auth.share };
  return o;
}
```

各 getter 改签名（`getMeta(gameId, auth?: GameAuth)` 等），内部 `req(..., gameOpts(auth))`；`getEvents(gameId, auth, fromSeq)` 把 `from_seq` 放进 `query`。`audioUrl(gameId, seq, part, auth?)`：token → `?token=`，share → `?share=`，否则裸。`CreateGameResponse.spectator_token` → `share_token: string | null`。

- [ ] **Step 4: `ws.ts` 与 `voice.ts`**

`UseLiveEventsArgs` → `{ gameId: string | null; auth: GameAuth; enabled: boolean }`；`wsUrl(fromSeq, gameId, auth)`：token → `?token=…&from_seq=`；share → `?game_id=…&share=…&from_seq=`；否则 `?game_id=…&from_seq=`。effect 守卫改为 `if (!enabled || !gameId) return;`；依赖数组 `[gameId, auth.token, auth.share, enabled]`。音频帧 URL：`frame.url` 拼接 `audioUrl` 同样规则（抽一个 `withAuth(url, auth)` 小函数：token → `?token=`，share → `?share=`，否则原样）。
`voice.ts`：`playSeq(gameId, seq, parts, auth?: GameAuth)`，内部 `audioUrl(gameId, seq, part.part, auth)`。

- [ ] **Step 5: `GamePage.tsx`**

- Props：`{ gameId?: string; token?: string; share?: string; viewer?: Viewer }`，删 `replay`。
- `const auth: GameAuth = useMemo(() => ({ token, share }), [token, share]);`
- 引导 effect：删掉 `replay` 分支；守卫改为 `if (!gameId || !viewer) { setErrorKind("auth"); return; }`。统一路径：`getMeta(gameId, auth)` → 成功即回放装入（`store.load(meta, { gameId, token: token ?? "", viewer, mode: "replay" })`）；403 → `/state`（`getState(gameId, auth)`）直播；401 → `auth` 错误态；404 → `4404`。`getGameAvatars(gameId, auth)`、`getAudioManifest(gameId, auth)`、`playSeq(..., auth)`、`useLiveEvents({ gameId, auth, enabled: mode === "live" && ready })`。依赖数组 `[gameId, token, share, viewer]`。
- `ErrorState` 的 `auth` 文案（`ErrorState.tsx:62` 附近）改为「请登录，或使用建局者提供的分享链接」并加一个 `<a href="#/login">去登录</a>`。

- [ ] **Step 6: 历史 / 分享 / 建局**

- `api/history.ts` `GameSummary` 加 `owner_id: string | null; owner_name: string | null; share_token: string | null;`。
- `HistoryTable`：props 加 `showOwner?: boolean`、`onShare?: (row: GameSummary) => void`。finished 行主按钮 `href={`#/g/${row.game_id}`}`（登录态 GM）；live 行改为同样的链接「观看」（本人会话即 GM）；有 `onShare` 时每行加「分享」按钮（`share_token !== null` 才启用）。`showOwner` 时在「板子」列后加「创建者」列显示 `owner_name ?? "—"`。
- `History.tsx`：`const user = useAuth((s) => s.user)`；`<HistoryTable showOwner={user?.role === "admin"} onShare={setSharing} />`；`sharing !== null` 时渲染 `<ShareDialog gameId shareToken gmToken={null} />`（ShareDialog 的 `gmToken` 改为 `string | null`，null 时不显示 GM 链接；按钮「进入」改为跳 `#/g/{id}`）。副标题去掉「事件流存于 data/games/」改为「只显示你创建的对局」（admin：「全部用户的对局」）。
- `ShareDialog`：`spectatorToken` → `shareToken: string | null`，`linkFor(gameId, "share", token)`；标签「观众链接 · 仅公开信息，可匿名打开」。
- `Lobby.tsx`：`spectatorToken: res.spectator_token` → `shareToken: res.share_token`，传给 `ShareDialog`。

- [ ] **Step 7: 跑 `npm run check`**

Run: `cd frontend && npm run check`
Expected: 全绿。

- [ ] **Step 8: Commit**

```bash
git add frontend/src
git commit -m "feat(frontend): 对局页 token/share/cookie 三种凭据，历史表分享与创建者列，ShareDialog 改 share 链接 (issue #114)"
```

---

### Task 12: 管理员用户页

**Files:**
- Create: `frontend/src/api/admin.ts`、`frontend/src/pages/AdminUsers.tsx`、`frontend/src/pages/AdminUsers.module.css`
- Modify: `frontend/src/App.tsx`（`admin` 路由渲染）
- Test: `frontend/src/pages/AdminUsers.test.tsx`

**Interfaces:**
- Consumes: Task 8 的 `/admin/users*`；Task 10 `UserPublic`、`useAuth`。
- Produces: `listUsers()`, `patchUser(id, {role?, status?})`, `verifyUser(id)`；`<AdminUsers />`。

- [ ] **Step 1: 写测试**

```tsx
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { useAuth } from "../store/auth";
import AdminUsers from "./AdminUsers";

const me = { user_id: "u_me", username: "root", email: "r@x", role: "admin" as const, status: "active" as const, email_verified: true, created_at: "t" };
const bob = { user_id: "u_bob", username: "bob", email: "b@x", role: "user" as const, status: "active" as const, email_verified: false, created_at: "t" };

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

describe("AdminUsers", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("列出用户，自己那行按钮禁用，禁用他人后刷新", async () => {
    useAuth.setState({ user: me, status: "authed" });
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      if (init?.method === "PATCH") return Promise.resolve(json(200, { ...bob, status: "disabled" }));
      if (init?.method === "POST") return Promise.resolve(json(200, { ...bob, email_verified: true }));
      return Promise.resolve(json(200, [me, bob]));
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<AdminUsers />);
    await waitFor(() => expect(screen.getByText("bob")).toBeInTheDocument());
    const rows = screen.getAllByRole("row");
    expect(rows).toHaveLength(3);
    expect(screen.getByRole("button", { name: "禁用 bob" })).toBeEnabled();
    expect(screen.queryByRole("button", { name: "禁用 root" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "禁用 bob" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith("/api/v1/admin/users/u_bob", expect.objectContaining({ method: "PATCH" })));
    fireEvent.click(screen.getByRole("button", { name: "标记已验证 bob" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith("/api/v1/admin/users/u_bob/verify", expect.objectContaining({ method: "POST" })));
  });
});
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd frontend && npx vitest run src/pages/AdminUsers.test.tsx`
Expected: FAIL

- [ ] **Step 3: 实现**

`src/api/admin.ts`：

```ts
import type { UserPublic } from "./auth";
import { req } from "./rest";

export function listUsers(): Promise<UserPublic[]> {
  return req<UserPublic[]>("GET", "/admin/users");
}

export function patchUser(userId: string, body: { role?: "admin" | "user"; status?: "active" | "disabled" }): Promise<UserPublic> {
  return req<UserPublic>("PATCH", `/admin/users/${userId}`, { body });
}

export function verifyUser(userId: string): Promise<UserPublic> {
  return req<UserPublic>("POST", `/admin/users/${userId}/verify`);
}
```

`AdminUsers.tsx`：表格列「用户名 / 邮箱 / 角色 / 状态 / 邮箱验证 / 注册时间 / 操作」；操作：`禁用 {name}` / `启用 {name}`、`设为管理员 {name}` / `降为普通用户 {name}`、未验证时 `标记已验证 {name}`（按钮 `aria-label` 用这些精确文案）；自己那行不渲染操作按钮。每次操作后用响应行替换列表项；错误显示在顶部错误条（`ApiError.detail`）。样式复用 History 的表格 class。

`App.tsx`：`admin` 路由 → `user?.role === "admin" ? <AdminUsers /> : <Lobby />`。

- [ ] **Step 4: 跑 `npm run check`**

Run: `cd frontend && npm run check`
Expected: 全绿。

- [ ] **Step 5: Commit**

```bash
git add frontend/src
git commit -m "feat(frontend): 管理员用户页（禁用/启用、角色、手工验证） (issue #114)"
```

---

### Task 13: 文档、部署、PRD、全套门禁、后续 issue

**Files:**
- Modify: `.env.example`、`README.md:160-170, 196-202`、`Dockerfile:38-39`、`docs/specs/requirements.md`（§4.4.5 `:579-583`、§5.4 `:753`）
- 无代码测试；验收 = 全套门禁 + Docker 冒烟。

- [ ] **Step 1: `.env.example`**

删除 `AGENTHOWL_PUBLIC_HISTORY` 段，追加：

```
# ---- 多用户（issue #114）----
# 站点密钥：签分享链接；缺省自动生成并写入 backend/data/secret.key（0600）。轮换会让旧分享链接失效。
#AGENTHOWL_SECRET_KEY=
# 用户库（SQLite）路径，默认 data/users.db
#AGENTHOWL_USERS_DB=data/users.db
# 会话 cookie 的 Secure 标记：公网 HTTPS 保持 1；本地 http 调试设 0
#AGENTHOWL_COOKIE_SECURE=1
# 反代后信任 X-Forwarded-For（限流按真实 IP）
#AGENTHOWL_TRUST_PROXY=0
# 管理员引导：三者齐全时启动创建（已存在则跳过，不改密码）
#AGENTHOWL_ADMIN_USERNAME=admin
#AGENTHOWL_ADMIN_EMAIL=admin@example.com
#AGENTHOWL_ADMIN_PASSWORD=
# 邮箱验证码 SMTP：HOST 为空 = 不验证邮箱（注册即可登录）
#AGENTHOWL_SMTP_HOST=
#AGENTHOWL_SMTP_PORT=587
#AGENTHOWL_SMTP_USER=
#AGENTHOWL_SMTP_PASSWORD=
#AGENTHOWL_SMTP_FROM=
#AGENTHOWL_SMTP_STARTTLS=1
```

- [ ] **Step 2: README**

- 「历史对局」段：删除 `AGENTHOWL_PUBLIC_HISTORY` 说明与 `?replay=1`，改为「列表只含自己创建的对局（admin 全部）；点进即上帝视角；『分享』生成匿名可看的 `?share=` 链接」。
- 「前端」段 `?spec=` → `?share=`，说明 share 是 HMAC 派生、重启不失效。
- 新增「## 多用户 / Multi-user」小节：注册流程（SMTP 可选）、`AGENTHOWL_ADMIN_*` 引导、`python -m app.cli.claim --user <name>` 迁移旧数据、公网部署清单（HTTPS 反代 + `COOKIE_SECURE=1` + `TRUST_PROXY=1`）、外部 Agent 客户端入座需带 `host_token`。
- 「API 快速开始」里的 `curl` 示例：建局前先 `POST /auth/login` 并用 `-c cookies.txt -b cookies.txt`；`/join` 带 `Authorization: Bearer <host_token>`。

- [ ] **Step 3: Dockerfile / compose**

healthcheck URL 改为 `http://127.0.0.1:8000/api/v1/health`。compose 不变（`./backend/data` 卷已覆盖 `users.db` 与 `secret.key`）。

- [ ] **Step 4: PRD**

§4.4.5：把「单用户本地部署假设」句改为「Provider 按用户归属（BYOK），密钥仍明文 0600；加密落盘见后续 issue」。§5.4 改为「认证、用户与会话」：三层凭据（对局 token / HMAC 分享 token / cookie 会话）、归属规则、admin 角色，引用本 spec。

- [ ] **Step 5: 全套门禁**

```bash
cd backend && uv run pytest -q --ignore=tests/test_api_e2e.py && uv run pytest -q tests/test_api_e2e.py && uv run ruff check . && uv run ruff format --check . && uv run mypy app && uv run pytest -q tests/test_agent_profile.py::test_importing_registry_does_not_load_litellm
cd ../frontend && npm run check
cd .. && git diff --stat main -- backend/app/engine   # 必须为空
```

- [ ] **Step 6: Docker 冒烟（本机）**

`docker compose up -d --build`；`.env` 临时加 `AGENTHOWL_ADMIN_*` 与 `AGENTHOWL_COOKIE_SECURE=0`；浏览器：注册普通用户（免验证）→ 建局 → 对局页 → 复制分享链接在隐私窗口打开 → 管理员登录看到两人的局 → `python -m app.cli.claim --dry-run` 对旧数据计数。记录结果到 PR 描述。

- [ ] **Step 7: Commit + 后续 issue**

```bash
git add .env.example README.md Dockerfile docs/specs/requirements.md
git commit -m "docs: 多用户部署说明、PRD §4.4.5/§5.4 更新、healthcheck 改 /health (issue #114)"
```

用 `gh issue create` 建四条后续（spec §12）：密码找回；Provider 密钥加密落盘；会话管理 / 改密码；对局「公开」标记与公开大厅。每条正文引用本 spec 路径与相关代码位置。

---

## 自检记录

- 覆盖：spec §1–§2 → T1/T2；§3 → T3；§4 → T2/T3；§5 → T4/T5/T6/T9；§6 → T6/T7/T11；§7 → T8/T12；§8 → T10/T11/T12；§9 → T3/T13；§10 → 各任务的 404/401/文案断言 + T13 清单；§11 → 各任务测试 + T13 门禁；§12 → T13。
- 类型一致性：`GameAuth`（T11）与 `ParsedHash.share`（T10）；`resolve_viewer` / `_share_viewer` / `_session_viewer` / `viewer_of`（T6）被 T7 导入；`visible_providers`（T5）被 T6 导入；`Role` / `Status`（T1）被 T8 导入；`is_expired`（T1）被 T3 导入；`experience_store_for`（T4）在 `main.py` 装配。
- Review Focus 五条均已在对应任务写入测试。
