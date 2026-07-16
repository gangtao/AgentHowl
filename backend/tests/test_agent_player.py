"""AgentPlayerPort（issue #31 Task 6）：决策流、狼夜两段隔离、超时边际、模型路由。零网络。"""

import time

import pytest
from pydantic import BaseModel

from app.agent.agent_player import AgentConfig, AgentPlayerPort
from app.agent.decisions import (
    NightDecision,
    SpeechDecision,
    VoteDecision,
    WolfDeliberation,
)
from app.engine.actions import NightAction, NightActionType, Speak
from app.engine.config import RoleType, build_preset
from app.engine.observation import PlayerObservation
from tests.llm_helpers import ScriptedLLMClient

SECRET = "夜间私谋：今晚刀3号，明天悍跳"


def _obs(
    phase: str, *, seat: int = 0, role: RoleType = RoleType.WEREWOLF, **kw
) -> PlayerObservation:
    return PlayerObservation(
        game_id="g_a",
        state_version=kw.pop("state_version", 10),
        my_seat=seat,
        my_role=role,
        my_status="ALIVE",
        phase=phase,
        round=kw.pop("round", 1),
        seats=[{"seat": i, "alive": True, "is_sheriff": False} for i in range(9)],
        sheriff_seat=None,
        badge_flow_claims={},
        private=kw.pop("private", {"teammates": [4, 7]}),
        available_actions=[seat],
        **kw,
    )


def _port(
    script, *, agent_config: AgentConfig | None = None
) -> tuple[AgentPlayerPort, ScriptedLLMClient]:
    client = ScriptedLLMClient(script)
    port = AgentPlayerPort(
        seat=0,
        game_config=build_preset("std_9_kill_side"),
        agent_config=agent_config or AgentConfig(model="scripted"),
        client=client,
    )
    return port, client


async def test_speech_act_maps_to_speak() -> None:
    def script(rm: type[BaseModel], system: str, user: str) -> BaseModel:
        assert rm is SpeechDecision
        assert "0 号" in system or "0 号" in user or "0" in system  # 静态段含座位
        return SpeechDecision(reasoning="r", content="我是好人")

    port, client = _port(script)
    action = await port.act(_obs("DAY_SPEECH"), time.time() + 30)
    assert action == Speak(actor_seat=0, content="我是好人", claim_role=None, badge_flow=())
    assert len(client.calls) == 1


async def test_wolf_night_then_day_isolation() -> None:
    """核心隔离测试：狼夜私谋文本绝不出现在任何昼间 prompt 中；
    公私分离正向路径：第1夜私谋通过 night_private_context() 流入第2夜 prompt。"""

    wolf_call_count = 0  # 追踪狼夜调用序号

    def script(rm: type[BaseModel], system: str, user: str) -> BaseModel:
        nonlocal wolf_call_count
        if rm is WolfDeliberation:
            assert "队友" in user  # 狼夜 prompt 含私有段
            wolf_call_count += 1
            if wolf_call_count == 1:
                # 第1夜私谋：返回 SECRET
                return WolfDeliberation(analysis=SECRET, proposed_target=3)
            else:
                # 第2夜：私谋应该包含第1夜的 SECRET，在更深的推理中
                return WolfDeliberation(analysis="夜2分析：基于夜1谋定调整刀目", proposed_target=5)
        assert rm is VoteDecision or rm is SpeechDecision
        if rm is VoteDecision:
            return VoteDecision(reasoning="r", target_seat=3)
        return SpeechDecision(reasoning="r", content="昨晚平安夜")

    port, client = _port(script)
    # 第1轮：狼夜、昼间发言、投票
    kill = await port.act(_obs("NIGHT_WEREWOLF"), time.time() + 30)
    assert kill == NightAction(actor_seat=0, action_type=NightActionType.KILL, target_seat=3)
    assert SECRET in port.memory.night_private_context()

    await port.act(_obs("DAY_SPEECH", state_version=11), time.time() + 30)
    await port.act(_obs("VOTE", state_version=12), time.time() + 30)

    # 第2轮：再来一次狼夜，检验第1夜私谋是否流入第2夜 prompt
    kill2 = await port.act(_obs("NIGHT_WEREWOLF", round=2, state_version=20), time.time() + 30)
    assert kill2 == NightAction(actor_seat=0, action_type=NightActionType.KILL, target_seat=5)

    # 验证 1：私谋文本 SECRET 是狼夜那次调用的响应内容，只在响应返回后才被
    # note_night_private 写入 night_private 分区——它不可能出现在产生它自身的那次
    # 请求 prompt 里，更不用说后续昼间调用。因此正确隔离下，前三次调用
    # （第1狼夜、昼间、投票）的请求 prompt 里都不应见到 SECRET。
    early_calls = client.calls[:3]  # 第1狼夜、昼发言、投票
    for _model, system, user in early_calls:
        assert SECRET not in user and SECRET not in system

    # 验证 2：公私分离正向路径——第1夜私谋 SECRET 经由 memory.night_private_context()
    # 流入第2夜的 wolf_night_prompt（在"狼队私有"段）
    second_wolf_night_call = client.calls[-1]  # 最后一次调用是第2狼夜
    _, _, user_prompt = second_wolf_night_call
    assert SECRET in user_prompt, "第1夜私谋应流入第2夜 prompt"

    # 验证 3：昼间调用（发言、投票）永不见 SECRET（显式取第 2、3 次调用）
    day_calls = client.calls[1:3]
    assert len(day_calls) == 2
    for _model, system, user in day_calls:
        assert SECRET not in user and SECRET not in system


async def test_night_role_uses_night_model_speech_uses_speech_model() -> None:
    def script(rm: type[BaseModel], system: str, user: str) -> BaseModel:
        if rm is NightDecision:
            return NightDecision(reasoning="r", action_type=NightActionType.CHECK, target_seat=2)
        return SpeechDecision(reasoning="r", content="hi")

    cfg = AgentConfig(model="night-model", model_speech="speech-model")
    port, client = _port(script, agent_config=cfg)
    await port.act(_obs("NIGHT_SEER", role=RoleType.SEER, private={}), time.time() + 30)
    await port.act(
        _obs("DAY_SPEECH", role=RoleType.SEER, private={}, state_version=11), time.time() + 30
    )
    assert client.calls[0][0] == "night-model"
    assert client.calls[1][0] == "speech-model"


async def test_deadline_margin_raises_without_llm_call() -> None:
    def script(rm: type[BaseModel], system: str, user: str) -> BaseModel:
        raise AssertionError("不应发起 LLM 调用")

    port, client = _port(script)
    with pytest.raises(TimeoutError):
        await port.act(_obs("DAY_SPEECH"), time.time() + 1.0)  # 剩余 < margin 2s
    assert client.calls == []


async def test_llm_exception_propagates() -> None:
    def script(rm: type[BaseModel], system: str, user: str) -> BaseModel:
        raise RuntimeError("provider down")

    port, _ = _port(script)
    with pytest.raises(RuntimeError, match="provider down"):
        await port.act(_obs("DAY_SPEECH"), time.time() + 30)


async def test_lazy_reflection_runs_before_decision_when_time_allows() -> None:
    from app.agent.memory import ReflectionQA, ReflectionResult
    from app.engine.events import Event as Ev
    from app.engine.events import EventType, RoundStartedPayload, Visibility

    def script(rm: type[BaseModel], system: str, user: str) -> BaseModel:
        if rm is ReflectionResult:
            return ReflectionResult(summary="首轮总结", qa=[ReflectionQA(question="q", answer="a")])
        return SpeechDecision(reasoning="r", content="ok")

    port, client = _port(script)
    for rnd, seq in ((1, 1), (2, 2)):
        await port.on_events(
            [
                Ev(
                    seq=seq,
                    game_id="g_a",
                    ts=float(seq),
                    type=EventType.ROUND_STARTED,
                    actor_seat=None,
                    payload=RoundStartedPayload(round=rnd),
                    visibility=Visibility.PUBLIC,
                )
            ]
        )
    await port.act(_obs("DAY_SPEECH", round=2), time.time() + 60)
    assert len(client.calls) == 2  # 反思 + 决策
    assert "首轮总结" in client.calls[1][2]  # 反思摘要进了决策 prompt 的记忆段
