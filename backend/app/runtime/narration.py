# backend/app/runtime/narration.py
"""GM 旁白（issue #110）：事件 → 口播句子模板；句子级 WAV 缓存；旁白配置。

纯函数 + 本地文件缓存；不 import 任何 LLM 代码，仅借用 tts.py 的 WAV 工具。
口播文案与 app/cli/render.py 的终端渲染互不复用（后者带 【】[GM] 装饰）。模板一律一句一个「。」结尾；座位读作「N号」。
"""

from __future__ import annotations

import hashlib
import os
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

from app.agent.profile import PRESET_SPEAKERS, VoiceSpec
from app.engine.events import (
    BadgePassedPayload,
    DeathAnnouncedPayload,
    ElectionStageChangedPayload,
    Event,
    EventType,
    GameOverPayload,
    HunterShotPayload,
    NightResolvedPayload,
    PhaseChangedPayload,
    PlayerExiledPayload,
    RoundStartedPayload,
    SheriffElectedPayload,
    SheriffVoteStartedPayload,
    VoteResultPayload,
    VoteStartedPayload,
    WolfSelfDestructPayload,
)
from app.engine.phases import ElectionStage, Phase
from app.runtime.tts import TtsError, wav_duration

DEFAULT_NARRATOR_SPEAKER = "uncle_fu"
NARRATOR_WARM_TEXT = "大家好。"

# 发言事件永远不走旁白（由发言配音负责），即使用户把它们写进白名单
SPEECH_EVENTS: frozenset[EventType] = frozenset({EventType.PLAYER_SPOKE, EventType.LAST_WORDS})

DEFAULT_NARRATION_EVENTS: frozenset[EventType] = frozenset(
    {
        EventType.ROUND_STARTED,
        EventType.PHASE_CHANGED,
        EventType.NIGHT_RESOLVED,
        EventType.DEATH_ANNOUNCED,
        EventType.ELECTION_STAGE_CHANGED,
        EventType.SHERIFF_VOTE_STARTED,
        EventType.SHERIFF_ELECTED,
        EventType.BADGE_PASSED,
        EventType.VOTE_STARTED,
        EventType.VOTE_RESULT,
        EventType.PLAYER_EXILED,
        EventType.HUNTER_SHOT,
        EventType.WOLF_SELF_DESTRUCT,
        EventType.GAME_OVER,
    }
)


def seats(xs: Iterable[int]) -> str:
    return "、".join(f"{s}号" for s in xs)


_PHASE_LINE: dict[Phase, str] = {
    Phase.NIGHT_GUARD: "守卫请睁眼。",
    Phase.NIGHT_WEREWOLF: "狼人请睁眼。",
    Phase.NIGHT_WITCH: "女巫请睁眼。",
    Phase.NIGHT_SEER: "预言家请睁眼。",
    Phase.NIGHT_HUNTER_CONFIRM: "猎人请确认状态。",
    Phase.SHERIFF_ELECTION: "天亮了，进入警长竞选。",
    Phase.SHERIFF_PK: "警长竞选进入PK。",
    Phase.DEATH_ANNOUNCE: "天亮了。",
    Phase.LAST_WORDS: "请发表遗言。",
    Phase.VOTE: "进入放逐投票。",
    Phase.HUNTER_SHOOT: "猎人请开枪。",
    Phase.IDIOT_FLIP: "白痴翻牌。",
}
# 过渡阶段不播（终局由 GAME_OVER 播）
_SILENT_PHASES: frozenset[Phase] = frozenset(
    {Phase.EXILE, Phase.WIN_CHECK, Phase.LOBBY, Phase.ROLE_ASSIGN, Phase.GAME_OVER}
)

_STAGE_LINE: dict[ElectionStage, str] = {
    ElectionStage.CANDIDACY: "上警报名开始。",
    ElectionStage.SPEECH: "上警发言。",
    ElectionStage.WITHDRAW: "退水确认。",
    ElectionStage.VOTE: "警下投票开始。",
    ElectionStage.DIRECTION: "请警长决定发言方向。",
    ElectionStage.ANNOUNCE: "公布竞选结果。",
    ElectionStage.NONE: "竞选环节结束。",
}


def _phase_changed(p: PhaseChangedPayload) -> list[str]:
    if p.to == Phase.DAY_SPEECH:
        return [
            f"进入发言环节，顺序：{seats(p.speech_order)}。" if p.speech_order else "进入发言环节。"
        ]
    if p.to == Phase.VOTE_PK:
        return [f"平票PK，发言顺序：{seats(p.speech_order)}。" if p.speech_order else "平票PK。"]
    if p.to in _SILENT_PHASES:
        return []
    if p.to in _PHASE_LINE:
        return [_PHASE_LINE[p.to]]
    raise KeyError(f"Phase 缺少旁白模板：{p.to}")


def _election_stage(p: ElectionStageChangedPayload) -> list[str]:
    if p.stage == ElectionStage.SPEECH and p.speech_order:
        return [f"上警发言，顺序：{seats(p.speech_order)}。"]
    if p.stage in _STAGE_LINE:
        return [_STAGE_LINE[p.stage]]
    raise KeyError(f"ElectionStage 缺少旁白模板：{p.stage}")


def _render(event: Event) -> list[str]:  # noqa: PLR0911
    p = event.payload
    t = event.type
    if t == EventType.ROUND_STARTED and isinstance(p, RoundStartedPayload):
        return [f"第{p.round}轮，天黑请闭眼。"]
    if t == EventType.PHASE_CHANGED and isinstance(p, PhaseChangedPayload):
        return _phase_changed(p)
    if t == EventType.NIGHT_RESOLVED and isinstance(p, NightResolvedPayload):
        return [f"本夜结算，出局：{seats(p.deaths)}。" if p.deaths else "本夜结算，平安夜。"]
    if t == EventType.DEATH_ANNOUNCED and isinstance(p, DeathAnnouncedPayload):
        return [f"昨夜出局的是{seats(p.seats)}。" if p.seats else "昨夜是平安夜，无人出局。"]
    if t == EventType.ELECTION_STAGE_CHANGED and isinstance(p, ElectionStageChangedPayload):
        return _election_stage(p)
    if t == EventType.SHERIFF_VOTE_STARTED and isinstance(p, SheriffVoteStartedPayload):
        return [f"警长开票，候选人：{seats(p.candidates)}。"]
    if t == EventType.SHERIFF_ELECTED and isinstance(p, SheriffElectedPayload):
        return [f"{p.seat}号当选警长。"]
    if t == EventType.BADGE_PASSED and isinstance(p, BadgePassedPayload):
        if p.to_seat is not None:
            return [f"{p.from_seat}号把警徽移交给{p.to_seat}号。"]
        return [f"{p.from_seat}号撕毁警徽。"]
    if t == EventType.VOTE_STARTED and isinstance(p, VoteStartedPayload):
        return ["PK投票开始。" if p.tie_round > 0 else "投票开始。"]
    if t == EventType.VOTE_RESULT and isinstance(p, VoteResultPayload):
        return [
            f"{p.exiled}号得票最高。" if p.exiled is not None else f"平票：{seats(p.tie_seats)}。"
        ]
    if t == EventType.PLAYER_EXILED and isinstance(p, PlayerExiledPayload):
        return [f"{p.seat}号被放逐出局。" if p.seat is not None else "本轮无人出局。"]
    if t == EventType.HUNTER_SHOT and isinstance(p, HunterShotPayload):
        if p.victim is not None:
            return [f"{p.shooter}号猎人开枪，带走{p.victim}号。"]
        return [f"{p.shooter}号猎人没有开枪。"]
    if t == EventType.WOLF_SELF_DESTRUCT and isinstance(p, WolfSelfDestructPayload):
        return [f"{p.seat}号狼人自爆。"]
    if t == EventType.GAME_OVER and isinstance(p, GameOverPayload):
        who = {"GOOD": "好人阵营获胜", "WOLF": "狼人阵营获胜"}.get(p.winner or "", "平局")
        return [f"游戏结束，{who}。"]
    raise KeyError(f"事件缺少旁白模板：{t}")


# 有模板的事件类型；白名单校验只认这个集合（Task 2 的 NarrationConfig 用）
TEMPLATED_EVENTS: frozenset[EventType] = frozenset(
    {
        EventType.ROUND_STARTED,
        EventType.PHASE_CHANGED,
        EventType.NIGHT_RESOLVED,
        EventType.DEATH_ANNOUNCED,
        EventType.ELECTION_STAGE_CHANGED,
        EventType.SHERIFF_VOTE_STARTED,
        EventType.SHERIFF_ELECTED,
        EventType.BADGE_PASSED,
        EventType.VOTE_STARTED,
        EventType.VOTE_RESULT,
        EventType.PLAYER_EXILED,
        EventType.HUNTER_SHOT,
        EventType.WOLF_SELF_DESTRUCT,
        EventType.GAME_OVER,
    }
)


def narrate(event: Event, events: frozenset[EventType]) -> list[str]:
    """白名单内 → 按模板渲染（可能为空，如过渡阶段）；白名单外 / 发言事件 → []。"""
    if event.type in SPEECH_EVENTS or event.type not in events:
        return []
    return _render(event)


@dataclass(frozen=True)
class NarrationConfig:
    """旁白配置：声线 + 事件白名单 + 缓存目录。构造即校验（fail-loud）。"""

    speaker: str
    events: frozenset[EventType]
    cache_dir: Path

    def __post_init__(self) -> None:
        if self.speaker not in PRESET_SPEAKERS:
            raise ValueError(f"旁白声线必须是预置 speaker {PRESET_SPEAKERS}：{self.speaker!r}")
        missing = sorted(t.value for t in self.events - TEMPLATED_EVENTS - SPEECH_EVENTS)
        if missing:
            raise ValueError(f"旁白白名单里的事件没有模板：{missing}")

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None, *, data_dir: Path) -> NarrationConfig:
        e = os.environ if env is None else env
        speaker = (e.get("AGENTHOWL_NARRATOR_VOICE") or DEFAULT_NARRATOR_SPEAKER).strip()
        raw = (e.get("AGENTHOWL_NARRATION_EVENTS") or "").strip()
        if raw:
            names = [x.strip() for x in raw.split(",") if x.strip()]
            try:
                events = frozenset(EventType(n) for n in names)
            except ValueError as exc:
                raise ValueError(f"AGENTHOWL_NARRATION_EVENTS 含未知事件：{exc}") from exc
        else:
            events = DEFAULT_NARRATION_EVENTS
        cache_dir = Path(e.get("AGENTHOWL_NARRATION_DIR") or (data_dir / "narration"))
        return cls(speaker=speaker, events=events, cache_dir=cache_dir)

    @property
    def voice(self) -> VoiceSpec:
        return VoiceSpec(mode="preset", speaker=self.speaker)


class NarrationCache:
    """句子级 WAV 缓存：key = sha256(speaker + 句子)[:16]；所有对局共用。"""

    def __init__(self, cache_dir: Path) -> None:
        self._dir = cache_dir

    @staticmethod
    def key(speaker: str, text: str) -> str:
        return hashlib.sha256(f"{speaker}\n{text}".encode()).hexdigest()[:16]

    def _path(self, speaker: str, text: str) -> Path:
        return self._dir / f"{self.key(speaker, text)}.wav"

    def get(self, speaker: str, text: str) -> bytes | None:
        """未命中 / 文件不是合法 WAV → None（坏文件视为未命中，由 put 覆盖）。"""
        p = self._path(speaker, text)
        try:
            data = p.read_bytes()
            wav_duration(data)
        except (OSError, TtsError):
            return None
        return data

    def put(self, speaker: str, text: str, wav: bytes) -> Path:
        p = self._path(speaker, text)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".wav.tmp")
        tmp.write_bytes(wav)
        os.replace(tmp, p)
        return p
