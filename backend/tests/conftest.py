"""pytest 共享夹具。引擎测试零 IO、零 mock；API 测试用内存用户库、免验证、关限流（#114）。"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.main import create_app
from app.runtime.agent_library import InMemoryAgentLibrary
from app.runtime.experience_store import InMemoryExperienceStore
from app.runtime.mailer import NullMailer
from app.runtime.provider_store import InMemoryProviderStore
from app.runtime.ratelimit import RateLimiter
from app.runtime.users import InMemoryUserStore, User, hash_password, new_user_id, now_iso
from app.store.event_store import InMemoryEventStore

TEST_PASSWORD = "password1"


def make_app(**kwargs: Any) -> FastAPI:
    """create_app 的测试默认：内存事件库、内存用户库、NullMailer（注册免验证）、限流关、
    内存 Agent 库 / provider / 经验库（互不串）、
    cookie 不带 Secure（TestClient 走 http）。kwargs 覆盖任一默认。"""
    defaults: dict[str, Any] = {
        "store": InMemoryEventStore(),
        "user_store": InMemoryUserStore(),
        "mailer": NullMailer(),
        "rate_limiter": RateLimiter.disabled(),
        "secret": b"test-secret",
        "cookie_secure": False,
        "agent_library": InMemoryAgentLibrary(),
        "provider_store": InMemoryProviderStore(),
        "experience_store": InMemoryExperienceStore(),
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
    r = client.post("/api/v1/auth/login", json={"identifier": username, "password": TEST_PASSWORD})
    assert r.status_code == 200, r.text
    me: dict[str, Any] = client.get("/api/v1/auth/me").json()
    return me


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}
