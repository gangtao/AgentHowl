"""脚本 bot 与单局驱动。零 LLM、零 IO（除 simulate.py 打印）。"""

from __future__ import annotations

from app.engine import rng
from app.engine.actions import (
    Action,
    DayVote,
    NightAction,
    NightActionType,
    SelfDestruct,
    Speak,
)
from app.engine.config import Faction, GameConfig
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

        if ph in (Phase.VOTE_PK, Phase.SHERIFF_PK) and state.speech_idx < len(state.speech_order):
            # PK 发言期：轮到的平票者发言；警上 PK 以 1/4 概率附带合法警徽流声明
            bf: tuple[int, ...] = ()
            if (
                ph == Phase.SHERIFF_PK
                and rng.derive_int(
                    seed=seed, purpose=f"bot:{seat}:bf", seq=state.state_version, modulo=4
                )
                == 0
            ):
                targets = [s for s in living_seats(state) if s != seat]
                if targets:
                    n_claim = 1 + rng.derive_int(
                        seed=seed, purpose=f"bot:{seat}:bfn", seq=state.state_version, modulo=2
                    )
                    picks: list[int] = []
                    for k in range(min(n_claim, len(targets))):
                        idx = rng.derive_int(
                            seed=seed,
                            purpose=f"bot:{seat}:bf{k}",
                            seq=state.state_version,
                            modulo=len(targets),
                        )
                        if targets[idx] not in picks:
                            picks.append(targets[idx])
                    bf = tuple(picks)
            return Speak(actor_seat=seat, content="(bot-pk)", badge_flow=bf)

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
            if pl.alive and pl.faction == Faction.WOLF:
                # 狼人偶发自爆（低概率），推动 Task 15 自爆分支被真实对局触达
                roll = rng.derive_int(
                    seed=seed,
                    purpose=f"bot:{seat}:selfdestruct",
                    seq=state.state_version,
                    modulo=20,
                )
                if roll == 0:
                    return SelfDestruct(actor_seat=seat)
            return Speak(actor_seat=seat, content="(bot)")
        if ph == Phase.LAST_WORDS and pl.is_sheriff:
            from app.engine.actions import SheriffAction, SheriffActionType

            return SheriffAction(actor_seat=seat, action_type=SheriffActionType.TEAR_BADGE)
        if ph in (Phase.VOTE, Phase.VOTE_PK):
            cands = list(state.vote_candidates) or [s for s in living_seats(state) if s != seat]
            cands = cands or living_seats(state)
            return DayVote(actor_seat=seat, target_seat=pick(cands, "v"))
        if ph == Phase.HUNTER_SHOOT:
            targets = [s for s in living_seats(state) if s != seat]
            if not targets:
                return NightAction(actor_seat=seat, action_type=NightActionType.SKIP)
            return NightAction(
                actor_seat=seat,
                action_type=NightActionType.SHOOT,
                target_seat=pick(targets, "shoot"),
            )
        from app.engine.actions import SheriffAction, SheriffActionType

        if ph == Phase.SHERIFF_ELECTION and state.election_stage == "direction":
            from app.engine.actions import Direction, SheriffAction, SheriffActionType

            left = (
                rng.derive_int(
                    seed=seed, purpose=f"bot:{seat}:dir", seq=state.state_version, modulo=2
                )
                == 0
            )
            return SheriffAction(
                actor_seat=seat,
                action_type=SheriffActionType.SET_SPEECH_DIRECTION,
                direction=Direction.LEFT if left else Direction.RIGHT,
            )
        if ph == Phase.SHERIFF_ELECTION and state.election_stage == "withdraw":
            from app.engine.actions import SheriffAction, SheriffActionType

            quit_race = (
                rng.derive_int(
                    seed=seed, purpose=f"bot:{seat}:withdraw", seq=state.state_version, modulo=8
                )
                == 0
            )
            return SheriffAction(
                actor_seat=seat,
                action_type=(
                    SheriffActionType.WITHDRAW if quit_race else SheriffActionType.RUN_FOR_SHERIFF
                ),
            )
        if ph == Phase.SHERIFF_ELECTION and state.election_stage == "candidacy":
            running = (
                rng.derive_int(
                    seed=seed, purpose=f"bot:{seat}:run", seq=state.state_version, modulo=2
                )
                == 0
            )
            return SheriffAction(
                actor_seat=seat,
                action_type=(
                    SheriffActionType.RUN_FOR_SHERIFF if running else SheriffActionType.WITHDRAW
                ),
            )
        if ph in (Phase.SHERIFF_ELECTION, Phase.SHERIFF_PK):
            cands = list(state.sheriff_candidates) or living_seats(state)
            return SheriffAction(
                actor_seat=seat,
                action_type=SheriffActionType.VOTE_SHERIFF,
                target_seat=pick(cands, "sv"),
            )
        # 其它阶段（LAST_WORDS 走下方遗言发言）默认 skip 发言
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
