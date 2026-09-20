"""经验存储（issue #59）：round-trip、缺失即新、原子写、损坏 fail-loud——文件用 tmp_path。"""

import json

import pytest

from app.agent.experience import AgentExperience, GameReflection
from app.engine.config import RoleType
from app.runtime.experience_store import InMemoryExperienceStore, JsonFileExperienceStore
from app.store.event_store import StoreCorruptionError


def _sample(mid: str = "alice") -> AgentExperience:
    exp = AgentExperience(memory_id=mid)
    exp.record_game(
        game_id="g1",
        role=RoleType.SEER,
        won=True,
        reflection=GameReflection(lessons=["早报警徽流"], opponent_notes={3: ["爱跟票"]}),
        seat_to_memory_id={0: mid, 3: "bob"},
        my_seat=0,
        ts="2026-09-20T00:00:00+00:00",
    )
    return exp


def test_in_memory_roundtrip_counts_saves_and_isolates_copies() -> None:
    store = InMemoryExperienceStore()
    fresh = store.load("alice")
    assert fresh.memory_id == "alice" and fresh.games_played == 0 and store.saves == 0
    exp = _sample()
    store.save(exp)
    exp.games_played = 99  # 保存后改原对象不得影响 store
    got = store.load("alice")
    assert got.games_played == 1 and got.lessons[0].text == "早报警徽流" and store.saves == 1


def test_json_file_missing_is_fresh_and_does_not_create_dir(tmp_path) -> None:
    d = tmp_path / "mem"
    store = JsonFileExperienceStore(d)
    assert store.load("alice").games_played == 0
    assert not d.exists()


def test_json_file_save_creates_dir_roundtrips_and_leaves_no_temp(tmp_path) -> None:
    d = tmp_path / "mem"
    store = JsonFileExperienceStore(d)
    store.save(_sample())
    assert store.path_for("alice") == d / "alice.json"
    assert sorted(p.name for p in d.iterdir()) == ["alice.json"]
    got = store.load("alice")
    assert got.games_played == 1 and got.opponent_notes["bob"][0].text == "爱跟票"
    raw = json.loads((d / "alice.json").read_text(encoding="utf-8"))
    assert raw["memory_id"] == "alice" and raw["lessons"][0]["role"] == "SEER"


@pytest.mark.parametrize(
    ("content", "hint"),
    [
        ("{not json", "合法 JSON"),
        ("[1, 2]", "顶层"),
        ('{"memory_id": "alice", "games_played": "many"}', "校验失败"),
        ('{"memory_id": "bob"}', "文件名不符"),
    ],
)
def test_json_file_corruption_is_loud_and_names_path(tmp_path, content, hint) -> None:
    d = tmp_path / "mem"
    d.mkdir()
    (d / "alice.json").write_text(content, encoding="utf-8")
    with pytest.raises(StoreCorruptionError, match=hint) as ei:
        JsonFileExperienceStore(d).load("alice")
    assert "alice.json" in str(ei.value)
