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


class _FakeCompletions:
    """捕获 instructor create(**kwargs)，返回固定合法决策。"""

    def __init__(self) -> None:
        self.kwargs: dict[str, object] = {}

    async def create(self, **kwargs: object) -> object:
        from app.agent.decisions import SpeechDecision

        self.kwargs = kwargs
        return SpeechDecision(reasoning="r", content="hi")


class _FakeInstructor:
    def __init__(self) -> None:
        self.chat = type("C", (), {"completions": _FakeCompletions()})()


async def _run(model: str, thinking: bool, monkeypatch) -> tuple[object, dict[str, object]]:
    from app.agent.decisions import SpeechDecision
    from app.agent.llm_client import LiteLLMInstructorClient

    client = LiteLLMInstructorClient()
    fake = _FakeInstructor()
    seen: dict[str, object] = {}

    def fake_client_for(mode: object) -> object:
        seen["mode"] = mode
        return fake

    monkeypatch.setattr(client, "_client_for", fake_client_for)
    await client.complete_structured(
        system_prompt="s",
        user_prompt="u",
        response_model=SpeechDecision,
        model=model,
        thinking=thinking,
    )
    return seen["mode"], fake.chat.completions.kwargs  # type: ignore[attr-defined]


async def test_thinking_on_uses_md_json_and_passes_think_true(monkeypatch) -> None:
    import instructor

    mode, kwargs = await _run("ollama/qwen3:8b", thinking=True, monkeypatch=monkeypatch)
    assert mode is instructor.Mode.MD_JSON
    assert kwargs.get("think") is True


async def test_thinking_off_ollama_passes_think_false_and_not_md_json(monkeypatch) -> None:
    import instructor

    mode, kwargs = await _run("ollama/qwen2.5-coder:7b", thinking=False, monkeypatch=monkeypatch)
    assert mode is not instructor.Mode.MD_JSON  # 关闭思考不用软 JSON（TOOLS/JSON 按模型能力）
    assert kwargs.get("think") is False  # think=False 修复推理模型空 content


async def test_non_ollama_never_passes_think(monkeypatch) -> None:
    _mode, kwargs = await _run("gpt-4o-mini", thinking=True, monkeypatch=monkeypatch)
    assert "think" not in kwargs  # 非 ollama 不传 think（否则 provider 报错）
