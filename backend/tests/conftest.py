"""pytest 共享夹具。引擎测试零 IO、零 mock；API 测试用内存用户库、免验证、关限流（#114）。"""

from __future__ import annotations

import os
from collections.abc import Iterator
from typing import Any

import pytest
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


@pytest.fixture(autouse=True)
def _isolate_agenthowl_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """issue #124：litellm 在 import 时 load_dotenv()，从 .venv 向上找到仓库根的 .env（docker
    compose 用），把 AGENTHOWL_ADMIN_* / TTS_URL 等塞进 os.environ。全量跑时一旦有测试模块
    惰性加载了 litellm，之后每个 make_app() 都会按 .env 引导出一个管理员，test_api_admin
    的用户列表 / 单管理员断言随之失败；单跑该文件不触发，故只在全量时失败。
    每个测试开始前清掉 AGENTHOWL_*（冒烟开关 AGENTHOWL_SMOKE_MODEL 除外），
    需要环境引导的测试自己 setenv。"""
    for key in list(os.environ):
        if key.startswith("AGENTHOWL_") and "SMOKE" not in key:
            monkeypatch.delenv(key, raising=False)
    yield


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
