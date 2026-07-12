"""EventStore 测试：编解码、契约（双实现参数化）、文件专项。issue #28。"""

import json
from pathlib import Path

import pytest

from app.cli.bot import run_game
from app.engine.config import build_preset
from app.engine.events import Event, reduce_all
from app.engine.phases import Phase
from app.engine.state import GameState
from app.store.event_store import (
    EventStore,
    GameExistsError,
    GameMeta,
    GameNotFoundError,
    InMemoryEventStore,
    JsonFileEventStore,
    SeatName,
    SeqConflictError,
    StoreCorruptionError,
    StoreError,
    event_from_json,
    event_to_json,
    initial_state,
    load_state,
)


def _run_fixture_game(seed: int = 42) -> tuple[GameMeta, GameState, list[Event]]:
    """跑一局 9 人 bot 对局，返回 (meta, 终局状态, 事件流)。"""
    cfg = build_preset("std_9_kill_side").model_copy(update={"seed": seed})
    final, events = run_game(cfg, game_id="g1")
    roster = tuple(SeatName(seat=p.seat, display_name=p.display_name) for p in final.players)
    return GameMeta(game_id="g1", config=final.config, roster=roster), final, events


def _assert_replay_matches(replayed: GameState, final: GameState) -> None:
    """回放状态与实时终局一致（口径与 test_determinism 一致，排除游标字段）。"""
    assert replayed.phase == final.phase == Phase.GAME_OVER
    assert replayed.winner == final.winner
    assert [p.alive for p in replayed.players] == [p.alive for p in final.players]
    assert [p.role for p in replayed.players] == [p.role for p in final.players]
    assert replayed.sheriff_seat == final.sheriff_seat
    assert replayed.election_stage == final.election_stage


class TestCodec:
    def test_roundtrip_whole_game(self) -> None:
        """整局事件 JSON 往返后逐条相等（payload 具体类不丢失）。"""
        _, _, events = _run_fixture_game()
        for ev in events:
            restored = event_from_json(event_to_json(ev))
            assert restored == ev
            assert type(restored.payload) is type(ev.payload)

    def test_bad_event_type_fails_loud(self) -> None:
        from app.store.event_store import StoreCorruptionError

        _, _, events = _run_fixture_game()
        d = event_to_json(events[0])
        d["type"] = "NO_SUCH_EVENT"
        with pytest.raises(StoreCorruptionError):
            event_from_json(d)

    def test_non_dict_fails_loud(self) -> None:
        from app.store.event_store import StoreCorruptionError

        with pytest.raises(StoreCorruptionError):
            event_from_json("not a dict")


class TestInitialState:
    def test_replay_from_initial_state(self) -> None:
        """initial_state(meta) 作为回放起点，reduce_all 后与实时终局一致。"""
        meta, final, events = _run_fixture_game()
        replayed = reduce_all(initial_state(meta), events)
        _assert_replay_matches(replayed, final)

    def test_sparse_roster_rejected(self) -> None:
        meta, _, _ = _run_fixture_game()
        holed = GameMeta(
            game_id=meta.game_id,
            config=meta.config,
            roster=meta.roster[1:],  # 缺 0 号座
        )
        with pytest.raises(StoreError):
            initial_state(holed)


@pytest.fixture(params=["memory", "jsonl"])
def store(request: pytest.FixtureRequest, tmp_path: Path) -> EventStore:
    """契约测试跑在所有实现上。"""
    if request.param == "memory":
        return InMemoryEventStore()
    return JsonFileEventStore(tmp_path / "data")


class TestContract:
    def test_roundtrip_and_load_state(self, store: EventStore) -> None:
        meta, final, events = _run_fixture_game()
        store.create_game(meta)
        for ev in events:
            store.append("g1", ev)
        assert store.load_meta("g1") == meta
        assert store.load_events("g1") == events
        _assert_replay_matches(load_state(store, "g1"), final)

    def test_from_seq_inclusive(self, store: EventStore) -> None:
        meta, _, events = _run_fixture_game()
        store.create_game(meta)
        for ev in events:
            store.append("g1", ev)
        assert store.load_events("g1", from_seq=5) == [e for e in events if e.seq >= 5]
        assert store.load_events("g1", from_seq=events[-1].seq + 1) == []

    def test_seq_duplicate_rejected(self, store: EventStore) -> None:
        meta, _, events = _run_fixture_game()
        store.create_game(meta)
        store.append("g1", events[0])
        with pytest.raises(SeqConflictError):
            store.append("g1", events[0])

    def test_seq_gap_rejected(self, store: EventStore) -> None:
        meta, _, events = _run_fixture_game()
        store.create_game(meta)
        with pytest.raises(SeqConflictError):
            store.append("g1", events[1])  # 首事件必须 seq=1

    def test_cross_game_id_rejected(self, store: EventStore) -> None:
        meta, _, events = _run_fixture_game()
        store.create_game(meta)
        alien = events[0].model_copy(update={"game_id": "other"})
        with pytest.raises(StoreError):
            store.append("g1", alien)

    def test_unknown_game_fails(self, store: EventStore) -> None:
        _, _, events = _run_fixture_game()
        with pytest.raises(GameNotFoundError):
            store.load_meta("nope")
        with pytest.raises(GameNotFoundError):
            store.load_events("nope")
        with pytest.raises(GameNotFoundError):
            store.append("nope", events[0])

    def test_duplicate_create_rejected(self, store: EventStore) -> None:
        meta, _, _ = _run_fixture_game()
        store.create_game(meta)
        with pytest.raises(GameExistsError):
            store.create_game(meta)

    def test_bad_game_id_rejected(self, store: EventStore) -> None:
        meta, _, _ = _run_fixture_game()
        for bad in ("", "a/b", "..", "a b", "中"):
            evil = GameMeta(game_id=bad, config=meta.config, roster=meta.roster)
            with pytest.raises(StoreError):
                store.create_game(evil)

    def test_list_games_sorted(self, store: EventStore) -> None:
        meta, _, _ = _run_fixture_game()
        for gid in ("g2", "g1"):
            store.create_game(GameMeta(game_id=gid, config=meta.config, roster=meta.roster))
        assert store.list_games() == ["g1", "g2"]


class TestJsonFile:
    def test_restart_reloads(self, tmp_path: Path) -> None:
        """同一 data_dir 新建实例（模拟进程重启）后装载与续写均正常。"""
        meta, final, events = _run_fixture_game()
        s1 = JsonFileEventStore(tmp_path / "d")
        s1.create_game(meta)
        for ev in events[:-1]:
            s1.append("g1", ev)

        s2 = JsonFileEventStore(tmp_path / "d")
        assert s2.load_meta("g1") == meta
        assert s2.load_events("g1") == events[:-1]
        s2.append("g1", events[-1])  # seq 续接
        _assert_replay_matches(load_state(s2, "g1"), final)

    def test_list_games_from_disk(self, tmp_path: Path) -> None:
        meta, _, _ = _run_fixture_game()
        s1 = JsonFileEventStore(tmp_path / "d")
        s1.create_game(meta)
        s2 = JsonFileEventStore(tmp_path / "d")
        assert s2.list_games() == ["g1"]

    def _populated_dir(self, tmp_path: Path) -> tuple[Path, GameMeta, list[Event]]:
        meta, _, events = _run_fixture_game()
        s = JsonFileEventStore(tmp_path / "d")
        s.create_game(meta)
        for ev in events[:10]:
            s.append("g1", ev)
        return tmp_path / "d" / "g1.jsonl", meta, events

    def test_torn_tail_repaired(self, tmp_path: Path) -> None:
        """残尾行（崩溃中断的 append）开箱截断，装载与续写正常。"""
        path, _, events = self._populated_dir(tmp_path)
        with path.open("ab") as f:
            f.write(b'{"kind": "event", "da')  # 无换行的半行

        s = JsonFileEventStore(path.parent)
        assert s.load_events("g1") == events[:10]
        s.append("g1", events[10])  # 修复后可继续追加
        assert not path.read_bytes().rstrip(b"\n").endswith(b'"da')
        # 再次冷装载验证文件已物理修复
        assert JsonFileEventStore(path.parent).load_events("g1") == events[:11]

    def test_middle_bad_line_fails_loud(self, tmp_path: Path) -> None:
        path, _, _ = self._populated_dir(tmp_path)
        lines = path.read_bytes().split(b"\n")
        lines[3] = b"@@garbage@@"
        path.write_bytes(b"\n".join(lines))
        with pytest.raises(StoreCorruptionError):
            JsonFileEventStore(path.parent).load_events("g1")

    def test_terminated_bad_tail_fails_loud(self, tmp_path: Path) -> None:
        """以换行结尾的坏行不是残尾，是真损坏。"""
        path, _, _ = self._populated_dir(tmp_path)
        with path.open("ab") as f:
            f.write(b"@@garbage@@\n")
        with pytest.raises(StoreCorruptionError):
            JsonFileEventStore(path.parent).load_events("g1")

    def test_duplicate_meta_fails_loud(self, tmp_path: Path) -> None:
        path, meta, _ = self._populated_dir(tmp_path)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"kind": "meta", "data": meta.model_dump(mode="json")}) + "\n")
        with pytest.raises(StoreCorruptionError):
            JsonFileEventStore(path.parent).load_events("g1")

    def test_seq_hole_in_file_fails_loud(self, tmp_path: Path) -> None:
        path, _, _ = self._populated_dir(tmp_path)
        lines = path.read_bytes().split(b"\n")
        del lines[3]  # 抠掉一条中间事件 → seq 洞
        path.write_bytes(b"\n".join(lines))
        with pytest.raises(StoreCorruptionError):
            JsonFileEventStore(path.parent).load_events("g1")

    def test_meta_not_first_fails_loud(self, tmp_path: Path) -> None:
        path, _, _ = self._populated_dir(tmp_path)
        lines = path.read_bytes().split(b"\n")
        lines[0], lines[1] = lines[1], lines[0]
        path.write_bytes(b"\n".join(lines))
        with pytest.raises(StoreCorruptionError):
            JsonFileEventStore(path.parent).load_events("g1")
