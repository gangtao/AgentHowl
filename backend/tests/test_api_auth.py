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
        assert (
            client.post(
                "/api/v1/auth/verify", json={"email": "a@x.io", "code": "999999"}
            ).status_code
            == 400
        )
    # 第 6 次即使码对也作废
    assert (
        client.post("/api/v1/auth/verify", json={"email": "a@x.io", "code": code}).status_code
        == 400
    )


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


def _reg(client: TestClient) -> None:
    client.post(
        "/api/v1/auth/register",
        json={"username": "alice", "email": "a@x.io", "password": "password1"},
    )


def test_resend_does_not_reset_attempts(client: TestClient, mailer: RecordingMailer) -> None:
    _reg(client)
    bad = {"email": "a@x.io", "code": "999999"}
    for _ in range(5):
        assert client.post("/api/v1/auth/verify", json=bad).status_code == 400
    assert client.post("/api/v1/auth/resend", json={"email": "a@x.io"}).status_code == 200
    r = client.post("/api/v1/auth/verify", json={"email": "a@x.io", "code": _code_from(mailer)})
    assert r.status_code == 400


def test_resend_after_expiry_resets_attempts(client: TestClient, mailer: RecordingMailer) -> None:
    _reg(client)
    for _ in range(5):
        client.post("/api/v1/auth/verify", json={"email": "a@x.io", "code": "999999"})
    users = client.app.state.users  # type: ignore[attr-defined]
    uid = users.get_by_email("a@x.io").user_id
    old = users.get_email_code(uid)
    users.put_email_code(old.model_copy(update={"expires_at": "2000-01-01T00:00:00+00:00"}))
    assert client.post("/api/v1/auth/resend", json={"email": "a@x.io"}).status_code == 200
    assert users.get_email_code(uid).attempts == 0
    r = client.post("/api/v1/auth/verify", json={"email": "a@x.io", "code": _code_from(mailer)})
    assert r.status_code == 200
