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
        thinking: bool = False,
    ) -> TModel: ...


def _pick_mode(model: str, thinking: bool = False) -> instructor.Mode:
    """选 instructor 解析模式。

    thinking=True：用 MD_JSON（软 JSON，容忍 ```json 围栏、不硬发 format=json）——
    推理模型开启思考时会把思考写进思考通道、把 JSON 裹在围栏里返回，硬发 format=json
    反而使 content 为空。thinking=False：支持函数调用 → TOOLS，否则 JSON（硬约束更稳）。
    """
    if thinking:
        return instructor.Mode.MD_JSON
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
        thinking: bool = False,
    ) -> TModel:
        client = self._client_for(_pick_mode(model, thinking))
        # Ollama 的 think 参数直接控制模型思考开关；对 ollama/* 显式传（含 False——
        # think=False 能修复推理模型在硬 JSON 下 content 为空的问题）。非 ollama 不传。
        extra: dict[str, Any] = {}
        if model.startswith("ollama/"):
            extra["think"] = thinking
        result = await client.chat.completions.create(
            model=model,
            response_model=response_model,
            max_retries=self._max_retries,
            temperature=temperature,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            **extra,
        )
        assert isinstance(result, response_model)  # instructor 已校验；为 mypy 窄化
        return result
