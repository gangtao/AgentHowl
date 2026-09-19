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
_MBTI_DEFAULT_STRENGTH = {
    "EI": 0.5,
    "SN": 0.3,
    "TF": 0.5,
    "JP": 0.5,
}  # 落在「比较」档；S/N 信号弱 → 「略微」档
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
            raise ValueError(
                "personality 至少要给 description / traits / preset / style_notes 之一"
            )
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
                lines.append(
                    f"你{_band(_MBTI_DEFAULT_STRENGTH[MBTI_AXES[i]])}倾向于{_MBTI_TEXT[letter]}。"
                )
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
