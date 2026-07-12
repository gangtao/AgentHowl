"""EventStore 测试：编解码、契约（双实现参数化）、文件专项。issue #28。"""

import pytest

from app.cli.bot import run_game
from app.engine.config import build_preset
from app.engine.events import Event, reduce_all
from app.engine.phases import Phase
from app.engine.state import GameState
from app.store.event_store import (
    GameMeta,
    SeatName,
    StoreError,
    event_from_json,
    event_to_json,
    initial_state,
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
