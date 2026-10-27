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
    validate_email("first.last+tag@sub.example.co")
    for bad in (
        "",
        "noat",
        "a@" + "x" * 260,
        "a@x.com,b@y.com",
        "a@x.com b@y.com",
        "a\r\n@x.com",
        "a@@x.com",
        "a@x",
        "a@.x.com",
    ):
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


def test_bootstrap_admin_logs_error_when_username_taken_by_non_admin(
    store: UserStore, caplog: pytest.LogCaptureFixture
) -> None:
    """issue #120：普通用户抢注了管理员用户名 → 不静默跳过，ERROR 级告警且不建管理员。"""
    import logging

    store.put(_user("u_9", "root", "someone@x.io"))
    with caplog.at_level(logging.ERROR, logger="app.runtime.users"):
        assert bootstrap_admin(store, username="root", email="r@x.io", password="password1") is None
    assert any("已被非管理员账号占用" in r.getMessage() for r in caplog.records)
    assert store.count() == 1 and store.get("u_9").role == "user"  # type: ignore[union-attr]
