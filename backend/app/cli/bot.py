"""脚本 bot 与单局驱动。零 LLM、零 IO（除 simulate.py 打印）。"""

from __future__ import annotations

from app.engine import rng
from app.engine.actions import Action, DayVote, NightAction, NightActionType, Speak
from app.engine.config import GameConfig
from app.engine.engine import create_game, step
from app.engine.events import Event
from app.engine.phases import Phase, expected_actors
from app.engine.state import GameState, living_seats, player_at


def _legal_night_targets(state: GameState, seat: int) -> list[int]:
    return [s for s in living_seats(state) if s != seat] or living_seats(state)


class RandomBot:
    """在合法行动集合内均匀随机选择，随机源由 (seed, seat, state_version) 派生。"""

    @staticmethod
    def choose_action(state: GameState, seat: int) -> Action:
        seed = state.config.seed if state.config.seed is not None else 0

        def pick(items: list[int], salt: str) -> int:
            idx = rng.derive_int(
                seed=seed, purpose=f"bot:{seat}:{salt}", seq=state.state_version, modulo=len(items)
            )
            return items[idx]

        ph = state.phase
        pl = player_at(state, seat)

        if ph == Phase.NIGHT_GUARD:
            targets = [s for s in living_seats(state) if s != pl.last_guard_target]
            return NightAction(
                actor_seat=seat, action_type=NightActionType.GUARD, target_seat=pick(targets, "g")
            )
        if ph == Phase.NIGHT_WEREWOLF:
            targets = _legal_night_targets(state, seat)
            return NightAction(
                actor_seat=seat, action_type=NightActionType.KILL, target_seat=pick(targets, "k")
            )
        if ph == Phase.NIGHT_WITCH:
            return NightAction(actor_seat=seat, action_type=NightActionType.SKIP)
        if ph == Phase.NIGHT_SEER:
            targets = _legal_night_targets(state, seat)
            return NightAction(
                actor_seat=seat, action_type=NightActionType.CHECK, target_seat=pick(targets, "c")
            )
        if ph == Phase.DAY_SPEECH:
            return Speak(actor_seat=seat, content="(bot)")
        if ph in (Phase.VOTE, Phase.VOTE_PK):
            cands = list(state.vote_candidates) or [s for s in living_seats(state) if s != seat]
            cands = cands or living_seats(state)
            return DayVote(actor_seat=seat, target_seat=pick(cands, "v"))
        # 其它阶段（猎人/警长，Stage 2/3）默认 skip 发言
        return Speak(actor_seat=seat, content="(bot-skip)")


def run_game(config: GameConfig, game_id: str) -> tuple[GameState, list[Event]]:
    res = create_game(config, game_id)
    state, events = res.state, list(res.events)
    guard = 0
    while state.phase != Phase.GAME_OVER:
        actors = sorted(expected_actors(state))
        if not actors:
            raise RuntimeError(f"无人可行动但未终局：phase={state.phase}")
        for seat in actors:
            # 终局后 expected_actors 为空，剩余座位在下方成员检查处自然跳过
            if seat not in expected_actors(state):
                continue
            action = RandomBot.choose_action(state, seat)
            res = step(state, action)
            if res.rejection is not None:
                raise RuntimeError(f"bot 行动被拒：{res.rejection} @ {state.phase}")
            state, new_events = res.state, res.events
            events.extend(new_events)
        guard += 1
        if guard > 100_000:
            raise RuntimeError("对局未收敛")
    return state, events
