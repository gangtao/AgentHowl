# Agent 人格 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 每个 Agent 可配置任意性格特点（自由描述 / 自定义特质 / MBTI、Big Five 预设，任意组合），翻译成狼人杀语境行为倾向注入系统 prompt 静态段（issue #57）。

**Architecture:** 新模块 `app/agent/personality.py`（schema + 校验 + 纯函数翻译）；`static_system_prompt` 加 `personality_text=""`；`AgentPlayerPort` 缓存生成一次；`AgentProfile.personality`；档案表摘要。任务顺序：模块 → prompt/端口/档案接入 → CLI 渲染/文档/bench。

**Tech Stack:** Python 3.11、Pydantic v2、pytest；`uv`。Python 命令在 `backend/` 下执行。

**Spec:** `docs/superpowers/specs/2026-09-19-agent-personality-design.md`（执行者须同时阅读）

## Global Constraints

- 引擎不改。`personality.py` 只依赖 pydantic（不 import engine 以外的任何 app 模块；不 import agent_player）。
- `personality_text=""` 时 `static_system_prompt` 输出逐字不变；无人格档案零变化。
- 人设段只进系统 prompt 静态段；不进 `build_prompt` / `build_wolf_night_prompt` 的 user prompt；不进反思。
- 预设展开不含体系名（`MBTI`、`Big Five`、四字母代码）。
- 护栏短语（`你知道`、`上帝视角`、`无视规则`、`绕过`、`作弊`、`真实身份是`、`其实是狼`）出现在 `description` / `style_notes` 即校验失败。
- 文档与代码注释用中文；标识符用英文；ruff 行宽 100 且中文按宽 2 计。
- 测试零 IO 零 mock。
- 每任务结束：`uv run pytest -q -x --ignore=tests/test_api_e2e.py` 全绿、`uv run ruff check .`（All checks passed!）、`uv run ruff format --check .`、`uv run mypy app` 全过；最后任务跑 `uv run pytest -q`。
- commit 风格 `feat(agent): … (issue #57)`，结尾附 `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`。

## File Structure

| 文件 | 职责 | 任务 |
|---|---|---|
| `backend/app/agent/personality.py`（新） | `PersonalityPreset`、`PersonalitySpec`、`render_personality`、`personality_summary`、词表 | 1 |
| `backend/tests/test_agent_personality.py`（新） | 模块测试 | 1 |
| `backend/app/agent/prompts.py`、`agent_player.py`、`profile.py` | `personality_text`、端口缓存、`AgentProfile.personality` | 2 |
| `backend/app/cli/render.py`、`README.md`、`docs/specs/requirements.md`、`tests/test_agent_bench.py` | 档案表摘要、文档、bench | 3 |

---

### Task 1: `app/agent/personality.py`——schema、校验、翻译

**Files:**
- Create: `backend/app/agent/personality.py`
- Create: `backend/tests/test_agent_personality.py`

**Interfaces:**
- Produces：`PersonalityPreset(system, value)`、`PersonalitySpec(description, traits, preset, style_notes)`、`render_personality(spec) -> str`、`personality_summary(spec) -> str`、`FORBIDDEN_PHRASES`、`MBTI_AXES`、`BIG_FIVE_KEYS`、`TRAIT_LEXICON`。

- [ ] **Step 1: 写失败测试**

新建 `backend/tests/test_agent_personality.py`：

```python
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
    text = render_personality(PersonalitySpec(preset=PersonalityPreset(system="MBTI", value="ISTJ")))
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
    assert personality_summary(PersonalitySpec(preset=PersonalityPreset(system="MBTI", value="enfp"))) == "ENFP"
    assert (
        personality_summary(
            PersonalitySpec(preset=PersonalityPreset(system="BIG_FIVE", value={"O": 0.9, "A": 0.2}))
        )
        == "O0.9 A0.2"
    )
    assert personality_summary(PersonalitySpec(description="老油条，话不多但每句都带钩子啊")) == "老油条，话不多但每句都带钩…"
    assert personality_summary(PersonalitySpec(traits={"多疑": 0.9, "冲动": 0.3})) == "多疑"
    assert personality_summary(PersonalitySpec(style_notes="爱用感叹号")) == "爱用感叹号"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_agent_personality.py -q`
Expected: 收集期 `ModuleNotFoundError: No module named 'app.agent.personality'`

- [ ] **Step 3: 实现**

新建 `backend/app/agent/personality.py`：

```python
"""Agent 人格（issue #57）：任意性格特点 → 狼人杀语境行为倾向文本。

三层输入任意组合：自由描述（description）、自定义特质词表（traits）、现成体系预设（MBTI /
Big Five）。翻译为系统 prompt 静态段的一段文本，顺序即优先级（用户显式描述优先于预设）；
预设展开用隐式写法（不出现体系名）。护栏：越权/改规则短语在 schema 层拒绝。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

MBTI_AXES: tuple[str, ...] = ("EI", "SN", "TF", "JP")
BIG_FIVE_KEYS: tuple[str, ...] = ("O", "C", "E", "A", "N")
FORBIDDEN_PHRASES: tuple[str, ...] = (
    "你知道",
    "上帝视角",
    "无视规则",
    "绕过",
    "作弊",
    "真实身份是",
    "其实是狼",
)
_MBTI_DEFAULT_STRENGTH = {"EI": 0.7, "SN": 0.6, "TF": 0.7, "JP": 0.7}  # S/N 信号弱，默认略低
_MAX_DESC = 300
_MAX_STYLE = 100
_MAX_TRAIT_LEN = 12

# 特质词 → 狼人杀语境行为句（词表外的词按形容词原样纳入）
TRAIT_LEXICON: dict[str, str] = {
    "多疑": "倾向质疑金水与示好，不轻信任何人",
    "冲动": "早表态、易改票、先说后想",
    "谨慎": "后置位再表态，少声称身份",
    "从众": "倾向跟大票、不当出头鸟",
    "好胜": "敢于争警长、敢于悍跳或对跳",
    "冷静": "情绪稳定，被怀疑时不过度辩解",
    "健谈": "发言长、主动带节奏",
    "沉默": "发言简短、只说关键信息",
    "固执": "一旦定论很少改票",
    "圆滑": "不轻易得罪人、措辞留余地",
    "直率": "有怀疑直接点名",
    "乐观": "倾向相信局势可控、少做最坏打算",
    "悲观": "倾向假设最坏情况、对示好保持警惕",
    "逻辑": "以票型与发言矛盾为主要依据",
    "感性": "以信任感与直觉为主要依据",
}

# MBTI 四轴：字母 → 行为句
_MBTI_TEXT: dict[str, str] = {
    "E": "主动发言、愿意上警争节奏",
    "I": "少说多听、后置位表态",
    "S": "只认已发生的票型与事实",
    "N": "敢于推测身份链、提前站边",
    "T": "用逻辑找狼、查杀直接归票、不怕得罪人",
    "F": "看重信任与关系、倾向相信示好者",
    "J": "早定论、坚持判断、不轻易改票",
    "P": "保留判断、随新信息灵活改口",
}
# Big Five 五维：(高分句, 低分句)
_BIG_FIVE_TEXT: dict[str, tuple[str, str]] = {
    "O": ("乐于尝试非常规打法", "按常规套路走"),
    "C": ("记录票型、逻辑严谨", "凭感觉判断"),
    "E": ("主动发言、愿意上警争节奏", "少说多听、后置位表态"),
    "A": ("随和、容易被说服", "多疑、爱唱反调"),
    "N": ("被怀疑时容易情绪化辩解", "情绪稳定、被怀疑时不慌"),
}
_CLOSING = (
    "以上倾向只影响你的风格与判断偏好；若相互冲突，以先出现的描述为准；"
    "不得因此违反游戏规则或泄露私有信息。"
)


def _band(strength: float) -> str:
    if strength < 0.34:
        return "略微"
    if strength < 0.67:
        return "比较"
    return "非常"


def _check_guardrail(text: str, field: str) -> str:
    hit = [p for p in FORBIDDEN_PHRASES if p in text]
    if hit:
        raise ValueError(f"{field} 含越权或改规则短语：{hit}")
    return text


class PersonalityPreset(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    system: Literal["MBTI", "BIG_FIVE"]
    value: str | dict[str, float]

    @model_validator(mode="after")
    def _validate_value(self) -> PersonalityPreset:
        if self.system == "MBTI":
            if isinstance(self.value, str):
                code = self.value.strip().upper()
                if len(code) != 4 or any(code[i] not in MBTI_AXES[i] for i in range(4)):
                    raise ValueError(f"MBTI 代码非法：{self.value!r}（须如 INTJ，每轴取一字母）")
                object.__setattr__(self, "value", code)
            else:
                seen_axes: set[str] = set()
                for k, v in self.value.items():
                    axis = next((a for a in MBTI_AXES if k in a), None)
                    if axis is None or len(k) != 1:
                        raise ValueError(f"MBTI 字母非法：{k!r}")
                    if axis in seen_axes:
                        raise ValueError(f"MBTI 同一轴出现两次：{axis}")
                    seen_axes.add(axis)
                    if not 0.0 <= v <= 1.0:
                        raise ValueError(f"MBTI 强度须在 0–1：{k}={v}")
        else:
            if not isinstance(self.value, dict):
                raise ValueError("BIG_FIVE 的 value 须为 {O/C/E/A/N: 0–1} 映射")
            for k, v in self.value.items():
                if k not in BIG_FIVE_KEYS:
                    raise ValueError(f"Big Five 键非法：{k!r}（可用 O/C/E/A/N）")
                if not 0.0 <= v <= 1.0:
                    raise ValueError(f"Big Five 强度须在 0–1：{k}={v}")
        return self


class PersonalitySpec(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    description: str | None = None  # 自由文本，≤ 300 字
    traits: dict[str, float] = Field(default_factory=dict)  # 特质词 → 强度 0–1
    preset: PersonalityPreset | None = None
    style_notes: str | None = None  # 口头禅/语气，≤ 100 字

    @field_validator("description", "style_notes", mode="before")
    @classmethod
    def _strip_text(cls, v: object) -> object:
        if isinstance(v, str):
            v = v.strip()
            return v or None
        return v

    @field_validator("description")
    @classmethod
    def _check_description(cls, v: str | None) -> str | None:
        if v is not None:
            if len(v) > _MAX_DESC:
                raise ValueError(f"description 超过 {_MAX_DESC} 字（{len(v)}）")
            _check_guardrail(v, "description")
        return v

    @field_validator("style_notes")
    @classmethod
    def _check_style(cls, v: str | None) -> str | None:
        if v is not None:
            if len(v) > _MAX_STYLE:
                raise ValueError(f"style_notes 超过 {_MAX_STYLE} 字（{len(v)}）")
            _check_guardrail(v, "style_notes")
        return v

    @field_validator("traits")
    @classmethod
    def _check_traits(cls, v: dict[str, float]) -> dict[str, float]:
        out: dict[str, float] = {}
        for k, s in v.items():
            key = k.strip()
            if not key or len(key) > _MAX_TRAIT_LEN:
                raise ValueError(f"特质词非法：{k!r}（须非空且 ≤ {_MAX_TRAIT_LEN} 字）")
            if not 0.0 <= s <= 1.0:
                raise ValueError(f"特质强度须在 0–1：{key}={s}")
            out[key] = s
        return out

    @model_validator(mode="after")
    def _not_empty(self) -> PersonalitySpec:
        if not (self.description or self.traits or self.preset or self.style_notes):
            raise ValueError("personality 至少要给 description / traits / preset / style_notes 之一")
        return self


def _trait_lines(traits: dict[str, float]) -> list[str]:
    lines: list[str] = []
    for word, strength in sorted(traits.items(), key=lambda kv: (-kv[1], kv[0])):
        prefix = f"你{_band(strength)}{word}"
        behavior = TRAIT_LEXICON.get(word)
        lines.append(f"{prefix}：{behavior}。" if behavior else f"{prefix}。")
    return lines


def _preset_lines(preset: PersonalityPreset) -> list[str]:
    lines: list[str] = []
    if preset.system == "MBTI":
        if isinstance(preset.value, str):
            for i, letter in enumerate(preset.value):
                lines.append(f"你{_band(_MBTI_DEFAULT_STRENGTH[MBTI_AXES[i]])}倾向于{_MBTI_TEXT[letter]}。")
        else:
            for letter, strength in preset.value.items():
                lines.append(f"你{_band(strength)}倾向于{_MBTI_TEXT[letter]}。")
    else:
        assert isinstance(preset.value, dict)
        for key, strength in preset.value.items():
            high, low = _BIG_FIVE_TEXT[key]
            if strength > 0.6:
                lines.append(f"你{_band(strength)}倾向于{high}。")
            elif strength < 0.4:
                lines.append(f"你{_band(1.0 - strength)}倾向于{low}。")
            # 0.4–0.6：中性，不出句
    return lines


def render_personality(spec: PersonalitySpec) -> str:
    """三层输入 → 人设文本；顺序即优先级；末句固定说明边界。"""
    lines: list[str] = []
    if spec.description:
        lines.append(f"你的性格：{spec.description}")
    lines.extend(_trait_lines(spec.traits))
    if spec.preset is not None:
        lines.extend(_preset_lines(spec.preset))
    if spec.style_notes:
        lines.append(f"说话风格：{spec.style_notes}")
    lines.append(_CLOSING)
    return "\n".join(lines)


def personality_summary(spec: PersonalitySpec) -> str:
    """档案表用的一眼摘要：预设代码 > 描述前 12 字 > 首个特质词 > 风格备注。"""
    if spec.preset is not None:
        if isinstance(spec.preset.value, str):
            return spec.preset.value
        return " ".join(f"{k}{v:g}" for k, v in spec.preset.value.items())
    if spec.description:
        return spec.description if len(spec.description) <= 12 else spec.description[:12] + "…"
    if spec.traits:
        return max(spec.traits.items(), key=lambda kv: (kv[1], kv[0]))[0]
    return spec.style_notes or ""
```

- [ ] **Step 4: 跑测试确认通过 + 无回归**

Run: `uv run pytest tests/test_agent_personality.py -q`
Expected: 全部 PASS（`test_summary` 里 BIG_FIVE 摘要 `O0.9 A0.2` 依赖 `{:g}` 格式）

Run: `uv run pytest -q -x --ignore=tests/test_api_e2e.py && uv run ruff check . && uv run ruff format --check . && uv run mypy app`
Expected: 全绿（`object.__setattr__` 在 frozen 模型的 validator 里改规范化值是 pydantic v2 的既定写法；若 mypy 报 `_validate_value` 返回类型，用 `-> "PersonalityPreset"` 或 `Self`）

- [ ] **Step 5: Commit**

```bash
git add backend/app/agent/personality.py backend/tests/test_agent_personality.py
git commit -m "feat(agent): 人格 schema 与翻译——描述/特质词表/MBTI、Big Five 预设 → 狼人杀语境行为倾向 (issue #57)"
```

---

### Task 2: 接入——`static_system_prompt`、端口缓存、`AgentProfile.personality`

**Files:**
- Modify: `backend/app/agent/prompts.py`（`static_system_prompt` 约 line 61-70）
- Modify: `backend/app/agent/agent_player.py`（`__init__`、`_system_for`、`build_agent_port`）
- Modify: `backend/app/agent/profile.py`（`AgentProfile.personality`、模块 docstring）
- Test: `backend/tests/test_agent_prompts.py`、`test_agent_player.py`、`test_agent_profile.py`、`test_api_lobby.py`

**Interfaces:**
- Consumes: Task 1 `PersonalitySpec`、`render_personality`。
- Produces：`static_system_prompt(config, seat, role, personality_text: str = "")`；`AgentPlayerPort(..., personality: PersonalitySpec | None = None)`；`AgentProfile.personality: PersonalitySpec | None = None`。

- [ ] **Step 1: 写失败测试**

追加到 `backend/tests/test_agent_prompts.py` 末尾：

```python
def test_static_prompt_personality_block_position_and_identity_when_empty() -> None:
    config = build_preset("std_9_kill_side")
    base = static_system_prompt(config, seat=2, role=RoleType.SEER)
    assert base == static_system_prompt(config, seat=2, role=RoleType.SEER, personality_text="")
    assert "== 你的性格 ==" not in base
    sp = static_system_prompt(config, seat=2, role=RoleType.SEER, personality_text="你非常多疑：不轻信任何人。")
    assert "== 你的性格 ==\n你非常多疑：不轻信任何人。" in sp
    assert sp.index("角色：SEER") < sp.index("== 你的性格 ==") < sp.index("发言用中文")
```

追加到 `backend/tests/test_agent_player.py` 末尾：

```python
async def test_personality_in_system_prompt_only() -> None:
    from app.agent.personality import PersonalitySpec

    def script(rm: type[BaseModel], system: str, user: str) -> BaseModel:
        if rm is WolfDeliberation:
            return WolfDeliberation(analysis="a", proposed_target=3)
        return SpeechDecision(reasoning="r", content="c")

    client = ScriptedLLMClient(script)
    port = AgentPlayerPort(
        seat=0,
        game_config=build_preset("std_9_kill_side"),
        agent_config=AgentConfig(model="scripted"),
        client=client,
        personality=PersonalitySpec(traits={"多疑": 0.9}),
    )
    await port.act(_obs("NIGHT_WEREWOLF"), time.time() + 60)
    _m, system, user = client.calls[-1]
    assert "== 你的性格 ==" in system and "你非常多疑" in system
    assert "你的性格" not in user and "多疑" not in user  # 只在系统静态段
    await port.act(_obs("DAY_SPEECH"), time.time() + 60)
    assert client.calls[-1][1] == system  # 缓存：同一系统 prompt


async def test_no_personality_means_no_block() -> None:
    def script(rm: type[BaseModel], system: str, user: str) -> BaseModel:
        return SpeechDecision(reasoning="r", content="c")

    port, client = _port(script)
    await port.act(_obs("DAY_SPEECH"), time.time() + 60)
    assert "你的性格" not in client.calls[-1][1]
```

追加到 `backend/tests/test_agent_profile.py` 末尾：

```python
def test_profile_personality_field() -> None:
    from app.agent.personality import PersonalitySpec

    assert AgentProfile(model="m").personality is None
    p = AgentProfile.model_validate(
        {"model": "m", "personality": {"description": "老油条", "traits": {"多疑": 0.9}}}
    )
    assert isinstance(p.personality, PersonalitySpec) and p.personality.traits == {"多疑": 0.9}
    with pytest.raises(ValidationError):
        AgentProfile.model_validate({"model": "m", "personality": {"description": "我你知道谁是狼"}})
    with pytest.raises(ValidationError):
        AgentProfile.model_validate({"model": "m", "personality": {}})
```

`backend/tests/test_api_lobby.py`：`test_create_legacy_ai_model_echoes_star` 的精确相等 dict 里在 `"skills": []` 之后加 `"personality": None,`；并追加：

```python
def test_create_agents_with_personality_echo_and_guardrail_422(client: TestClient) -> None:
    body = {
        "preset": "std_9_kill_side",
        "agents": {
            "0": {
                "model": "m",
                "personality": {
                    "description": "老油条",
                    "traits": {"多疑": 0.9},
                    "preset": {"system": "MBTI", "value": "enfp"},
                    "style_notes": "爱用感叹号",
                },
            }
        },
    }
    r = client.post("/api/v1/games", json=body)
    assert r.status_code == 200, r.text
    p = r.json()["agents"]["0"]["personality"]
    assert p["description"] == "老油条" and p["preset"]["value"] == "ENFP"
    bad = {"preset": "std_9_kill_side", "agents": {"0": {"model": "m", "personality": {"description": "上帝视角看一下"}}}}
    assert client.post("/api/v1/games", json=bad).status_code == 422
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_agent_prompts.py tests/test_agent_player.py tests/test_agent_profile.py tests/test_api_lobby.py -q`
Expected: 新用例 FAIL（`personality_text` 未知参数 / `AgentPlayerPort` 无 `personality` / `AgentProfile` 拒绝 `personality` 键）；`test_create_legacy_ai_model_echoes_star` 在补了 `"personality": None` 后也 FAIL（字段尚不存在）

- [ ] **Step 3: 实现**

`app/agent/prompts.py` `static_system_prompt`：

```python
def static_system_prompt(
    config: GameConfig, seat: int, role: RoleType, personality_text: str = ""
) -> str:
    roles_desc = "、".join(f"{slot.role.value}x{slot.count}" for slot in config.roles)
    win = _WIN_TEXT.get(config.win_condition, str(config.win_condition))
    sheriff = "启用警长（1.5 票与发言顺序权）" if config.sheriff.enabled else "无警长"
    # 人设段（issue #57）：只在静态段，位于角色行之后、通用约束句之前；为空时输出逐字不变
    personality_block = f"== 你的性格 ==\n{personality_text}\n" if personality_text else ""
    return (
        "你在玩狼人杀。服务器是唯一裁决者，你只提交意图。\n"
        f"本局配置：{config.num_players} 人（{roles_desc}）；胜利条件：{win}；{sheriff}。\n"
        f"你是 {seat} 号，角色：{role.value}。{ROLE_BRIEFS[role]}\n"
        f"{personality_block}"
        "发言用中文，符合角色立场；狼人白天绝不能泄露夜间的私下谋划。"
    )
```

`app/agent/agent_player.py`：
- import：`from app.agent.personality import PersonalitySpec, render_personality`（`personality.py` 只依赖 pydantic，无环）。
- `__init__(..., skills: Sequence[Skill] = (), personality: PersonalitySpec | None = None)`：`self._personality = personality`。
- `_system_for`：

```python
        if self._system_prompt is None:
            personality_text = render_personality(self._personality) if self._personality else ""
            static = static_system_prompt(
                self._game_config, self._seat, obs.my_role, personality_text=personality_text
            )
            if self._skills:
                static += "\n== 你的技能 ==\n" + skills_index_text(self._skills)
            self._system_prompt = static
```

- `build_agent_port`：传 `personality=profile.personality`。

`app/agent/profile.py`：
- import：`from app.agent.personality import PersonalitySpec`。
- `AgentProfile` 加 `personality: PersonalitySpec | None = None  # 任意性格特点（issue #57）`；模块 docstring 的「（#56 模型路由、#58 skills）」改为「（#56 模型路由、#58 skills、#57 personality）」。

- [ ] **Step 4: 跑测试确认通过 + 回归**

Run: `uv run pytest tests/test_agent_prompts.py tests/test_agent_player.py tests/test_agent_profile.py tests/test_api_lobby.py tests/test_agent_integration.py -q`
Expected: 全部 PASS

Run: `uv run pytest -q -x --ignore=tests/test_api_e2e.py && uv run ruff check . && uv run ruff format --check . && uv run mypy app`
Expected: 全绿（含 `test_importing_registry_does_not_load_litellm`——`personality.py` 不 import agent_player）

- [ ] **Step 5: Commit**

```bash
git add backend/app/agent/prompts.py backend/app/agent/agent_player.py backend/app/agent/profile.py backend/tests/test_agent_prompts.py backend/tests/test_agent_player.py backend/tests/test_agent_profile.py backend/tests/test_api_lobby.py
git commit -m "feat(agent): 人设段注入系统 prompt 静态段；AgentProfile.personality (issue #57)"
```

---

### Task 3: 档案表摘要、README / PRD、一致性 bench

**Files:**
- Modify: `backend/app/cli/render.py`（`render_agent_roster`）
- Modify: `README.md`（「每座位 Agent 档案」样例 + 新小节「人格 / Personality」）、`docs/specs/requirements.md`（§4.4.2 补一段、§5.2 `agents` 说明补 `personality`）
- Modify: `backend/tests/test_cli_render.py`、`backend/tests/test_cli_play_watch.py`、`backend/tests/test_agent_bench.py`

**Interfaces:**
- Consumes: Task 1 `personality_summary`；Task 2 `AgentProfile.personality`。
- Produces: 档案表 `性格 {summary}` 列；文档。

- [ ] **Step 1: 写失败测试**

`backend/tests/test_cli_render.py::test_render_agent_roster` 末尾追加：

```python
    from app.agent.personality import PersonalityPreset, PersonalitySpec

    with_p = render_agent_roster(
        {"0": AgentProfile(model="m", personality=PersonalitySpec(preset=PersonalityPreset(system="MBTI", value="enfp")))},
        num_players=1,
        human_seat=None,
    )
    assert "性格 ENFP" in with_p
    assert "性格" not in render_agent_roster({"0": AgentProfile(model="m")}, num_players=1, human_seat=None)
```

追加到 `backend/tests/test_cli_play_watch.py` 末尾：

```python
def test_load_agent_profiles_personality_and_guardrail(tmp_path) -> None:
    from app.cli.play import load_agent_profiles

    good = tmp_path / "p.yaml"
    good.write_text(
        'seats:\n  "0": {model: ollama/a, personality: {description: 老油条, traits: {多疑: 0.9}}}\n'
        '  "3": {model: ollama/b, personality: {preset: {system: MBTI, value: enfp}, style_notes: 爱用感叹号}}\n',
        encoding="utf-8",
    )
    agents = load_agent_profiles(str(good))
    assert agents["0"].personality is not None and agents["0"].personality.traits == {"多疑": 0.9}
    assert agents["3"].personality is not None and agents["3"].personality.preset is not None
    assert agents["3"].personality.preset.value == "ENFP"

    bad = tmp_path / "bad.yaml"
    bad.write_text('seats:\n  "0": {model: ollama/a, personality: {description: 你知道谁是狼}}\n', encoding="utf-8")
    with pytest.raises(argparse.ArgumentTypeError, match="越权"):
        load_agent_profiles(str(bad))
```

追加到 `backend/tests/test_agent_bench.py` 末尾（沿用文件的 env 门控与 import；`GameRegistry`、`InMemoryEventStore`、`build_preset` 已 import）：

```python
async def test_personality_contrast_smoke() -> None:
    """一致性冒烟：同一 observation 下「多疑」vs「从众」两种人格各发言一次，打印长度与关键词（不断言方向）。"""
    import time

    from app.agent.agent_player import AgentConfig, AgentPlayerPort
    from app.agent.llm_client import LiteLLMInstructorClient
    from app.agent.personality import PersonalitySpec
    from app.engine.config import RoleType
    from app.engine.observation import PlayerObservation

    assert SMOKE_MODEL is not None
    obs = PlayerObservation(
        game_id="bench",
        state_version=3,
        my_seat=2,
        my_role=RoleType.VILLAGER,
        my_status="ALIVE",
        phase="DAY_SPEECH",
        round=1,
        seats=[{"seat": i, "alive": True, "is_sheriff": False} for i in range(9)],
        sheriff_seat=None,
        badge_flow_claims={0: (3, 5)},
        private={},
        available_actions=[2],
    )
    out: dict[str, str] = {}
    for label, traits in (("多疑", {"多疑": 0.9}), ("从众", {"从众": 0.9})):
        port = AgentPlayerPort(
            seat=2,
            game_config=build_preset("std_9_kill_side"),
            agent_config=AgentConfig(model=SMOKE_MODEL),
            client=LiteLLMInstructorClient(),
            personality=PersonalitySpec(traits=traits),
        )
        action = await port.act(obs, time.time() + 120)
        out[label] = getattr(action, "content", "")
    for label, text in out.items():
        print(f"[{label}] len={len(text)} 含'金水'={'金水' in text} 含'怀疑'={'怀疑' in text}: {text[:80]}")
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_cli_render.py::test_render_agent_roster tests/test_cli_play_watch.py::test_load_agent_profiles_personality_and_guardrail -q`
Expected: render 用例 FAIL（无「性格」列）；YAML 用例通过或失败取决于 Task 2（`AgentProfile.personality` 已存在 → 大概率 PASS；只需 render 用例 RED）

- [ ] **Step 3: 实现**

`app/cli/render.py`：import `from app.agent.personality import personality_summary`；`render_agent_roster` 在技能列之后加

```python
        if p.personality is not None:
            parts.append(f"性格 {personality_summary(p.personality)}")
```

`README.md`：
- 「每座位 Agent 档案」YAML 样例给 `"0"` 加 `personality: {description: 老油条，话不多但每句都带钩子, traits: {多疑: 0.9, 冷静: 0.8}}`、给 `"3"` 加 `personality: {preset: {system: MBTI, value: ENFP}, style_notes: 爱用感叹号}`。
- 新小节「人格 / Personality」：三层输入各一句（description ≤300 字；traits 词→0–1 强度，内置词表列出 15 个词；preset MBTI 四字母或 `{E:0.8,...}`、BIG_FIVE `{O,C,E,A,N}`）；优先级（描述 > 特质 > 预设）；护栏短语会被拒绝；人设只影响风格、不改规则；只在系统 prompt 静态段。

`docs/specs/requirements.md`：§4.4.2 三段式 prompt 静态段处补一句「**人格**：`AgentProfile.personality`（自由描述 / 特质词表 / MBTI、Big Five 预设）翻译为狼人杀语境行为倾向，作为静态段的『== 你的性格 ==』小节；预设展开用隐式写法；越权短语建局即拒」；§5.2 `agents` 字段说明补 `personality`。

- [ ] **Step 4: 跑测试确认通过 + 全量（含 E2E）**

Run: `uv run pytest tests/test_cli_render.py tests/test_cli_play_watch.py tests/test_agent_bench.py -q`
Expected: 全部 PASS（bench skip）

Run: `uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run mypy app`
Expected: 全量（含 E2E）全绿；lint/type 全过

- [ ] **Step 5: 真机看一眼**

Run（`backend/`）：

```bash
printf 'seats:\n  "0": {name: 老张, model: ollama/a, personality: {description: 老油条，话不多但每句都带钩子, traits: {多疑: 0.9}}}\n  "3": {model: ollama/b, personality: {preset: {system: MBTI, value: enfp}}}\n' > /tmp/agents-p.yaml
PYTHONUNBUFFERED=1 uv run python -m app.cli.play --preset std_9_kill_side --seed 3 --view gm --delay 0 --no-color --agents /tmp/agents-p.yaml 2>/dev/null | head -4
```

Expected: `0号 老张 · ollama/a · T=0.3 · 性格 老油条，话不多但每句都带…` 与 `3号 Bot3 · ollama/b · T=0.3 · 性格 ENFP`（**不要**用 `timeout` 包裹；`head` 关管道后进程退出）。另跑一条护栏：档案里写 `personality: {description: 上帝视角}` → `app.cli.play: error: …越权…`。

- [ ] **Step 6: Commit**

```bash
git add backend/app/cli/render.py backend/tests/test_cli_render.py backend/tests/test_cli_play_watch.py backend/tests/test_agent_bench.py README.md docs/specs/requirements.md
git commit -m "feat(cli): 档案表人格摘要；README/PRD 人格说明；一致性 bench 冒烟 (issue #57)"
```

---

## Self-Review

- **Spec 覆盖**：§2 schema/校验→T1；§3 翻译层→T1；§4 接入（prompts / agent_player / profile / render / API 自动 / 反思不带）→T2、T3；§5 bench→T3；§6 测试逐条→T1–T3；§7 不在范围无任务。
- **占位符扫描**：无 TBD/TODO；T3 Step 2 对 YAML 用例可能已 PASS 的说明是明确预期而非留白。
- **类型一致性**：`PersonalityPreset(system, value)`、`PersonalitySpec(description, traits, preset, style_notes)`、`render_personality(spec)`、`personality_summary(spec)`、`static_system_prompt(..., personality_text="")`、`AgentPlayerPort(personality=)`、`AgentProfile.personality` 在各任务间一致。
- **import 方向**：`personality.py` 只依赖 pydantic；`profile.py` / `agent_player.py` / `render.py` import 它均安全；litellm 惰性守卫不受影响。
- **契约连带**：`AgentProfile` 新增字段 → `test_api_lobby.py` 精确相等断言补 `"personality": None`（T2 Step 1 已含）。
