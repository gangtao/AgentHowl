"""GameRunner：驱动纯引擎的编排层 —— 串行开窗、事件落库同序广播（issue #29）。

分层：runtime 只转发 intent，裁决全在 engine；本模块对事件的唯一改写点是 meta。
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.agent.profile import AgentProfiles
from app.engine.actions import Action
from app.engine.config import GameConfig
from app.engine.engine import RosterEntry, create_game, step
from app.engine.events import Event
from app.engine.observation import build_observation
from app.engine.phases import ElectionStage, Phase, expected_actors, speech_queue_pending
from app.engine.state import GameState
from app.runtime.connection import ConnectionManager
from app.runtime.defaults import default_action
from app.runtime.player_port import PlayerPort, SupportsResultFeedback
from app.store.event_store import EventStore, GameMeta, SeatName

logger = logging.getLogger(__name__)

MAX_REJECTIONS = 3  # 截止前允许的非法 intent 次数，超过即落默认行动


class LobbyError(RuntimeError):
    """大厅规则违规（重复加入、未满员取名册等）。"""


class RunnerTimeouts(BaseModel):
    model_config = ConfigDict(frozen=True)

    speech_sec: float
    action_sec: float

    @classmethod
    def from_config(cls, cfg: GameConfig) -> RunnerTimeouts:
        return cls(
            speech_sec=float(cfg.speech_timeout_sec),
            action_sec=float(cfg.action_timeout_sec),
        )


class GameLobby:
    """建局前大厅：收集座位（真人 join / bot 填充），产出 roster 与 GameMeta。"""

    def __init__(self, config: GameConfig, game_id: str) -> None:
        self._config = config
        self._game_id = game_id
        self._entries: list[RosterEntry] = []

    @property
    def is_full(self) -> bool:
        return len(self._entries) >= self._config.num_players

    def join(self, display_name: str, player_type: Literal["HUMAN", "AGENT"] = "HUMAN") -> int:
        if self.is_full:
            raise LobbyError(f"对局已满员（{self._config.num_players} 座）")
        self._entries.append(RosterEntry(display_name=display_name, player_type=player_type))
        return len(self._entries) - 1

    def fill_with_bots(self, name_for: Callable[[int], str] | None = None) -> None:
        """填满空位；name_for(seat) 给出展示名（issue #56 档案名），缺省 Bot{seat}。"""
        while not self.is_full:
            seat = len(self._entries)
            name = name_for(seat) if name_for is not None else f"Bot{seat}"
            self._entries.append(RosterEntry(display_name=name, player_type="AGENT"))

    def roster(self) -> tuple[RosterEntry, ...]:
        if not self.is_full:
            raise LobbyError(f"未满员：{len(self._entries)}/{self._config.num_players}")
        return tuple(self._entries)

    def game_meta(self, agents: AgentProfiles | None = None) -> GameMeta:
        return GameMeta(
            game_id=self._game_id,
            config=self._config,
            roster=tuple(
                SeatName(seat=i, display_name=e.display_name) for i, e in enumerate(self.roster())
            ),
            agents=dict(agents or {}),
        )


def _speech_window(state: GameState) -> bool:
    """当前窗口是否发言型（超时取 speech_timeout_sec）。"""
    if state.phase in (Phase.DAY_SPEECH, Phase.LAST_WORDS):
        return True
    return speech_queue_pending(state)


def _simultaneous_window(state: GameState) -> bool:
    """行动者「同时出手、互不可见」的窗口：上警报名 / 退水确认 / 警下投票 / 放逐投票。
    发言、夜间行动（狼队需看到彼此提议）保持串行。"""
    ph = state.phase
    if ph in (Phase.VOTE, Phase.VOTE_PK, Phase.SHERIFF_PK):
        return not speech_queue_pending(state)  # PK 发言回合串行，投票同步
    if ph == Phase.SHERIFF_ELECTION:
        return state.election_stage in (
            ElectionStage.CANDIDACY,
            ElectionStage.WITHDRAW,
            ElectionStage.VOTE,
        )
    return False


class GameRunner:
    def __init__(
        self,
        *,
        store: EventStore,
        config: GameConfig,
        game_id: str,
        roster: Sequence[RosterEntry],
        ports: Mapping[int, PlayerPort],
        connections: ConnectionManager | None = None,
        timeouts: RunnerTimeouts | None = None,
        agents: AgentProfiles | None = None,
    ) -> None:
        self._store = store
        self._config = config
        self._game_id = game_id
        self._roster = tuple(roster)
        self._ports = ports
        # 实际建成 Agent 端口的座位 → 档案（issue #64）；只写进 meta，运行时不读
        self._agents: AgentProfiles = dict(agents or {})
        self.connections = connections
        self._timeouts = timeouts or RunnerTimeouts.from_config(config)
        self._state: GameState | None = None

    @property
    def state(self) -> GameState:
        if self._state is None:
            raise RuntimeError("对局尚未开始")
        return self._state

    async def run(self) -> GameState:
        meta = GameMeta(
            game_id=self._game_id,
            config=self._config,
            roster=tuple(
                SeatName(seat=i, display_name=e.display_name) for i, e in enumerate(self._roster)
            ),
            agents=self._agents,
        )
        self._store.create_game(meta)
        res = create_game(self._config, self._game_id, roster=self._roster)
        self._state = res.state
        await self._commit(res.events)

        guard = 0
        while self.state.phase != Phase.GAME_OVER:
            actors = sorted(expected_actors(self.state))
            if not actors:
                raise RuntimeError(f"无人可行动但未终局：phase={self.state.phase}")
            if len(actors) > 1 and _simultaneous_window(self.state):
                await self._drive_window(actors)
            else:
                for seat in actors:
                    if seat not in expected_actors(self.state):
                        continue  # 前一行动已终结此窗口（如终局）
                    await self._drive_seat(seat)
            guard += 1
            if guard > 100_000:
                raise RuntimeError("对局未收敛")
        return self.state

    # ---------- 内部 ----------

    def _window_timeout(self) -> float:
        if _speech_window(self.state):
            return self._timeouts.speech_sec
        return self._timeouts.action_sec

    async def _drive_window(self, seats: list[int]) -> None:
        """同步窗口：全体行动者基于**同一状态**并行决策，再按座位序逐个应用。

        上警报名 / 退水 / 警下投票 / 放逐投票在现实里是同时举手、同时亮票；若像发言那样
        串行驱动，后行动者会看到前面人的选择——真机 LLM 局出现 9/9 全员上警、跟票成风。
        PRD §4.4「并发/异步注意」允许并行开窗。非法行动回退到串行重试路径（剩余时限内）。
        """
        missing = [s for s in seats if s not in self._ports]
        if missing:
            raise RuntimeError(f"座位 {missing} 未接入 PlayerPort（wiring 缺失，拒绝静默代打）")
        base = self.state
        window = self._window_timeout()
        deadline_ts = time.time() + window

        async def one(seat: int) -> Action:
            return await asyncio.wait_for(
                self._ports[seat].act(build_observation(base, seat), deadline_ts), timeout=window
            )

        results = await asyncio.gather(*(one(s) for s in seats), return_exceptions=True)
        for seat, res in zip(seats, results, strict=True):
            if seat not in expected_actors(self.state):
                continue  # 前一行动已终结此窗口（如竞选期自爆）
            if isinstance(res, BaseException):
                self._log_port_failure(seat, res)
                await self._apply_default(seat)
                continue
            await self._drive_seat(seat, deadline_ts=deadline_ts, first_action=res)

    def _log_port_failure(self, seat: int, exc: BaseException) -> None:
        if isinstance(exc, TimeoutError):
            logger.warning("seat=%d phase=%s 端口超时，落默认行动", seat, self.state.phase)
            return
        # 端口实现抛错（Agent 崩溃等）：对局不陪葬，落默认行动。必须留日志——
        # 否则 LLM 参数错误等会被静默记成「超时」，排查无从下手
        logger.warning(
            "seat=%d phase=%s 端口异常，落默认行动：%s: %s",
            seat,
            self.state.phase,
            type(exc).__name__,
            str(exc)[:300],
        )

    async def _drive_seat(
        self, seat: int, *, deadline_ts: float | None = None, first_action: Action | None = None
    ) -> None:
        """驱动单个座位直到提交合法行动或落默认。`first_action` 为同步窗口里已并行拿到
        的行动：先应用它，被拒才回到「重新请求端口」的串行重试路径。"""
        if seat not in self._ports:
            raise RuntimeError(f"座位 {seat} 未接入 PlayerPort（wiring 缺失，拒绝静默代打）")
        obs = build_observation(self.state, seat)
        if deadline_ts is None:
            deadline_ts = time.time() + self._window_timeout()
        rejections = 0
        pending = first_action
        while True:
            remaining = deadline_ts - time.time()
            if pending is not None:
                action, pending = pending, None
            else:
                if remaining <= 0 or rejections >= MAX_REJECTIONS:
                    logger.warning(
                        "seat=%d phase=%s %s，落默认行动",
                        seat,
                        self.state.phase,
                        f"连续 {rejections} 次非法行动"
                        if rejections >= MAX_REJECTIONS
                        else "重试中窗口耗尽",
                    )
                    await self._apply_default(seat)
                    return
                try:
                    action = await asyncio.wait_for(
                        self._ports[seat].act(obs, deadline_ts), timeout=remaining
                    )
                except Exception as exc:  # 含 TimeoutError
                    self._log_port_failure(seat, exc)
                    await self._apply_default(seat)
                    return
            res = step(self.state, action)
            if res.rejection is not None:
                port = self._ports[seat]
                if isinstance(port, SupportsResultFeedback):
                    port.notify_result(str(res.rejection), self.state.state_version, None)
                rejections += 1  # 非法 intent：截止前重试（M2.3 真人重试路径）
                logger.info(
                    "seat=%d phase=%s 行动被拒（第 %d 次）：%s %s",
                    seat,
                    self.state.phase,
                    rejections,
                    res.rejection,
                    type(action).__name__,
                )
                continue
            self._state = res.state
            # 技能装配记录（issue #60）：端口若暴露 last_skills_used，写进本次提交的首条事件 meta
            skills = tuple(getattr(self._ports[seat], "last_skills_used", ()))
            await self._commit(res.events, skills=skills)
            port = self._ports[seat]
            if isinstance(port, SupportsResultFeedback):
                event_id = f"evt_{res.events[0].seq:05d}" if res.events else None
                port.notify_result(None, self._state.state_version, event_id)
            return

    async def _apply_default(self, seat: int) -> None:
        res = step(self.state, default_action(self.state, seat))
        if res.rejection is not None:
            raise RuntimeError(f"默认行动被拒（不变量破坏）：{res.rejection} @ {self.state.phase}")
        self._state = res.state
        await self._commit(res.events, timed_out=True)

    async def _commit(
        self, events: list[Event], timed_out: bool = False, skills: Sequence[str] = ()
    ) -> None:
        """meta 充实 → 落库 → 广播，同序。runtime 对事件的唯一合法改写点。"""
        wall_ts = datetime.now(UTC).isoformat()
        enriched: list[Event] = []
        for i, e in enumerate(events):
            meta = {**e.meta, "wall_ts": wall_ts}
            if timed_out:
                meta["timeout"] = "true"
            if skills and i == 0:  # 只标首条：一次行动记一次装配（issue #60）
                meta["skills"] = ",".join(skills)
            enriched.append(e.model_copy(update={"meta": meta}))
        for e in enriched:
            self._store.append(self._game_id, e)
        if self.connections is not None:
            await self.connections.broadcast(enriched)
