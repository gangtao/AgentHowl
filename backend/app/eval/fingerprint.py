"""档案指纹与摘要（issue #60）：按内容聚合多局统计；name / memory_id 不参与。"""

from __future__ import annotations

import hashlib
import json

from app.agent.personality import personality_summary
from app.agent.profile import AgentProfile

_DEFAULT_TEMPERATURE = AgentProfile.model_fields["temperature"].default


def profile_fingerprint(profile: AgentProfile) -> str:
    """去 name / memory_id 后规范化 JSON 的 sha1 前 10 位：内容相同即同一配置。"""
    body = profile.model_dump(mode="json", exclude={"name", "memory_id"})
    canon = json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha1(canon.encode("utf-8")).hexdigest()[:10]


def profile_summary(profile: AgentProfile) -> str:
    """报告显示名：模型 + 技能 + 性格 + 非默认温度 + thinking。"""
    parts = [profile.model]
    if profile.skills:
        parts.append("技能 " + ",".join(profile.skills))
    if profile.personality is not None:
        parts.append(f"性格 {personality_summary(profile.personality)}")
    if profile.temperature != _DEFAULT_TEMPERATURE:
        parts.append(f"T={profile.temperature}")
    if profile.thinking:
        parts.append("thinking")
    return " · ".join(parts)
