"""档案指纹与摘要（issue #60）。"""

from app.agent.personality import PersonalityPreset, PersonalitySpec
from app.agent.profile import AgentProfile
from app.eval.fingerprint import profile_fingerprint, profile_summary


def test_fingerprint_ignores_name_and_memory_id_but_not_content() -> None:
    base = AgentProfile(model="ollama/a", skills=("logic-chain", "side-taking"))
    same = AgentProfile(
        model="ollama/a", skills=("logic-chain", "side-taking"), name="老张", memory_id="x"
    )
    assert profile_fingerprint(base) == profile_fingerprint(same)
    assert len(profile_fingerprint(base)) == 10
    changed = base.model_copy(update={"temperature": 0.7})
    assert profile_fingerprint(base) != profile_fingerprint(changed)
    assert profile_fingerprint(base) != profile_fingerprint(
        AgentProfile(model="ollama/a", skills=("side-taking", "logic-chain"))
    )
    with_p = base.model_copy(update={"personality": PersonalitySpec(traits={"多疑": 0.9})})
    assert profile_fingerprint(base) != profile_fingerprint(with_p)


def test_profile_summary_format() -> None:
    assert profile_summary(AgentProfile(model="ollama/a")) == "ollama/a"
    rich = AgentProfile(
        model="ollama/b",
        skills=("logic-chain",),
        personality=PersonalitySpec(preset=PersonalityPreset(system="MBTI", value="enfp")),
        temperature=0.7,
        thinking=True,
    )
    assert profile_summary(rich) == "ollama/b · 技能 logic-chain · 性格 ENFP · T=0.7 · thinking"
