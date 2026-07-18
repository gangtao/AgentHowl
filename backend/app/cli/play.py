"""CLI 观战/对局器（issue #44）：python -m app.cli.play。

无 --seat=看局；--seat N=交互玩局。进程内 async 跑 runtime，纯客户端。
"""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import Awaitable, Callable

from app.cli.render import render_event
from app.engine.config import GameConfig, build_preset
from app.engine.engine import RosterEntry
from app.engine.events import Event
from app.engine.observation import Viewer
from app.engine.state import GameState
from app.runtime.connection import ConnectionManager
from app.runtime.game_runner import GameRunner, RunnerTimeouts
from app.runtime.player_port import BotPlayerPort, HumanPlayerPort, PlayerPort

ReadLine = Callable[[str], Awaitable[str]]

# 宽松默认超时，便于人类从容操作
_CLI_TIMEOUTS = RunnerTimeouts(speech_sec=120.0, action_sec=120.0)
# 思考模式：推理模型单次决策可达数分钟，给足窗口
_THINK_TIMEOUTS = RunnerTimeouts(speech_sec=600.0, action_sec=600.0)


async def default_read_line(prompt: str) -> str:
    """默认行读取器：线程内阻塞 input，不卡事件循环。

    局限：input() 阻塞在独立线程，asyncio 取消无法中断它。若玩家在 `> ` 提示处
    发呆到本回合超时（默认行动顶替）且对局随即终局，该线程会滞留到解释器退出时
    才被 join —— 表现为进程退出前需按一次回车。交互式 CLI 的固有取舍，非 run_play
    的挂死缺陷（对局逻辑已正常收尾）。
    """
    return await asyncio.to_thread(input, prompt)


def _parse_view(view: str) -> Viewer:
    if view == "gm":
        return "GM"
    if view == "spectator":
        return "SPECTATOR"
    if view.startswith("seat:"):
        return int(view.split(":", 1)[1])
    raise ValueError(f"未知视角：{view}（用 gm|spectator|seat:N）")


def _wire_game(
    config: GameConfig,
    *,
    human_seat: int | None = None,
    ai_model: str | None = None,
    thinking: bool = False,
) -> tuple[GameRunner, ConnectionManager, dict[int, PlayerPort]]:
    """装配 store/roster/ports/conns/runner（不订阅、不 run）。"""
    from app.store.event_store import InMemoryEventStore

    n = config.num_players
    holder: dict[str, GameRunner] = {}

    def state_of() -> GameState:
        return holder["r"].state  # run 前不会被调用（订阅先于 run，bot.act 在 run 内）

    ports: dict[int, PlayerPort] = {}
    for seat in range(n):
        if seat == human_seat:
            ports[seat] = HumanPlayerPort()
        elif ai_model is not None:
            from app.agent.agent_player import build_agent_port

            ports[seat] = build_agent_port(seat, config, ai_model, None, thinking=thinking)
        else:
            ports[seat] = BotPlayerPort(state_provider=state_of)

    roster = [
        RosterEntry(display_name=f"P{i}", player_type=("HUMAN" if i == human_seat else "AGENT"))
        for i in range(n)
    ]
    conns = ConnectionManager(state_provider=state_of)
    runner = GameRunner(
        store=InMemoryEventStore(),
        config=config,
        game_id="cli",
        roster=roster,
        ports=ports,
        connections=conns,
        # 思考模式单次决策可达数分钟，放宽窗口避免被超时代打
        timeouts=_THINK_TIMEOUTS if thinking else _CLI_TIMEOUTS,
    )
    holder["r"] = runner
    return runner, conns, ports


async def run_watch(
    config: GameConfig,
    *,
    view: Viewer,
    delay: float,
    step: bool,
    ai_model: str | None = None,
    thinking: bool = False,
    read_line: ReadLine = default_read_line,
) -> GameState:
    """看局：打印型订阅者按 view 叙述，delay/step 限速，跑到 GAME_OVER。

    ai_model 设置时全座由 LLM Agent 扮演（自对局）；否则内置随机 bot。
    thinking=True 时 LLM Agent 开启思考（更强推理但明显更慢）。
    """
    runner, conns, _ = _wire_game(config, ai_model=ai_model, thinking=thinking)

    async def on_events(events: list[Event]) -> None:
        for e in events:  # 已按 view 过滤
            line = render_event(e)
            if line:
                print(line)
            if step:
                await read_line("")  # 回车推进
            elif delay > 0:
                await asyncio.sleep(delay)

    conns.subscribe(view, on_events)  # 必须先于 run
    return await runner.run()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="app.cli.play", description="AgentHowl 终端观战/对局器")
    parser.add_argument("--seat", type=int, default=None, help="设=真人玩该座；缺=看局")
    parser.add_argument("--preset", default="std_9_kill_side")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--view", default="gm", help="看局视角 gm|spectator|seat:N")
    parser.add_argument("--delay", type=float, default=0.6, help="看局逐事件延时（秒）")
    parser.add_argument("--step", action="store_true", help="看局逐步（回车推进）")
    parser.add_argument("--ai-model", default=None, help="LLM 自对局模型（如 ollama/llama3.1）")
    parser.add_argument(
        "--thinking",
        action="store_true",
        help="开启推理模型思考（更强推理，但单次决策可达数分钟）",
    )
    parser.add_argument("--no-color", action="store_true")
    args = parser.parse_args(argv)

    config = build_preset(args.preset).model_copy(update={"seed": args.seed})
    if args.no_color:
        import os

        os.environ["NO_COLOR"] = "1"

    if args.seat is None:
        asyncio.run(
            run_watch(
                config,
                view=_parse_view(args.view),
                delay=args.delay,
                step=args.step,
                ai_model=args.ai_model,
                thinking=args.thinking,
            )
        )
    else:
        from app.cli.play_human import run_play

        asyncio.run(
            run_play(config, seat=args.seat, ai_model=args.ai_model, thinking=args.thinking)
        )


if __name__ == "__main__":
    main()
