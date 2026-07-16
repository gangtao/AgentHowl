"""LLM 客户端（issue #31 Task 3）：mode 选择与脚本客户端契约。零网络。"""

import pytest
from pydantic import BaseModel

from app.agent.llm_client import LiteLLMInstructorClient, LLMClient, _pick_mode
from tests.llm_helpers import ScriptedLLMClient


class _Echo(BaseModel):
    text: str


def test_pick_mode_tools_when_supported(monkeypatch: pytest.MonkeyPatch) -> None:
    import instructor
    import litellm

    monkeypatch.setattr(litellm, "supports_function_calling", lambda model: True)
    assert _pick_mode("gpt-x") is instructor.Mode.TOOLS


def test_pick_mode_json_when_unsupported_or_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    import instructor
    import litellm

    monkeypatch.setattr(litellm, "supports_function_calling", lambda model: False)
    assert _pick_mode("ollama/llama3.1") is instructor.Mode.JSON

    def _boom(model: str) -> bool:
        raise ValueError("unknown model")

    monkeypatch.setattr(litellm, "supports_function_calling", _boom)
    assert _pick_mode("ollama/whatever") is instructor.Mode.JSON  # 查询异常按不支持处理


def test_client_constructs_without_network() -> None:
    client = LiteLLMInstructorClient()
    assert client is not None


async def test_scripted_client_satisfies_protocol_and_records() -> None:
    def script(rm: type[BaseModel], system: str, user: str) -> BaseModel:
        assert rm is _Echo
        return _Echo(text="hi")

    scripted: LLMClient = ScriptedLLMClient(script)
    out = await scripted.complete_structured(
        system_prompt="sys", user_prompt="usr", response_model=_Echo, model="scripted"
    )
    assert out == _Echo(text="hi")
    assert scripted.calls == [("scripted", "sys", "usr")]  # type: ignore[attr-defined]
