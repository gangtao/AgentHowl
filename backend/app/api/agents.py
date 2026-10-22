"""Agent 档案库 + 建局辅助端点（issue #26）。登录后按归属访问（issue #114）。"""

from __future__ import annotations

import secrets
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from app.agent.profile import AgentProfile
from app.agent.skills import SkillError, SkillLibrary
from app.api.auth import can_access, require_user
from app.engine.config import PRESET_NAMES, build_preset
from app.runtime.agent_library import AgentLibraryStore, StoredAgent
from app.runtime.provider_store import ProviderStore
from app.runtime.registry import BYOK_REQUIRED_MSG
from app.runtime.users import User
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


def _visible_agents(lib: AgentLibraryStore, user: User) -> list[StoredAgent]:
    """当前用户可见的档案（admin 全部；普通用户仅自己的）。"""
    return [s for s in lib.list() if can_access(user, s.owner_id)]


def _get_owned_agent(lib: AgentLibraryStore, user: User, agent_id: str) -> StoredAgent:
    """取档案；不存在或无权访问一律 404（不泄露存在性）。"""
    stored = lib.get(agent_id)
    if stored is None or not can_access(user, stored.owner_id):
        raise HTTPException(status_code=404, detail=f"档案不存在：{agent_id}")
    return stored


def _check_profile(
    profile: AgentProfile,
    lib: AgentLibraryStore,
    skills: SkillLibrary,
    providers: ProviderStore,
    *,
    user: User,
    exclude_id: str | None,
) -> None:
    """名字必填且在自己的集合内唯一；memory_id 同理；技能名可解析；provider 须存在且可访问。"""
    if not profile.name:
        raise HTTPException(status_code=422, detail="档案须有名字（name）")
    for other in lib.list():
        if other.agent_id == exclude_id or other.owner_id != user.user_id:
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
    if profile.provider is None and user.role != "admin":
        raise HTTPException(status_code=400, detail=BYOK_REQUIRED_MSG)
    if profile.provider is not None:
        p = providers.get(profile.provider)
        if p is None or not can_access(user, p.owner_id):
            raise HTTPException(status_code=400, detail=f"provider 不存在：{profile.provider}")


@router.get("/agents")
def list_agents(
    user: User = Depends(require_user), lib: AgentLibraryStore = Depends(get_library)
) -> list[StoredAgent]:
    return _visible_agents(lib, user)


@router.post("/agents", status_code=201)
def create_agent(
    profile: AgentProfile,
    user: User = Depends(require_user),
    lib: AgentLibraryStore = Depends(get_library),
    skills: SkillLibrary = Depends(get_skill_library),
    providers: ProviderStore = Depends(get_provider_store),
) -> StoredAgent:
    _check_profile(profile, lib, skills, providers, user=user, exclude_id=None)
    now = _now()
    stored = StoredAgent(
        agent_id=f"a_{secrets.token_hex(4)}",
        profile=profile,
        created_at=now,
        updated_at=now,
        owner_id=user.user_id,
    )
    lib.put(stored)
    return stored


@router.get("/agents/{agent_id}")
def get_agent(
    agent_id: str,
    user: User = Depends(require_user),
    lib: AgentLibraryStore = Depends(get_library),
) -> StoredAgent:
    return _get_owned_agent(lib, user, agent_id)


@router.put("/agents/{agent_id}")
def update_agent(
    agent_id: str,
    profile: AgentProfile,
    user: User = Depends(require_user),
    lib: AgentLibraryStore = Depends(get_library),
    skills: SkillLibrary = Depends(get_skill_library),
    providers: ProviderStore = Depends(get_provider_store),
) -> StoredAgent:
    existing = _get_owned_agent(lib, user, agent_id)
    _check_profile(profile, lib, skills, providers, user=user, exclude_id=agent_id)
    stored = existing.model_copy(update={"profile": profile, "updated_at": _now()})
    lib.put(stored)
    return stored


@router.delete("/agents/{agent_id}", status_code=204, response_class=Response)
def delete_agent(
    agent_id: str,
    user: User = Depends(require_user),
    lib: AgentLibraryStore = Depends(get_library),
) -> Response:
    _get_owned_agent(lib, user, agent_id)
    lib.delete(agent_id)
    return Response(status_code=204)


@router.get("/skills")
def list_skills(
    _: User = Depends(require_user), skills: SkillLibrary = Depends(get_skill_library)
) -> list[dict[str, Any]]:
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
def list_presets(_: User = Depends(require_user)) -> list[PresetInfo]:
    return [preset_info(name, build_preset(name)) for name in PRESET_NAMES]
