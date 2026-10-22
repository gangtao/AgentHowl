"""registry 的归属透传（issue #114）：owner_id 进 meta、经验存储按 owner 分、provider 白名单。"""

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
    reg.create(
        cfg,
        allow_spectators=True,
        agents={"0": AgentProfile(model="m", provider="p_a")},
        allowed_providers={"p_a"},
    )
    with pytest.raises(ValueError):
        reg.create(
            cfg,
            allow_spectators=True,
            agents={"0": AgentProfile(model="m", provider="p_b")},
            allowed_providers={"p_a"},
        )
    # None = 不限制（admin / CLI）
    reg.create(cfg, allow_spectators=True, agents={"0": AgentProfile(model="m", provider="p_b")})
