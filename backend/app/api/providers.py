"""模型服务 Provider CRUD + test/models 端点（issue #26）。登录后按归属访问（issue #114）。

密钥语义：POST 直接落库；PUT 省略 api_key = 保留原密钥，传 "" = 清除；响应一律 ProviderPublic
（不含明文密钥）。DELETE 前扫 agent_library，档案仍引用则 409。
"""

from __future__ import annotations

import secrets
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from app.agent.provider import Provider, ProviderInput, ProviderPublic, redact_secret
from app.api.auth import can_access, require_user
from app.runtime.agent_library import AgentLibraryStore
from app.runtime.netguard import private_api_base_blocking_enabled, private_api_base_reason
from app.runtime.provider_probe import ProviderProbe
from app.runtime.provider_store import ProviderStore
from app.runtime.users import User

router = APIRouter()


class _TestRequest(BaseModel):
    """POST /providers/{id}/test 请求体：model 缺省=用 provider.default_model。"""

    model: str | None = None


def get_provider_store(request: Request) -> ProviderStore:
    store: ProviderStore = request.app.state.provider_store
    return store


def get_provider_probe(request: Request) -> ProviderProbe:
    probe: ProviderProbe = request.app.state.provider_probe
    return probe


def get_agent_library(request: Request) -> AgentLibraryStore:
    lib: AgentLibraryStore = request.app.state.agent_library
    return lib


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def visible_providers(store: ProviderStore, user: User) -> list[Provider]:
    """当前用户可见的 provider（admin 全部；普通用户仅自己的）。"""
    return [p for p in store.list() if can_access(user, p.owner_id)]


def _get_owned_provider(store: ProviderStore, user: User, provider_id: str) -> Provider:
    """取 provider；不存在或无权访问一律 404（不泄露存在性）。"""
    p = store.get(provider_id)
    if p is None or not can_access(user, p.owner_id):
        raise HTTPException(status_code=404, detail=f"provider 不存在：{provider_id}")
    return p


def _check_api_base(api_base: str | None) -> None:
    """issue #120：公网部署开启 AGENTHOWL_BLOCK_PRIVATE_API_BASE 后，
    拒绝指向内网 / 本机的 api_base。"""
    if not private_api_base_blocking_enabled():
        return
    reason = private_api_base_reason(api_base)
    if reason is not None:
        raise HTTPException(status_code=400, detail=f"api_base 不允许指向内网 / 本机（{reason}）")


def _check_name_unique(
    name: str, store: ProviderStore, *, owner_id: str, exclude_id: str | None
) -> None:
    """同名按 owner 唯一：只与同 owner 的 provider 比较。"""
    for other in store.list():
        if other.owner_id == owner_id and other.provider_id != exclude_id and other.name == name:
            raise HTTPException(status_code=409, detail=f"已有同名 provider：{name}")


def _redact_response(result: dict[str, Any], provider: Provider) -> dict[str, Any]:
    """端点级纵深防御：探测结果回给前端前，再对可能带明文密钥的字符串字段脱敏一次
    （即便 probe 实现忘了脱敏，这里兜底；已脱敏的文本重复替换是幂等的）。
    """
    for field in ("error", "detail", "message"):
        value = result.get(field)
        if isinstance(value, str):
            result[field] = redact_secret(value, provider.api_key)
    return result


@router.get("/providers")
def list_providers(
    user: User = Depends(require_user), store: ProviderStore = Depends(get_provider_store)
) -> list[ProviderPublic]:
    return [ProviderPublic.from_provider(p) for p in visible_providers(store, user)]


@router.post("/providers", status_code=201)
def create_provider(
    body: ProviderInput,
    user: User = Depends(require_user),
    store: ProviderStore = Depends(get_provider_store),
) -> ProviderPublic:
    _check_name_unique(body.name, store, owner_id=user.user_id, exclude_id=None)
    _check_api_base(body.api_base)
    now = _now()
    provider = Provider(
        provider_id=f"p_{secrets.token_hex(4)}",
        name=body.name,
        kind=body.kind,
        api_base=body.api_base,
        api_key=body.api_key,
        default_model=body.default_model,
        created_at=now,
        updated_at=now,
        owner_id=user.user_id,
    )
    store.put(provider)
    return ProviderPublic.from_provider(provider)


@router.get("/providers/{provider_id}")
def get_provider(
    provider_id: str,
    user: User = Depends(require_user),
    store: ProviderStore = Depends(get_provider_store),
) -> ProviderPublic:
    return ProviderPublic.from_provider(_get_owned_provider(store, user, provider_id))


@router.put("/providers/{provider_id}")
def update_provider(
    provider_id: str,
    body: ProviderInput,
    user: User = Depends(require_user),
    store: ProviderStore = Depends(get_provider_store),
) -> ProviderPublic:
    """全量替换语义：`api_key` 省略=保留原密钥、`""`=清除；`api_base` 省略则按 kind 重置为默认值
    （不像 api_key 那样"保留原值"——PUT 对其余字段一律整体覆盖）。
    """
    existing = _get_owned_provider(store, user, provider_id)
    _check_api_base(body.api_base)
    _check_name_unique(
        body.name, store, owner_id=existing.owner_id or user.user_id, exclude_id=provider_id
    )
    # api_key 省略（未出现在请求体里）= 保留原密钥；显式传 "" = 清除
    api_key = existing.api_key if "api_key" not in body.model_fields_set else (body.api_key or None)
    provider = existing.model_copy(
        update={
            "name": body.name,
            "kind": body.kind,
            "api_base": body.api_base,
            "api_key": api_key,
            "default_model": body.default_model,
            "updated_at": _now(),
        }
    )
    store.put(provider)
    return ProviderPublic.from_provider(provider)


@router.delete("/providers/{provider_id}", status_code=204, response_class=Response)
def delete_provider(
    provider_id: str,
    user: User = Depends(require_user),
    store: ProviderStore = Depends(get_provider_store),
    lib: AgentLibraryStore = Depends(get_agent_library),
) -> Response:
    _get_owned_provider(store, user, provider_id)
    # issue #120：只给计数——admin 删被他人档案引用的 provider 时，文案不得列出他人档案名
    refs = sum(1 for s in lib.list() if s.profile.provider == provider_id)
    if refs:
        raise HTTPException(status_code=409, detail=f"仍被 {refs} 个 Agent 引用，请先解除引用")
    store.delete(provider_id)
    return Response(status_code=204)


@router.post("/providers/{provider_id}/test")
async def test_provider(
    provider_id: str,
    body: _TestRequest | None = None,
    user: User = Depends(require_user),
    store: ProviderStore = Depends(get_provider_store),
    probe: ProviderProbe = Depends(get_provider_probe),
) -> dict[str, Any]:
    provider = _get_owned_provider(store, user, provider_id)
    model = (body.model if body is not None else None) or provider.default_model
    if not model:
        raise HTTPException(status_code=400, detail="未指定 model 且该 provider 没有 default_model")
    return _redact_response(await probe.test(provider, model), provider)


@router.get("/providers/{provider_id}/models")
async def list_provider_models(
    provider_id: str,
    user: User = Depends(require_user),
    store: ProviderStore = Depends(get_provider_store),
    probe: ProviderProbe = Depends(get_provider_probe),
) -> dict[str, Any]:
    provider = _get_owned_provider(store, user, provider_id)
    return _redact_response(await probe.list_models(provider), provider)
