"""AgentProfile（issue #56）：schema、查找、校验、旧字段折叠、到 AgentConfig 的映射。"""

import pytest
from pydantic import ValidationError

from app.agent.profile import (
    AgentProfile,
    legacy_to_profiles,
    merge_profiles,
    profile_for,
    to_agent_config,
    validate_profiles,
)
from app.engine.config import build_preset


def test_schema_defaults_and_forbid_unknown_keys() -> None:
    p = AgentProfile(model="ollama/a")
    assert p.name is None and p.model_speech is None and p.reflection_model is None
    assert p.thinking is False and p.temperature == 0.3
    with pytest.raises(ValidationError):
        AgentProfile(model="ollama/a", modle_speech="x")  # type: ignore[call-arg]  # 键名笔误
    with pytest.raises(ValidationError):
        AgentProfile(model="ollama/a", temperature=2.5)
    with pytest.raises(ValidationError):
        AgentProfile()  # type: ignore[call-arg]  # 缺 model


def test_name_strips_whitespace_and_blank_becomes_none() -> None:
    assert AgentProfile(model="m", name="  ").name is None
    assert AgentProfile(model="m", name=" 老张 ").name == "老张"


def test_profile_for_prefers_seat_then_star() -> None:
    star = AgentProfile(model="ollama/star")
    seat3 = AgentProfile(model="ollama/three")
    agents = {"*": star, "3": seat3}
    assert profile_for(agents, 3) is seat3
    assert profile_for(agents, 0) is star
    assert profile_for({"3": seat3}, 0) is None
    assert profile_for({}, 0) is None


def test_validate_profiles_keys() -> None:
    p = AgentProfile(model="m")
    validate_profiles({"*": p, "0": p, "8": p}, num_players=9)
    for bad in ("9", "-1", "a", "01"):
        with pytest.raises(ValueError, match="座位"):
            validate_profiles({bad: p}, num_players=9)


def test_legacy_to_profiles_and_merge() -> None:
    assert legacy_to_profiles(None) == {}
    legacy = legacy_to_profiles("ollama/a", "ollama/b", reflection_model="ollama/c", thinking=True)
    assert legacy == {
        "*": AgentProfile(
            model="ollama/a", model_speech="ollama/b", reflection_model="ollama/c", thinking=True
        )
    }
    seat0 = {"0": AgentProfile(model="ollama/z")}
    merged = merge_profiles(seat0, legacy)
    assert merged["0"].model == "ollama/z" and merged["*"].model == "ollama/a"
    assert merge_profiles(None, legacy) == legacy
    assert merge_profiles(seat0, {}) == seat0
    with pytest.raises(ValueError, match=r"agents\['\*'\]"):
        merge_profiles({"*": AgentProfile(model="ollama/x")}, legacy)


def test_to_agent_config_maps_fields_and_seed() -> None:
    cfg = build_preset("std_9_kill_side").model_copy(update={"seed": 11})
    p = AgentProfile(
        model="ollama/a",
        model_speech="ollama/b",
        reflection_model="ollama/c",
        thinking=True,
        temperature=0.7,
    )
    ac = to_agent_config(p, cfg)
    assert (ac.model, ac.model_speech, ac.reflection_model) == ("ollama/a", "ollama/b", "ollama/c")
    assert ac.thinking is True and ac.temperature == 0.7
    assert ac.agent_seed == 11
    assert to_agent_config(p, cfg.model_copy(update={"seed": None})).agent_seed == 0


def test_importing_registry_does_not_load_litellm() -> None:
    """档案模块进 registry 的 import 图后，服务启动不得连带加载 litellm（惰性加载设计）。"""
    import subprocess
    import sys
    from pathlib import Path

    code = "import sys, app.runtime.registry, app.agent.profile; print('litellm' in sys.modules)"
    out = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        check=True,
        cwd=Path(__file__).resolve().parents[1],
    ).stdout.strip()
    assert out == "False"
