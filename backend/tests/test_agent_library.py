"""Agent 档案库存储（issue #26）：round-trip、原子写、坏文件跳过、目录惰性。"""

from app.agent.profile import AgentProfile
from app.runtime.agent_library import InMemoryAgentLibrary, JsonFileAgentLibrary, StoredAgent


def _stored(agent_id: str = "a_00000001", name: str = "夜枭") -> StoredAgent:
    return StoredAgent(
        agent_id=agent_id,
        profile=AgentProfile(name=name, model="ollama/qwen2.5:14b", skills=("logic-chain",)),
        created_at="2026-09-24T00:00:00+00:00",
        updated_at="2026-09-24T00:00:00+00:00",
    )


def test_in_memory_crud() -> None:
    lib = InMemoryAgentLibrary()
    assert lib.list() == [] and lib.get("a_x") is None
    lib.put(_stored())
    assert lib.get("a_00000001").profile.name == "夜枭"  # type: ignore[union-attr]
    lib.put(_stored(name="铁齿"))
    assert [s.profile.name for s in lib.list()] == ["铁齿"]
    assert lib.delete("a_00000001") is True and lib.delete("a_00000001") is False


def test_json_file_roundtrip_lazy_dir_and_corrupt_skipped(tmp_path, caplog) -> None:
    d = tmp_path / "agents"
    lib = JsonFileAgentLibrary(d)
    assert lib.list() == [] and not d.exists()
    lib.put(_stored())
    assert (d / "a_00000001.json").exists()
    assert sorted(p.name for p in d.iterdir()) == ["a_00000001.json"]
    got = JsonFileAgentLibrary(d).get("a_00000001")
    assert got is not None and got.profile.skills == ("logic-chain",)
    (d / "a_bad.json").write_text("{bad", encoding="utf-8")
    assert [s.agent_id for s in JsonFileAgentLibrary(d).list()] == ["a_00000001"]
    assert "a_bad.json" in caplog.text
    assert lib.delete("a_00000001") is True and not (d / "a_00000001.json").exists()
