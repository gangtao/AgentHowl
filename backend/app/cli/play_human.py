"""CLI 玩局（issue #44）：真人座交互——mini-syntax 解析 + turn-loop。

纯客户端：只经 observation 与端口提交，合法性裁决全在引擎。
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Callable

from app.cli.play import ReadLine, _wire_game, default_read_line
from app.cli.render import color, render_event, render_observation, render_tools
from app.engine.config import GameConfig
from app.engine.events import Event
from app.engine.observation import PlayerObservation
from app.engine.state import GameState
from app.runtime.game_runner import GameRunner
from app.runtime.player_port import HumanPlayerPort, NotYourTurnError
from app.schemas.actions import ToolCall, ToolCallError, available_tools_for, parse_tool_call

_HELP = (
    "命令：speak <话>｜vote <座>｜vote abstain｜night <类型> [座]"
    "（kill/check/save/poison/guard/shoot/skip）｜"
    "sheriff <类型> [座|left/right]｜self_destruct｜help｜state｜speeches"
)


class CliInputError(ValueError):
    """无法解析的输入行（提示后重读，不裁决合法性）。"""


def parse_line(line: str, obs: PlayerObservation) -> ToolCall:
    """mini-syntax → ToolCall。合法性（阶段/目标存活等）交引擎裁决。"""
    parts = line.strip().split()
    if not parts:
        raise CliInputError("空输入")
    cmd, args = parts[0], parts[1:]

    if cmd == "speak":
        return ToolCall(tool="speak", arguments={"content": " ".join(args)})
    if cmd == "self_destruct":
        return ToolCall(tool="self_destruct", arguments={})
    if cmd == "vote":
        if args and args[0] == "abstain":
            return ToolCall(tool="vote", arguments={"abstain": True})
        if not args:
            raise CliInputError("vote 需要座位号或 abstain")
        return ToolCall(tool="vote", arguments={"target_seat": _int(args[0])})
    if cmd == "night":
        if not args:
            raise CliInputError("night 需要行动类型")
        payload: dict[str, object] = {"action_type": args[0]}
        if len(args) > 1:
            payload["target_seat"] = _int(args[1])
        return ToolCall(tool="night_action", arguments=payload)
    if cmd == "sheriff":
        if not args:
            raise CliInputError("sheriff 需要行动类型")
        payload = {"action_type": args[0]}
        if len(args) > 1:
            if args[1] in ("left", "right"):
                payload["direction"] = args[1].upper()
            else:
                payload["target_seat"] = _int(args[1])
        return ToolCall(tool="sheriff_action", arguments=payload)
    raise CliInputError(f"未知命令：{cmd}（help 查看用法）")


def _int(s: str) -> int:
    try:
        return int(s)
    except ValueError as exc:
        raise CliInputError(f"需要座位号，收到：{s}") from exc


async def run_play(
    config: GameConfig,
    *,
    seat: int,
    ai_model: str | None = None,
    thinking: bool = False,
    read_line: ReadLine = default_read_line,
    on_wired: Callable[[GameRunner], None] | None = None,
) -> GameState:
    """真人座玩局：并发 runner + turn-loop，跑到 GAME_OVER。"""
    runner, conns, ports = _wire_game(config, human_seat=seat, ai_model=ai_model, thinking=thinking)
    port = ports[seat]
    assert isinstance(port, HumanPlayerPort)
    if on_wired is not None:
        on_wired(runner)

    async def narrate(events: list[Event]) -> None:
        for e in events:
            line = render_event(e)
            if line:
                print(line)

    conns.subscribe(seat, narrate)  # 先于 run

    done = asyncio.Event()

    async def turn_loop() -> None:
        while not done.is_set():
            prompt = await port.wait_armed(0.25)
            if prompt is None:
                continue
            obs = prompt.observation
            print(color(f"\n—— 轮到你（{obs.my_seat}号）——", "cyan"))
            print(render_observation(obs))
            print(render_tools(available_tools_for(obs)))
            while True:  # 本窗口内重读，直到提交（成功→下一轮；被拒→回外层重开窗）
                line = await read_line("> ")
                parts = line.strip().split()
                if not parts:
                    continue
                if parts[0] == "help":
                    print(_HELP)
                    continue
                if parts[0] == "state":
                    print(render_observation(obs))
                    continue
                if parts[0] == "speeches":
                    print("（发言见上方叙述）")
                    continue
                try:
                    call = parse_line(line, obs)
                    action = parse_tool_call(call, actor_seat=seat)
                except (CliInputError, ToolCallError) as exc:
                    print(color(f"⚠ {exc}", "yellow"))
                    continue
                try:
                    outcome = await port.submit_and_wait(action)
                except NotYourTurnError:
                    print(color("窗口已关闭（可能超时代打）", "grey"))
                    break
                if outcome.ok:
                    print(color("✓ 已提交", "green"))
                    break
                print(color(f"✗ 被拒：{outcome.rejected_reason}，请重试", "yellow"))
                break  # 重开窗（race-safe：回外层 wait_armed 捕获重开的窗口）

    loop_task = asyncio.create_task(turn_loop())
    try:
        state = await runner.run()
    finally:
        done.set()
        loop_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await loop_task

    winner = {"GOOD": "好人胜", "WOLF": "狼人胜"}.get(state.winner or "", "平局")
    print(color(f"\n═══════ 游戏结束：{winner} ═══════", "bold"))
    return state
