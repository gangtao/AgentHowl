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


async def test_instructor_retries_on_invalid_then_valid(monkeypatch) -> None:
    """判据 5：底层模型首次返回不合 schema 的 JSON，instructor 校验失败后重试至合法。"""
    import litellm

    from app.agent.decisions import SpeechDecision

    calls = {"n": 0}

    def _resp(content: str):
        # 构造 litellm ModelResponse（OpenAI 形状）；instructor JSON mode 从 message.content 解析
        return litellm.ModelResponse(
            choices=[
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": content},
                    "finish_reason": "stop",
                }
            ],
            model="scripted",
            usage={"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        )

    async def fake_acompletion(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            # 缺必填字段 content → SpeechDecision 校验失败，触发 instructor 重试
            return _resp('{"reasoning": "先胡说"}')
        return _resp('{"reasoning": "ok", "content": "大家好"}')

    monkeypatch.setattr(litellm, "acompletion", fake_acompletion)

    client = LiteLLMInstructorClient(max_retries=2)
    result = await client.complete_structured(
        system_prompt="s",
        user_prompt="u",
        response_model=SpeechDecision,
        model="scripted",
    )
    assert isinstance(result, SpeechDecision) and result.content == "大家好"
    assert calls["n"] >= 2  # 首次校验失败确实触发了重试
