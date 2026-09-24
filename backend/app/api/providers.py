"""模型服务 Provider CRUD + test/models 端点（issue #26）。无鉴权：与建局一致，M3 单用户本地部署。

密钥语义：POST 直接落库；PUT 省略 api_key = 保留原密钥，传 "" = 清除；响应一律 ProviderPublic
（不含明文密钥）。DELETE 前扫 agent_library，档案仍引用则 409。
"""

from __future__ import annotations

import secrets
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from app.agent.provider import Provider, ProviderInput, ProviderPublic
from app.runtime.agent_library import AgentLibraryStore
from app.runtime.provider_probe import ProviderProbe
from app.runtime.provider_store import ProviderStore

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


def _check_name_unique(name: str, store: ProviderStore, *, exclude_id: str | None) -> None:
    for other in store.list():
        if other.provider_id != exclude_id and other.name == name:
            raise HTTPException(status_code=409, detail=f"已有同名 provider：{name}")


@router.get("/providers")
def list_providers(store: ProviderStore = Depends(get_provider_store)) -> list[ProviderPublic]:
    return [ProviderPublic.from_provider(p) for p in store.list()]


@router.post("/providers", status_code=201)
def create_provider(
    body: ProviderInput, store: ProviderStore = Depends(get_provider_store)
) -> ProviderPublic:
    _check_name_unique(body.name, store, exclude_id=None)
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
    )
    store.put(provider)
    return ProviderPublic.from_provider(provider)


@router.get("/providers/{provider_id}")
def get_provider(
    provider_id: str, store: ProviderStore = Depends(get_provider_store)
) -> ProviderPublic:
    provider = store.get(provider_id)
    if provider is None:
        raise HTTPException(status_code=404, detail=f"provider 不存在：{provider_id}")
    return ProviderPublic.from_provider(provider)


@router.put("/providers/{provider_id}")
def update_provider(
    provider_id: str,
    body: ProviderInput,
    store: ProviderStore = Depends(get_provider_store),
) -> ProviderPublic:
    """全量替换语义：`api_key` 省略=保留原密钥、`""`=清除；`api_base` 省略则按 kind 重置为默认值
    （不像 api_key 那样"保留原值"——PUT 对其余字段一律整体覆盖）。
    """
    existing = store.get(provider_id)
    if existing is None:
        raise HTTPException(status_code=404, detail=f"provider 不存在：{provider_id}")
    _check_name_unique(body.name, store, exclude_id=provider_id)
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
    store: ProviderStore = Depends(get_provider_store),
    lib: AgentLibraryStore = Depends(get_agent_library),
) -> Response:
    if store.get(provider_id) is None:
        raise HTTPException(status_code=404, detail=f"provider 不存在：{provider_id}")
    refs = [s.profile.name or s.agent_id for s in lib.list() if s.profile.provider == provider_id]
    if refs:
        raise HTTPException(
            status_code=409, detail=f"仍被 {len(refs)} 个 Agent 引用：{'、'.join(refs)}"
        )
    store.delete(provider_id)
    return Response(status_code=204)


@router.post("/providers/{provider_id}/test")
async def test_provider(
    provider_id: str,
    body: _TestRequest | None = None,
    store: ProviderStore = Depends(get_provider_store),
    probe: ProviderProbe = Depends(get_provider_probe),
) -> dict[str, Any]:
    provider = store.get(provider_id)
    if provider is None:
        raise HTTPException(status_code=404, detail=f"provider 不存在：{provider_id}")
    model = (body.model if body is not None else None) or provider.default_model
    if not model:
        raise HTTPException(status_code=400, detail="未指定 model 且该 provider 没有 default_model")
    return await probe.test(provider, model)


@router.get("/providers/{provider_id}/models")
async def list_provider_models(
    provider_id: str,
    store: ProviderStore = Depends(get_provider_store),
    probe: ProviderProbe = Depends(get_provider_probe),
) -> dict[str, Any]:
    provider = store.get(provider_id)
    if provider is None:
        raise HTTPException(status_code=404, detail=f"provider 不存在：{provider_id}")
    return await probe.list_models(provider)
