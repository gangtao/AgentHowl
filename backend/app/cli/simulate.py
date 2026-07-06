"""CLI：uv run python -m app.cli.simulate --preset <name> --seed <n> [--games N] [--verbose]"""

from __future__ import annotations

import argparse

from app.cli.bot import run_game
from app.engine.config import Faction, RoleType, build_preset
from app.engine.events import reduce_all
from app.engine.phases import Phase
from app.engine.state import GameState, Player


def _blank(final: GameState) -> GameState:
    players = tuple(
        Player(
            seat=p.seat,
            display_name=p.display_name,
            role=RoleType.VILLAGER,
            faction=Faction.GOOD,
        )
        for p in final.players
    )
    return GameState(
        game_id=final.game_id, config=final.config, phase=Phase.LOBBY, round=0, players=players
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="AgentHowl 随机 bot 对局模拟")
    parser.add_argument("--preset", default="std_9_kill_side")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--games", type=int, default=1)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    wins: dict[str, int] = {}
    for i in range(args.games):
        seed = args.seed + i
        config = build_preset(args.preset).model_copy(update={"seed": seed})
        final, events = run_game(config, game_id=f"g{seed}")
        assert final.phase == Phase.GAME_OVER, f"seed {seed} 未终局"
        replayed = reduce_all(_blank(final), events)
        assert replayed.winner == final.winner, f"seed {seed} 回放与实时不一致"
        result = final.winner or "DRAW"
        wins[result] = wins.get(result, 0) + 1
        if args.verbose:
            print(f"seed={seed} winner={result} events={len(events)} rounds={final.round}")

    print(f"跑完 {args.games} 局：{wins}")


if __name__ == "__main__":
    main()
