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


def wait_game_done(client: TestClient, gid: str, timeout: float = 60.0) -> Any:
    """事件驱动地等 runner task 结束（issue #74）：在 TestClient 的后台事件循环上 await 任务，
    而不是从测试线程 sleep 轮询（满负载下 30s 轮询截止会偶发超时）。超时不取消任务，
    断言信息带当前阶段 / 轮次便于排查。返回 GameHandle。"""
    import asyncio

    handle = client.app.state.games.get(gid)  # type: ignore[attr-defined]
    assert handle.task is not None, f"对局 {gid} 尚未开始"

    async def _wait(task: Any, t: float) -> bool:
        _done, pending = await asyncio.wait({task}, timeout=t)
        return not pending

    portal = getattr(client, "portal", None)
    if portal is not None:
        finished = client.portal.call(_wait, handle.task, timeout)
    else:
        # 不在 `with TestClient(app)` 块里：没有常驻 portal，只能轮询 done()（间隔很短）
        import time

        deadline = time.time() + timeout
        while not handle.task.done() and time.time() < deadline:
            time.sleep(0.02)
        finished = handle.task.done()
    if not finished:
        st = handle.runner.state if handle.runner is not None else None
        where = f"phase={st.phase} round={st.round} seq={st.state_version}" if st else "未开局"
        raise AssertionError(f"对局 {gid} 在 {timeout}s 内未结束（{where}）")
    return handle


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
