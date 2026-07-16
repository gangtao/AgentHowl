"""模型无关 LLM 客户端（issue #31，PRD §4.4.3）。

相对 PRD 签名去掉冗余 tools_schema 参数：结构化输出 schema 由 response_model
携带（instructor 负责校验与重试），工具语义在 prompts 指令段以文字呈现。
弱工具调用模型（如 Ollama）自动落 JSON mode。
"""

from __future__ import annotations

from typing import Any, Protocol, TypeVar

import instructor
import litellm
from pydantic import BaseModel

TModel = TypeVar("TModel", bound=BaseModel)

DEFAULT_MODEL = "ollama/llama3.1"


class LLMClient(Protocol):
    """结构化补全的唯一入口；实现必须无游戏状态（可跨座位复用）。"""

    async def complete_structured(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        response_model: type[TModel],
        model: str,
        temperature: float = 0.3,
    ) -> TModel: ...


def _pick_mode(model: str) -> instructor.Mode:
    """支持函数调用 → TOOLS；不支持或未知模型 → JSON（instructor 校验+重试兜底）。"""
    try:
        supported = bool(litellm.supports_function_calling(model))
    except Exception:
        supported = False
    return instructor.Mode.TOOLS if supported else instructor.Mode.JSON


class LiteLLMInstructorClient:
    def __init__(self, max_retries: int = 2) -> None:
        self._max_retries = max_retries
        self._clients: dict[instructor.Mode, Any] = {}  # instructor 异步客户端按 mode 缓存

    def _client_for(self, mode: instructor.Mode) -> Any:
        if mode not in self._clients:
            self._clients[mode] = instructor.from_litellm(litellm.acompletion, mode=mode)
        return self._clients[mode]

    async def complete_structured(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        response_model: type[TModel],
        model: str,
        temperature: float = 0.3,
    ) -> TModel:
        client = self._client_for(_pick_mode(model))
        result = await client.chat.completions.create(
            model=model,
            response_model=response_model,
            max_retries=self._max_retries,
            temperature=temperature,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        assert isinstance(result, response_model)  # instructor 已校验；为 mypy 窄化
        return result
