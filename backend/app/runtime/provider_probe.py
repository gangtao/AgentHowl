"""Provider 探测（issue #26）：测试连接与拉取模型列表。默认实现在函数内 import litellm / httpx。"""

from __future__ import annotations

import time
from typing import Any, Protocol

from app.agent.provider import Provider, resolve_model


class ProviderProbe(Protocol):
    async def test(self, provider: Provider, model: str | None) -> dict[str, Any]: ...
    async def list_models(self, provider: Provider) -> dict[str, Any]: ...


_STATIC_MODELS: dict[str, list[str]] = {
    "anthropic": ["claude-3-5-haiku-latest", "claude-3-5-sonnet-latest"],
    "gemini": ["gemini-1.5-flash", "gemini-1.5-pro"],
}


class LiteLLMProbe:
    async def test(self, provider: Provider, model: str | None) -> dict[str, Any]:
        import litellm  # 惰性

        name = model or provider.default_model
        assert name is not None  # 端点已校验
        extra: dict[str, Any] = {}
        if provider.api_base:
            extra["api_base"] = provider.api_base
        if provider.api_key:
            extra["api_key"] = provider.api_key
        t0 = time.monotonic()
        try:
            await litellm.acompletion(
                model=resolve_model(name, provider),
                messages=[{"role": "user", "content": "ping"}],
                max_tokens=8,
                timeout=5,
                **extra,
            )
        except Exception as exc:  # 错误原文回给 UI
            return {
                "ok": False,
                "latency_ms": int((time.monotonic() - t0) * 1000),
                "error": f"{type(exc).__name__}: {exc}",
            }
        return {"ok": True, "latency_ms": int((time.monotonic() - t0) * 1000), "error": None}

    async def list_models(self, provider: Provider) -> dict[str, Any]:
        if provider.kind in _STATIC_MODELS:
            return {"models": _STATIC_MODELS[provider.kind], "error": None}
        import httpx  # 惰性

        base = (provider.api_base or "").rstrip("/")
        try:
            async with httpx.AsyncClient(timeout=5) as http:
                if provider.kind == "ollama":
                    r = await http.get(f"{base}/api/tags")
                    r.raise_for_status()
                    names = [m["name"] for m in r.json().get("models", [])]
                    return {"models": names, "error": None}
                headers = (
                    {"Authorization": f"Bearer {provider.api_key}"} if provider.api_key else {}
                )
                url = f"{base}/v1/models" if not base.endswith("/v1") else f"{base}/models"
                if provider.kind == "openai" and not base:
                    url = "https://api.openai.com/v1/models"
                r = await http.get(url, headers=headers)
                r.raise_for_status()
                return {"models": sorted(m["id"] for m in r.json().get("data", [])), "error": None}
        except Exception as exc:
            return {"models": [], "error": f"{type(exc).__name__}: {exc}"}
