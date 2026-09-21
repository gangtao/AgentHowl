"""离线指标分析器（issue #60）：逐事件回放归因，按档案指纹汇总。

analyze_game 用引擎 reduce 维护回放状态，只为知道「当前轮次 / 在世狼 / 投票轮」——引擎零改动。
比率 = 分子和 / 分母和；分母 0 → None（报告显示 N/A）。
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import ClassVar

from pydantic import BaseModel, Field

from app.agent.profile import AgentProfile
from app.engine.config import Faction, RoleType, faction_of
from app.engine.events import (
    Event,
    EventType,
    GameOverPayload,
    HunterShotPayload,
    NightResolvedPayload,
    PlayerExiledPayload,
    PlayerSpokePayload,
    RolesAssignedPayload,
    SheriffCandidacyPayload,
    SheriffElectedPayload,
    SheriffWithdrewPayload,
    VoteCastPayload,
    VoteStartedPayload,
    WolfKillDecidedPayload,
    WolfKillProposedPayload,
    WolfKillRevotePayload,
    WolfSelfDestructPayload,
    reduce,
)
from app.eval.fingerprint import profile_fingerprint, profile_summary
from app.store.event_store import GameMeta, initial_state

RANDOM_BOT_LABEL = "随机 bot"


class SeatStats(BaseModel):
    """一个座位一局的计数（全部为可加计数，汇总时逐字段求和）。"""

    wins: int = 0
    alive_at_end: int = 0
    rounds_alive: int = 0
    exiled: int = 0
    night_killed: int = 0
    speeches: int = 0
    speech_chars: int = 0
    claims: int = 0
    badge_flows: int = 0
    candidacies: int = 0
    elected: int = 0
    withdrew: int = 0
    votes: int = 0
    abstains: int = 0
    pk_votes_eligible: int = 0
    vote_changes: int = 0
    wolf_nights: int = 0
    proposals: int = 0
    no_kill_proposals: int = 0
    revote_nights: int = 0
    decided_no_kill: int = 0
    skills_assembled: int = 0
    skill_counts: dict[str, int] = Field(default_factory=dict)

    def add(self, other: SeatStats) -> None:
        for name in type(self).model_fields:
            if name == "skill_counts":
                for k, v in other.skill_counts.items():
                    self.skill_counts[k] = self.skill_counts.get(k, 0) + v
            else:
                setattr(self, name, getattr(self, name) + getattr(other, name))


class GameAnalysis(BaseModel):
    game_id: str
    winner: str | None
    rounds: int
    sheriff_enabled: bool
    roles: dict[int, RoleType]
    fingerprints: dict[int, str | None]
    seats: dict[int, SeatStats]


def _die(seats: dict[int, SeatStats], dead: set[int], seat: int, round_no: int) -> None:
    if seat not in dead:
        dead.add(seat)
        seats[seat].rounds_alive = round_no


def analyze_game(meta: GameMeta, events: Sequence[Event]) -> GameAnalysis:  # noqa: PLR0912, PLR0915
    state = initial_state(meta)
    n = len(meta.roster)
    seats = {s: SeatStats() for s in range(n)}
    roles: dict[int, RoleType] = {}
    dead: set[int] = set()
    first_targets: dict[int, int | None] = {}  # 本轮首轮投票目标（VOTE_STARTED tie_round=0 重置）
    pk_candidates: tuple[int, ...] | None = None  # 非 None = 正处于 PK 轮
    night_counted = revote_counted = decided_counted = False
    winner: str | None = None
    for e in events:
        p = e.payload
        t = e.type
        # 归因用「应用前」的状态：当前轮次、在世狼
        alive_wolves = [pl.seat for pl in state.players if pl.alive and pl.faction == Faction.WOLF]
        if t is EventType.ROLES_ASSIGNED and isinstance(p, RolesAssignedPayload):
            roles = dict(p.assignments)
        elif t is EventType.ROUND_STARTED:
            night_counted = revote_counted = decided_counted = False
        elif t is EventType.WOLF_KILL_PROPOSED and isinstance(p, WolfKillProposedPayload):
            if not night_counted:
                for w in alive_wolves:
                    seats[w].wolf_nights += 1
                night_counted = True
            st = seats[p.wolf_seat]
            st.proposals += 1
            if p.target is None:
                st.no_kill_proposals += 1
        elif t is EventType.WOLF_KILL_REVOTE and isinstance(p, WolfKillRevotePayload):
            if not revote_counted and night_counted:
                for w in alive_wolves:
                    seats[w].revote_nights += 1
                revote_counted = True
        elif t is EventType.WOLF_KILL_DECIDED and isinstance(p, WolfKillDecidedPayload):
            if p.target is None and not decided_counted and night_counted:
                for w in alive_wolves:
                    seats[w].decided_no_kill += 1
                decided_counted = True
        elif t is EventType.NIGHT_RESOLVED and isinstance(p, NightResolvedPayload):
            for s in p.deaths:
                _die(seats, dead, s, state.round)
                seats[s].night_killed += 1
        elif t is EventType.PLAYER_EXILED and isinstance(p, PlayerExiledPayload):
            if p.seat is not None:
                _die(seats, dead, p.seat, state.round)
                seats[p.seat].exiled += 1
        elif t is EventType.HUNTER_SHOT and isinstance(p, HunterShotPayload):
            if p.victim is not None:
                _die(seats, dead, p.victim, state.round)
        elif t is EventType.WOLF_SELF_DESTRUCT and isinstance(p, WolfSelfDestructPayload):
            _die(seats, dead, p.seat, state.round)
        elif (
            t is EventType.PLAYER_SPOKE
            and isinstance(p, PlayerSpokePayload)
            and e.actor_seat is not None
        ):
            st = seats[e.actor_seat]
            st.speeches += 1
            st.speech_chars += len(p.content)
            if p.claim_role is not None:
                st.claims += 1
            if p.badge_flow:
                st.badge_flows += 1
        elif t is EventType.SHERIFF_CANDIDACY and isinstance(p, SheriffCandidacyPayload):
            if p.running:
                seats[p.seat].candidacies += 1
        elif t is EventType.SHERIFF_ELECTED and isinstance(p, SheriffElectedPayload):
            seats[p.seat].elected += 1
        elif t is EventType.SHERIFF_WITHDREW and isinstance(p, SheriffWithdrewPayload):
            seats[p.seat].withdrew += 1
        elif t is EventType.VOTE_STARTED and isinstance(p, VoteStartedPayload):
            if p.tie_round == 0:
                first_targets = {}
                pk_candidates = None
            else:
                pk_candidates = tuple(p.candidates)
        elif t is EventType.VOTE_CAST and isinstance(p, VoteCastPayload):
            voter, target = p.voter, p.target
            st = seats[voter]
            st.votes += 1
            if target is None:
                st.abstains += 1
            if pk_candidates is None:
                first_targets[voter] = target
            else:
                first = first_targets.get(voter)
                if first is not None and first in pk_candidates:
                    st.pk_votes_eligible += 1
                    if target != first:
                        st.vote_changes += 1
        elif t is EventType.GAME_OVER and isinstance(p, GameOverPayload):
            winner = p.winner
        skills = e.meta.get("skills")
        if skills and e.actor_seat is not None:
            st = seats[e.actor_seat]
            st.skills_assembled += 1
            for raw_name in skills.split(","):
                name = raw_name.strip()
                if name:
                    st.skill_counts[name] = st.skill_counts.get(name, 0) + 1
        state = reduce(state, e)
    for s, st in seats.items():
        if s not in dead:
            st.alive_at_end = 1
            st.rounds_alive = state.round
        role = roles.get(s)
        if role is not None and winner is not None and faction_of(role) == winner:
            st.wins = 1
    fps = {
        s: (profile_fingerprint(meta.agents[str(s)]) if str(s) in meta.agents else None)
        for s in range(n)
    }
    return GameAnalysis(
        game_id=meta.game_id,
        winner=winner,
        rounds=state.round,
        sheriff_enabled=meta.config.sheriff.enabled,
        roles=roles,
        fingerprints=fps,
        seats=seats,
    )


class RoleStats(BaseModel):
    games: int = 0
    wins: int = 0


def _rate(num: int, den: int) -> float | None:
    return num / den if den else None


class ProfileStats(BaseModel):
    """一个档案（指纹）跨局汇总；比率为属性，分母 0 → None。"""

    RATE_FIELDS: ClassVar[tuple[str, ...]] = (
        "win_rate",
        "wolf_win_rate",
        "good_win_rate",
        "survive_rate",
        "avg_rounds_alive",
        "exiled_rate",
        "night_killed_rate",
        "avg_speech_chars",
        "claim_rate",
        "badge_flow_rate",
        "candidacy_rate",
        "abstain_rate",
        "vote_change_rate",
        "no_kill_proposal_rate",
        "revote_night_rate",
        "decided_no_kill_rate",
    )

    summary: str = ""
    games: int = 0
    wins: int = 0
    wolf_games: int = 0
    wolf_wins: int = 0
    good_games: int = 0
    good_wins: int = 0
    sheriff_games: int = 0
    by_role: dict[RoleType, RoleStats] = Field(default_factory=dict)
    totals: SeatStats = Field(default_factory=SeatStats)

    @property
    def win_rate(self) -> float | None:
        return _rate(self.wins, self.games)

    @property
    def wolf_win_rate(self) -> float | None:
        return _rate(self.wolf_wins, self.wolf_games)

    @property
    def good_win_rate(self) -> float | None:
        return _rate(self.good_wins, self.good_games)

    @property
    def survive_rate(self) -> float | None:
        return _rate(self.totals.alive_at_end, self.games)

    @property
    def avg_rounds_alive(self) -> float | None:
        return _rate(self.totals.rounds_alive, self.games)

    @property
    def exiled_rate(self) -> float | None:
        return _rate(self.totals.exiled, self.games)

    @property
    def night_killed_rate(self) -> float | None:
        return _rate(self.totals.night_killed, self.games)

    @property
    def avg_speech_chars(self) -> float | None:
        return _rate(self.totals.speech_chars, self.totals.speeches)

    @property
    def claim_rate(self) -> float | None:
        return _rate(self.totals.claims, self.totals.speeches)

    @property
    def badge_flow_rate(self) -> float | None:
        return _rate(self.totals.badge_flows, self.totals.speeches)

    @property
    def candidacy_rate(self) -> float | None:
        return _rate(self.totals.candidacies, self.sheriff_games)

    @property
    def abstain_rate(self) -> float | None:
        return _rate(self.totals.abstains, self.totals.votes)

    @property
    def vote_change_rate(self) -> float | None:
        return _rate(self.totals.vote_changes, self.totals.pk_votes_eligible)

    @property
    def no_kill_proposal_rate(self) -> float | None:
        return _rate(self.totals.no_kill_proposals, self.totals.proposals)

    @property
    def revote_night_rate(self) -> float | None:
        return _rate(self.totals.revote_nights, self.totals.wolf_nights)

    @property
    def decided_no_kill_rate(self) -> float | None:
        return _rate(self.totals.decided_no_kill, self.totals.wolf_nights)

    def rates(self) -> dict[str, float | None]:
        return {name: getattr(self, name) for name in self.RATE_FIELDS}


def collect_profiles(metas: Iterable[GameMeta]) -> dict[str, AgentProfile]:
    """各局 meta.agents 里出现过的档案，按指纹去重（供 aggregate 填 summary）。"""
    out: dict[str, AgentProfile] = {}
    for m in metas:
        for p in m.agents.values():
            out.setdefault(profile_fingerprint(p), p)
    return out


def aggregate(
    analyses: Iterable[GameAnalysis], profiles: Mapping[str, AgentProfile] | None = None
) -> dict[str | None, ProfileStats]:
    profiles = profiles or {}
    out: dict[str | None, ProfileStats] = {}
    for a in analyses:
        for seat, st in a.seats.items():
            fp = a.fingerprints.get(seat)
            if fp not in out:
                if fp is None:
                    summary = RANDOM_BOT_LABEL
                else:
                    prof = profiles.get(fp)
                    summary = profile_summary(prof) if prof is not None else fp
                out[fp] = ProfileStats(summary=summary)
            ps = out[fp]
            ps.games += 1
            ps.wins += st.wins
            role = a.roles.get(seat)
            if role is not None:
                if faction_of(role) == Faction.WOLF:
                    ps.wolf_games += 1
                    ps.wolf_wins += st.wins
                else:
                    ps.good_games += 1
                    ps.good_wins += st.wins
                rs = ps.by_role.setdefault(role, RoleStats())
                rs.games += 1
                rs.wins += st.wins
            if a.sheriff_enabled:
                ps.sheriff_games += 1
            ps.totals.add(st)
    return out


def diff(a: ProfileStats, b: ProfileStats) -> dict[str, float | None]:
    """a − b 的全部比率；任一为 None → None。"""
    ra, rb = a.rates(), b.rates()
    out: dict[str, float | None] = {}
    for k in ProfileStats.RATE_FIELDS:
        x, y = ra[k], rb[k]
        out[k] = x - y if x is not None and y is not None else None
    return out
