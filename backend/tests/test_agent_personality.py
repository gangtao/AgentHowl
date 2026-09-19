"""Agent 人格（issue #57）：schema 校验、三层输入翻译、隐式写法、摘要。"""

import pytest
from pydantic import ValidationError

from app.agent.personality import (
    FORBIDDEN_PHRASES,
    TRAIT_LEXICON,
    PersonalityPreset,
    PersonalitySpec,
    personality_summary,
    render_personality,
)


def test_spec_rejects_empty_and_unknown_keys() -> None:
    with pytest.raises(ValidationError, match="至少"):
        PersonalitySpec()
    with pytest.raises(ValidationError):
        PersonalitySpec(description="x", mood="y")  # type: ignore[call-arg]


def test_spec_normalizes_and_bounds() -> None:
    s = PersonalitySpec(description="  多疑的老玩家  ", traits={" 多疑 ": 0.9})
    assert s.description == "多疑的老玩家" and s.traits == {"多疑": 0.9}
    assert PersonalitySpec(description="   ", traits={"冲动": 0.5}).description is None
    with pytest.raises(ValidationError, match="300"):
        PersonalitySpec(description="字" * 301)
    with pytest.raises(ValidationError, match="100"):
        PersonalitySpec(style_notes="字" * 101)
    for bad in (-0.1, 1.1):
        with pytest.raises(ValidationError):
            PersonalitySpec(traits={"多疑": bad})
    with pytest.raises(ValidationError, match="特质"):
        PersonalitySpec(traits={"": 0.5})
    with pytest.raises(ValidationError, match="特质"):
        PersonalitySpec(traits={"特" * 13: 0.5})


@pytest.mark.parametrize("phrase", FORBIDDEN_PHRASES)
def test_spec_guardrails(phrase: str) -> None:
    with pytest.raises(ValidationError, match="越权"):
        PersonalitySpec(description=f"我{phrase}啦")
    with pytest.raises(ValidationError, match="越权"):
        PersonalitySpec(style_notes=f"口头禅：{phrase}")


def test_preset_validation() -> None:
    p = PersonalityPreset(system="MBTI", value="intj")
    assert p.value == "INTJ"
    for bad in ("INT", "INTX", "IITJ", "ABCD"):
        with pytest.raises(ValidationError):
            PersonalityPreset(system="MBTI", value=bad)
    PersonalityPreset(system="MBTI", value={"E": 0.8, "N": 0.3})
    with pytest.raises(ValidationError):
        PersonalityPreset(system="MBTI", value={"X": 0.5})
    with pytest.raises(ValidationError):
        PersonalityPreset(system="MBTI", value={"E": 0.5, "I": 0.5})  # 同轴两字母
    PersonalityPreset(system="BIG_FIVE", value={"O": 0.7, "N": 0.2})
    with pytest.raises(ValidationError):
        PersonalityPreset(system="BIG_FIVE", value="OCEAN")
    with pytest.raises(ValidationError):
        PersonalityPreset(system="BIG_FIVE", value={"Z": 0.5})


def test_render_order_and_bands() -> None:
    spec = PersonalitySpec(
        description="老油条，话不多但每句都带钩子",
        traits={"多疑": 0.9, "从众": 0.2, "冲动": 0.5, "爱唱歌": 0.8},
        preset=PersonalityPreset(system="MBTI", value="ENFP"),
        style_notes="爱用感叹号",
    )
    text = render_personality(spec)
    lines = text.splitlines()
    assert lines[0] == "你的性格：老油条，话不多但每句都带钩子"
    i_desc = 0
    i_susp = next(i for i, ln in enumerate(lines) if "多疑" in ln)
    i_imp = next(i for i, ln in enumerate(lines) if "冲动" in ln)
    i_conf = next(i for i, ln in enumerate(lines) if "从众" in ln)
    i_sing = next(i for i, ln in enumerate(lines) if "爱唱歌" in ln)
    i_style = next(i for i, ln in enumerate(lines) if ln.startswith("说话风格："))
    assert i_desc < i_susp < i_imp < i_conf  # traits 按强度降序
    assert lines[i_susp].startswith("你非常多疑") and lines[i_imp].startswith("你比较冲动")
    assert lines[i_conf].startswith("你略微从众")
    assert lines[i_sing] == "你非常爱唱歌。"  # 词表外：原样形容词
    assert TRAIT_LEXICON["多疑"] in lines[i_susp]  # 词表内：带行为句
    assert i_sing < i_style and lines[i_style] == "说话风格：爱用感叹号"
    assert lines[-1].startswith("以上倾向只影响你的风格与判断偏好")
    # 预设展开在 traits 之后、style 之前，且隐式写法
    i_preset = next(i for i, ln in enumerate(lines) if "主动发言" in ln)
    assert i_sing < i_preset < i_style
    for banned in ("MBTI", "ENFP", "Big Five", "BIG_FIVE"):
        assert banned not in text


def test_render_mbti_defaults_and_dict() -> None:
    text = render_personality(
        PersonalitySpec(preset=PersonalityPreset(system="MBTI", value="ISTJ"))
    )
    assert "你比较" in text and "少说多听" in text  # I 轴 0.7 → 比较
    assert "略微" in text and "只认已发生" in text  # S 轴 0.6 → 略微（信号弱）
    assert "用逻辑找狼" in text and "早定论" in text
    d = render_personality(
        PersonalitySpec(preset=PersonalityPreset(system="MBTI", value={"E": 0.9, "P": 0.2}))
    )
    assert "你非常" in d and "主动发言" in d and "略微" in d and "随新信息灵活改口" in d
    assert "只认已发生" not in d and "推测身份链" not in d  # 缺省轴不出句


def test_render_big_five_midrange_silent() -> None:
    text = render_personality(
        PersonalitySpec(
            preset=PersonalityPreset(
                system="BIG_FIVE", value={"O": 0.9, "C": 0.5, "E": 0.1, "A": 0.2, "N": 0.55}
            )
        )
    )
    assert "非常规打法" in text and "少说多听" in text and "多疑、爱唱反调" in text
    assert "记录票型" not in text and "凭感觉" not in text  # C=0.5 不出句
    assert "情绪化辩解" not in text and "情绪稳定" not in text  # N=0.55 不出句


def test_summary() -> None:
    assert (
        personality_summary(PersonalitySpec(preset=PersonalityPreset(system="MBTI", value="enfp")))
        == "ENFP"
    )
    assert (
        personality_summary(
            PersonalitySpec(preset=PersonalityPreset(system="BIG_FIVE", value={"O": 0.9, "A": 0.2}))
        )
        == "O0.9 A0.2"
    )
    assert (
        personality_summary(PersonalitySpec(description="老油条，话不多但每句都带钩子啊"))
        == "老油条，话不多但每句都带…"
    )
    assert personality_summary(PersonalitySpec(traits={"多疑": 0.9, "冲动": 0.3})) == "多疑"
    assert personality_summary(PersonalitySpec(style_notes="爱用感叹号")) == "爱用感叹号"
