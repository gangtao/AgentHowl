import json

from app.cli.export_fixture import export_fixture, main
from app.engine.events import reduce_all
from app.store.event_store import GameMeta, event_from_json, initial_state


def test_fixture_states_match_prefix_reduce_and_sets_sorted() -> None:
    doc = export_fixture("std_9_kill_side", 3)
    assert doc["preset"] == "std_9_kill_side" and doc["seed"] == 3
    meta = GameMeta.model_validate(doc["meta"])
    # event_from_json 还原具体 payload 子类（SerializeAsAny 只管序列化，#34）
    events = [event_from_json(e) for e in doc["events"]]
    assert len(doc["states"]) == len(events) and doc["states"][-1]["phase"] == "GAME_OVER"
    for i in (0, 5, len(events) // 2, len(events) - 1):
        expected = reduce_all(initial_state(meta), events[: i + 1]).model_dump(mode="json")
        got = doc["states"][i]
        for k in ("acted_seats", "sheriff_declared", "sheriff_withdrawn", "sheriff_confirmed"):
            assert got[k] == sorted(got[k])
            expected[k] = sorted(expected[k])
        assert got == expected
    assert doc["meta"]["agents"] == {}


def test_main_writes_file(tmp_path) -> None:
    out = tmp_path / "f.json"
    main(["--preset", "std_9_kill_all", "--seed", "3", "--out", str(out)])
    doc = json.loads(out.read_text(encoding="utf-8"))
    assert doc["preset"] == "std_9_kill_all" and doc["events"][0]["type"] == "GAME_CREATED"
