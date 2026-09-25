"""Agent 档案库 + 建局辅助端点（issue #26）。无鉴权：与建局一致，M3 单用户本地部署。"""

from __future__ import annotations

import secrets
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from app.agent.profile import AgentProfile
from app.agent.skills import SkillError, SkillLibrary
from app.engine.config import PRESET_NAMES, build_preset
from app.runtime.agent_library import AgentLibraryStore, StoredAgent
from app.runtime.provider_store import ProviderStore
from app.schemas.presets import PresetInfo, preset_info

router = APIRouter()


def get_library(request: Request) -> AgentLibraryStore:
    lib: AgentLibraryStore = request.app.state.agent_library
    return lib


def get_skill_library(request: Request) -> SkillLibrary:
    lib: SkillLibrary = request.app.state.games.skill_library
    return lib


def get_provider_store(request: Request) -> ProviderStore:
    store: ProviderStore = request.app.state.provider_store
    return store


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _check_profile(
    profile: AgentProfile,
    lib: AgentLibraryStore,
    skills: SkillLibrary,
    providers: ProviderStore,
    *,
    exclude_id: str | None,
) -> None:
    """名字必填且唯一；memory_id 唯一；技能名可解析；provider（若配置）须存在。"""
    if not profile.name:
        raise HTTPException(status_code=422, detail="档案须有名字（name）")
    for other in lib.list():
        if other.agent_id == exclude_id:
            continue
        if other.profile.name == profile.name:
            raise HTTPException(status_code=409, detail=f"已有同名档案：{profile.name}")
        if profile.memory_id and other.profile.memory_id == profile.memory_id:
            raise HTTPException(
                status_code=409,
                detail=f"memory_id {profile.memory_id!r} 已被档案「{other.profile.name}」使用",
            )
    try:
        skills.resolve(profile.skills)
    except SkillError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if profile.provider is not None and providers.get(profile.provider) is None:
        raise HTTPException(status_code=400, detail=f"provider 不存在：{profile.provider}")


@router.get("/agents")
def list_agents(lib: AgentLibraryStore = Depends(get_library)) -> list[StoredAgent]:
    return lib.list()


@router.post("/agents", status_code=201)
def create_agent(
    profile: AgentProfile,
    lib: AgentLibraryStore = Depends(get_library),
    skills: SkillLibrary = Depends(get_skill_library),
    providers: ProviderStore = Depends(get_provider_store),
) -> StoredAgent:
    _check_profile(profile, lib, skills, providers, exclude_id=None)
    now = _now()
    stored = StoredAgent(
        agent_id=f"a_{secrets.token_hex(4)}", profile=profile, created_at=now, updated_at=now
    )
    lib.put(stored)
    return stored


@router.get("/agents/{agent_id}")
def get_agent(agent_id: str, lib: AgentLibraryStore = Depends(get_library)) -> StoredAgent:
    stored = lib.get(agent_id)
    if stored is None:
        raise HTTPException(status_code=404, detail=f"档案不存在：{agent_id}")
    return stored


@router.put("/agents/{agent_id}")
def update_agent(
    agent_id: str,
    profile: AgentProfile,
    lib: AgentLibraryStore = Depends(get_library),
    skills: SkillLibrary = Depends(get_skill_library),
    providers: ProviderStore = Depends(get_provider_store),
) -> StoredAgent:
    existing = lib.get(agent_id)
    if existing is None:
        raise HTTPException(status_code=404, detail=f"档案不存在：{agent_id}")
    _check_profile(profile, lib, skills, providers, exclude_id=agent_id)
    stored = existing.model_copy(update={"profile": profile, "updated_at": _now()})
    lib.put(stored)
    return stored


@router.delete("/agents/{agent_id}", status_code=204, response_class=Response)
def delete_agent(agent_id: str, lib: AgentLibraryStore = Depends(get_library)) -> Response:
    if not lib.delete(agent_id):
        raise HTTPException(status_code=404, detail=f"档案不存在：{agent_id}")
    return Response(status_code=204)


@router.get("/skills")
def list_skills(skills: SkillLibrary = Depends(get_skill_library)) -> list[dict[str, Any]]:
    return [
        {
            "name": s.name,
            "description": s.description,
            "roles": sorted(r.value for r in s.roles),
            "phases": sorted(s.phases),
        }
        for s in (skills.get(n) for n in skills.names())
    ]


@router.get("/presets")
def list_presets() -> list[PresetInfo]:
    return [preset_info(name, build_preset(name)) for name in PRESET_NAMES]
