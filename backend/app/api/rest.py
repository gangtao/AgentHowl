"""REST 端点（PRD §5.2）。零裁决：鉴权/序列化/转发（issue #30）。"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import ValidationError

from app.agent.profile import AgentProfiles, profile_for
from app.api.auth import can_access, current_user, require_user
from app.api.deps import (
    TokenInfo,
    TokenRegistry,
    get_games,
    get_tokens,
    require_kind,
    require_token,
)
from app.api.providers import visible_providers
from app.api.views import event_json_for_viewer
from app.engine.config import apply_override, build_preset
from app.engine.events import Event, EventType, Visibility
from app.engine.observation import build_observation, visible_events
from app.engine.phases import Phase
from app.engine.state import GameState
from app.runtime.agent_library import AgentLibraryStore
from app.runtime.history import GameSummary, is_finished, list_history
from app.runtime.player_port import ACCEPT_WAIT_SEC, TurnPrompt
from app.runtime.registry import GameHandle, GameRegistry
from app.runtime.secret import share_token, verify_share_token
from app.runtime.speech_audio import SpeechAudioSink
from app.runtime.tts import TtsClient, TtsStatus
from app.runtime.users import User, UserStore
from app.schemas.actions import (
    ActionResponse,
    ToolCall,
    ToolCallError,
    available_tools_for,
    parse_tool_call,
)
from app.schemas.games import (
    CreateGameRequest,
    CreateGameResponse,
    JoinRequest,
    JoinResponse,
    SpectatorView,
    SpeechItem,
    StartRequest,
    StartResponse,
)
from app.store.event_store import (
    GameNotFoundError,
    InvalidGameIdError,
    StoreError,
    event_to_json,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/games", tags=["games"])
tts_router = APIRouter(prefix="/tts", tags=["tts"])
_bearer = HTTPBearer(auto_error=False)


def _check_agent_ids(req: CreateGameRequest, lib: AgentLibraryStore, user: User) -> None:
    """agent_ids（issue #123）：键须在 agents 里（有 id 必有档案）；id 须是当前用户可见的档案
    （不存在与无权一律「档案不存在」，不泄露存在性）。不校验内联 profile 与库里是否一致。"""
    for key, agent_id in req.agent_ids.items():
        if key not in req.agents:
            raise ToolCallError(f"agent_ids 非法：座位 {key} 没有对应的 agents 档案")
        stored = lib.get(agent_id)
        if stored is None or not can_access(user, stored.owner_id):
            raise ToolCallError(f"agent_ids 非法：档案不存在：{agent_id}")


@router.post("")
async def create_game_endpoint(
    req: CreateGameRequest,
    request: Request,
    user: User = Depends(require_user),
    games: GameRegistry = Depends(get_games),
    tokens: TokenRegistry = Depends(get_tokens),
) -> CreateGameResponse:
    try:
        # issue #39：深合并 + 未知键 400（之前 model_copy 静默丢弃笔误键、嵌套子规则被整体重置）
        config = apply_override(build_preset(req.preset), req.config_override)
    except (KeyError, ValueError, ValidationError) as exc:
        raise ToolCallError(f"preset/config_override 非法：{exc}") from exc
    if req.narration and not req.voice:
        raise HTTPException(status_code=400, detail="旁白需要先开启语音播报")
    # 发言配音（issue #103）：开局前探测，不可用则 400，不悄悄降级
    tts: TtsClient = request.app.state.tts
    if req.voice:
        status = await tts.probe()
        if not status.ok:
            raise HTTPException(
                status_code=400,
                detail=f"TTS 服务不可用，无法开启语音：{status.detail or ''}".rstrip("："),
            )
    _check_agent_ids(req, request.app.state.agent_library, user)
    # 普通用户只能引用自己的 provider；admin 不限（issue #114）
    allowed: set[str] | None = (
        None
        if user.role == "admin"
        else {p.provider_id for p in visible_providers(request.app.state.provider_store, user)}
    )
    try:
        handle = games.create(
            config,
            allow_spectators=req.allow_spectators,
            num_ai_players=req.num_ai_players,
            agents=req.agents,
            ai_model=req.ai_model,
            ai_model_speech=req.ai_model_speech,
            voice=req.voice,
            narration=req.narration,
            owner_id=user.user_id,
            allowed_providers=allowed,
            require_provider=user.role != "admin",
            agent_ids=req.agent_ids,
        )
    except ValueError as exc:
        raise ToolCallError(f"agents 非法：{exc}") from exc
    host_token = tokens.issue(
        TokenInfo(game_id=handle.game_id, seat=None, kind="HOST", user_id=user.user_id)
    )
    share = share_token(request.app.state.secret, handle.game_id) if req.allow_spectators else None
    gm_token = tokens.issue(
        TokenInfo(game_id=handle.game_id, seat=None, kind="GM", user_id=user.user_id)
    )
    return CreateGameResponse(
        game_id=handle.game_id,
        host_token=host_token,
        share_token=share,
        gm_token=gm_token,
        # 回显 handle.config 而非请求侧 config：未指定 seed 时 registry 会抽一个随机种子写入
        config=handle.config.model_dump(mode="json"),
        agents=handle.agents,
        voice=handle.voice_enabled,
        narration=handle.narration_enabled,
    )


@router.post("/{game_id}/join")
def join_endpoint(
    game_id: str,
    req: JoinRequest,
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    user: User | None = Depends(current_user),
    games: GameRegistry = Depends(get_games),
    tokens: TokenRegistry = Depends(get_tokens),
) -> JoinResponse:
    """入座：登录会话（记录 user_id），或本局 host_token（外部 Agent 客户端，user_id=None）。"""
    user_id: str | None
    if user is not None:
        user_id = user.user_id
    else:
        info = tokens.resolve(creds.credentials) if creds is not None else None
        if info is None or info.kind != "HOST" or info.game_id != game_id:
            raise HTTPException(status_code=401, detail="入座需登录，或携带本局 host_token")
        user_id = None
    handle = games.get(game_id)
    seat = games.join(handle, req.display_name, req.player_type, seat=req.seat, user_id=user_id)
    token = tokens.issue(TokenInfo(game_id=game_id, seat=seat, kind="PLAYER", user_id=user_id))
    return JoinResponse(player_token=token, seat=seat, ws_url=f"/api/v1/ws?token={token}")


@router.post("/{game_id}/start")
async def start_endpoint(
    game_id: str,
    req: StartRequest,
    info: TokenInfo = Depends(require_token),
    games: GameRegistry = Depends(get_games),
) -> StartResponse:
    handle = games.get(game_id)
    require_kind(info, game_id, "HOST")
    games.start(handle, fill_with_bots=req.fill_with_bots)
    return StartResponse(ok=True, num_players=handle.config.num_players)


def _handle_for(games: GameRegistry, game_id: str) -> GameHandle:
    handle = games.get(game_id)
    handle.ensure_healthy()
    return handle


def viewer_of(info: TokenInfo) -> Any:
    """token → 可见性 viewer：座位号 / "SPECTATOR" / "GM"（GM 全量，issue #26）。"""
    if info.kind == "PLAYER":
        return info.seat
    return "GM" if info.kind == "GM" else "SPECTATOR"


def _owner_of(games: GameRegistry, game_id: str) -> str | None:
    """对局归属：活 handle 优先；否则读事件文件首行；都没有 → 404。"""
    try:
        return games.get(game_id).owner_id
    except LookupError:
        pass
    try:
        return games.store.load_meta(game_id).owner_id
    except (LookupError, StoreError):
        raise HTTPException(status_code=404, detail=f"对局不存在：{game_id}") from None


def _finished(games: GameRegistry, game_id: str) -> bool:
    """对局是否已终局；既无 handle 又无事件文件 → 404（不落到全局 500）。"""
    try:
        handle = games.get(game_id)
    except LookupError:
        try:
            return is_finished(games.store.load_events(game_id))
        except (LookupError, StoreError):
            raise HTTPException(status_code=404, detail=f"对局不存在：{game_id}") from None
    return handle.started and handle.live_state().phase == Phase.GAME_OVER


GM_LOCKED_MSG = "建局者已入座，对局结束前不能查看上帝视角"


def _owner_locked(games: GameRegistry, game_id: str) -> bool:
    """建局者已入座且未终局（issue #115）：上帝视角封锁中。无活 handle（纯历史文件）→ False。"""
    try:
        handle = games.get(game_id)
    except LookupError:
        return False
    if handle.owner_seat() is None:
        return False
    return not (handle.started and handle.live_state().phase == Phase.GAME_OVER)


def _require_finished(games: GameRegistry, game_id: str) -> None:
    if not _finished(games, game_id):
        raise HTTPException(status_code=403, detail="对局未结束，上帝视角回放未开放")


def _share_viewer(games: GameRegistry, secret: bytes, game_id: str, share: str) -> TokenInfo:
    """分享 token（issue #114）：直播期间要求 allow_spectators；终局一律放行。"""
    if not verify_share_token(secret, game_id, share):
        raise HTTPException(status_code=401, detail="分享链接无效")
    try:
        handle: GameHandle | None = games.get(game_id)
    except LookupError:
        handle = None
    if handle is not None and not handle.allow_spectators and not _finished(games, game_id):
        raise HTTPException(status_code=403, detail="该对局不开放观战")
    return TokenInfo(game_id=game_id, seat=None, kind="SPECTATOR")


def _session_viewer(games: GameRegistry, user: User | None, game_id: str) -> TokenInfo:
    """登录态：建局者 / admin → GM；其他人 → 404（不泄露存在性）；未登录 → 401。

    建局者本人已入座且未终局（issue #115）→ 解析成该座位的 PLAYER 视角（admin 身份的建局者也一样：
    正在打的人不该看到全局）；终局后恢复 GM。
    """
    if user is None:
        raise HTTPException(status_code=401, detail="请登录或使用分享链接")
    owner_id = _owner_of(games, game_id)
    if not can_access(user, owner_id):
        raise HTTPException(status_code=404, detail=f"对局不存在：{game_id}")
    if user.user_id == owner_id and _owner_locked(games, game_id):
        seat = games.get(game_id).owner_seat()
        return TokenInfo(game_id=game_id, seat=seat, kind="PLAYER", user_id=user.user_id)
    return TokenInfo(game_id=game_id, seat=None, kind="GM", user_id=user.user_id)


def resolve_viewer(
    game_id: str,
    request: Request,
    token: str | None = Query(default=None),
    share: str | None = Query(default=None),
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    user: User | None = Depends(current_user),
    games: GameRegistry = Depends(get_games),
    tokens: TokenRegistry = Depends(get_tokens),
) -> TokenInfo:
    """读端点统一视角解析（spec §6）：对局 token → 分享 token → 会话归属 → 401。
    `?token=` 与 Bearer 等价（<audio>/WS 发不出头）。"""
    raw = creds.credentials if creds is not None else token
    if raw:
        info = tokens.resolve(raw)
        if info is None:
            raise HTTPException(status_code=401, detail="token 无效")
        if info.game_id != game_id:
            raise HTTPException(status_code=403, detail="token 与对局不匹配")
        if info.kind == "GM" and _owner_locked(games, game_id):
            raise HTTPException(status_code=403, detail=GM_LOCKED_MSG)
        return info
    if share:
        return _share_viewer(games, request.app.state.secret, game_id, share)
    return _session_viewer(games, user, game_id)


def _reject_host(info: TokenInfo) -> None:
    if info.kind == "HOST":
        raise HTTPException(status_code=403, detail="host_token 无读流权限")


@router.get("")
def list_games_endpoint(
    request: Request,
    user: User = Depends(require_user),
    games: GameRegistry = Depends(get_games),
) -> list[GameSummary]:
    """历史对局列表（issue #98）：按归属过滤（本人 / admin 全部），补 owner_name 与分享 token。"""
    users: UserStore = request.app.state.users
    secret: bytes = request.app.state.secret
    out: list[GameSummary] = []
    for s in list_history(games.store, games):
        if not can_access(user, s.owner_id):
            continue
        owner = users.get(s.owner_id) if s.owner_id else None
        out.append(
            s.model_copy(
                update={
                    "owner_name": owner.username if owner else None,
                    "share_token": share_token(secret, s.game_id),
                }
            )
        )
    return out


@router.delete("/{game_id}", status_code=204, response_class=Response)
def delete_game_endpoint(
    game_id: str,
    request: Request,
    user: User = Depends(require_user),
    games: GameRegistry = Depends(get_games),
    tokens: TokenRegistry = Depends(get_tokens),
) -> Response:
    """删除历史对局（issue #100）：删事件文件 + 摘 handle + 作废该局 token。

    仅建局者 / admin 可删；他人与不存在一律 404（issue #114）。
    已开局且 task 未结束 → 409；未开局可删；已终局 / 崩溃 / 仅存文件的中断局都可删。
    不触碰 agent 跨局记忆（experience）——那是档案的数据，不随对局走。
    """
    if not can_access(user, _owner_of(games, game_id)):
        raise HTTPException(status_code=404, detail=f"对局不存在：{game_id}")
    try:
        handle: GameHandle | None = games.get(game_id)
    except LookupError:
        handle = None
    # 未开局（issue #115：Lobby 三步编排中途失败的半成品）可删；已开局且 task 未结束 → 409
    if (
        handle is not None
        and handle.started
        and not (handle.task is not None and handle.task.done())
    ):
        raise HTTPException(status_code=409, detail="对局进行中，不能删除")
    try:
        games.store.delete_game(game_id)
    except (GameNotFoundError, InvalidGameIdError):
        # 非法 id / 文件不在归 404；handle 存在但文件已没了的情况仍把 handle 清掉
        if handle is None:
            raise HTTPException(status_code=404, detail=f"对局不存在：{game_id}") from None
    except StoreError as exc:
        # 真删不掉（权限、磁盘）：不能装作成功把 handle/token 清掉，也不把文件名/OS 错误回给调用方
        logger.error("删除对局 %s 的事件文件失败：%s", game_id, exc)
        raise HTTPException(status_code=500, detail="删除失败，请查看服务端日志") from exc
    # 发言配音（issue #103）：事件文件删成功后连带清音频目录；SpeechAudioSink.delete_game 幂等
    request.app.state.speech_audio.delete_game(game_id)
    if handle is not None:
        games.remove(game_id)
    tokens.revoke_game(game_id)
    return Response(status_code=204)


def games_store_events(games: GameRegistry, game_id: str) -> list[Event]:
    return games.store.load_events(game_id)


@router.get("/{game_id}/state")
def state_endpoint(
    game_id: str,
    info: TokenInfo = Depends(resolve_viewer),
    games: GameRegistry = Depends(get_games),
) -> dict[str, Any]:
    """按视角返回快照；顶层 `viewer` 告诉前端本次被解析成了哪种视角（issue #115）。"""
    handle = _handle_for(games, game_id)
    _reject_host(info)
    live = handle.live_state()  # 未开局 → LobbyError(409)
    # 公开规则子集（issue #80）：观众 / 玩家视角的计票展示需要真实的 sheriff.vote_weight，
    # 之前前端对缺失的 config 猜 1.5，config_override 改票权后票数徽标与服务端 tally 不一致
    public_config = _public_config(live)
    if info.kind == "PLAYER":
        assert info.seat is not None
        obs = build_observation(live, info.seat).model_dump(mode="json")
        # 展示名是公开信息（观众视图也有），玩家页需要它渲染座位环；不动引擎的 observation
        names = {p.seat: p.display_name for p in live.players}
        obs["seats"] = [{**s, "display_name": names[int(s["seat"])]} for s in obs["seats"]]
        obs["viewer"] = info.seat
        obs["config"] = public_config
        return obs
    if info.kind == "GM":
        return {**live.model_dump(mode="json"), "viewer": "GM"}
    return SpectatorView(
        game_id=game_id,
        phase=str(live.phase),
        round=live.round,
        seats=[
            {
                "seat": p.seat,
                "display_name": p.display_name,
                "alive": p.alive,
                "is_sheriff": p.is_sheriff,
                "idiot_revealed": p.idiot_revealed,
            }
            for p in live.players
        ],
        sheriff_seat=live.sheriff_seat,
        winner=live.winner,
        config=public_config,
    ).model_dump(mode="json")


def _public_config(live: GameState) -> dict[str, Any]:
    """对局规则里全场公开的子集：人数与警长规则（票权、警徽流等），不含座位角色分配。"""
    return {
        "num_players": live.config.num_players,
        "sheriff": live.config.sheriff.model_dump(mode="json"),
    }


@router.get("/{game_id}/speeches")
def speeches_endpoint(
    game_id: str,
    round: int | None = Query(default=None),
    phase: str | None = Query(default=None),
    _info: TokenInfo = Depends(resolve_viewer),
    games: GameRegistry = Depends(get_games),
) -> list[SpeechItem]:
    try:
        handle: GameHandle | None = games.get(game_id)
    except LookupError:
        handle = None  # 无活 handle：resolve_viewer 已校验归属 / 分享，事件文件齐全
    if handle is not None:
        handle.ensure_healthy()
        if not handle.started:
            return []
    # 服务端以 GM 视角扫描以计算 round/phase（返回的两类事件本身是 PUBLIC）
    out: list[SpeechItem] = []
    cur_round, cur_phase = 0, ""
    for e in games_store_events(games, game_id):
        if e.type == EventType.ROUND_STARTED:
            cur_round = int(e.payload.round)  # type: ignore[attr-defined]
        elif e.type == EventType.PHASE_CHANGED:
            cur_phase = str(e.payload.to)  # type: ignore[attr-defined]
        elif (
            e.type == EventType.PLAYER_SPOKE
            and e.actor_seat is not None
            and e.visibility == Visibility.PUBLIC
        ):
            # 护栏：即使未来出现非 PUBLIC 的发言类事件（如狼频道），也不得进入公开 speeches
            out.append(
                SpeechItem(
                    seq=e.seq,
                    round=cur_round,
                    phase=cur_phase,
                    seat=e.actor_seat,
                    content=e.payload.content,  # type: ignore[attr-defined]
                    claim_role=None
                    if e.payload.claim_role is None  # type: ignore[attr-defined]
                    else str(e.payload.claim_role),  # type: ignore[attr-defined]
                    badge_flow=e.payload.badge_flow,  # type: ignore[attr-defined]
                    kind="speech",
                )
            )
        elif e.type == EventType.LAST_WORDS and e.visibility == Visibility.PUBLIC:
            # 护栏：即使未来出现非 PUBLIC 的发言类事件（如狼频道），也不得进入公开 speeches
            out.append(
                SpeechItem(
                    seq=e.seq,
                    round=cur_round,
                    phase=cur_phase,
                    seat=e.payload.seat,  # type: ignore[attr-defined]
                    content=e.payload.content,  # type: ignore[attr-defined]
                    kind="last_words",
                )
            )
    if round is not None:
        out = [s for s in out if s.round == round]
    if phase is not None:
        out = [s for s in out if s.phase == phase]
    return out


@router.get("/{game_id}/events")
def events_endpoint(
    game_id: str,
    from_seq: int = Query(default=0),
    info: TokenInfo = Depends(resolve_viewer),
    games: GameRegistry = Depends(get_games),
) -> list[dict[str, Any]]:
    handle = _handle_for(games, game_id)
    _reject_host(info)
    if not handle.started:
        return []
    viewer: Any = viewer_of(info)
    events = games.store.load_events(game_id, from_seq=from_seq)
    visible = visible_events(handle.live_state(), events, viewer)
    return [event_json_for_viewer(e, viewer) for e in visible]


@router.get("/{game_id}/replay")
def replay_endpoint(
    game_id: str,
    _info: TokenInfo = Depends(resolve_viewer),
    games: GameRegistry = Depends(get_games),
) -> list[dict[str, Any]]:
    _require_finished(games, game_id)
    return [event_to_json(e) for e in games.store.load_events(game_id)]


@router.get("/{game_id}/meta")
def meta_endpoint(
    game_id: str,
    info: TokenInfo = Depends(resolve_viewer),
    games: GameRegistry = Depends(get_games),
) -> dict[str, Any]:
    """对局头记录（配置 / 名单 / 各座位实际生效的 Agent 档案，issue #64）+ `viewer`（issue #115）。

    与 /replay 同一门槛：终局后才开放——档案含模型与技能等 GM 层信息，不经 observation 暴露。
    """
    _require_finished(games, game_id)
    meta = games.store.load_meta(game_id)
    data = meta.model_dump(mode="json")
    data.pop("agent_ids", None)  # 归因 id 不随分享链接外泄（issue #123）
    return {**data, "viewer": viewer_of(info)}


@router.get("/{game_id}/avatars")
def avatars_endpoint(
    game_id: str,
    request: Request,
    _info: TokenInfo = Depends(resolve_viewer),
    games: GameRegistry = Depends(get_games),
) -> dict[str, str]:
    """座位 → 头像 id（issue #102）。视角解析同其他读端点（resolve_viewer）。

    来源：已开局取 GameMeta.agents（开局时实际生效的档案，真人占座已剔除），否则取 handle.agents
    按 profile_for 展开 "*"。只含有头像的座位；头像 id 本就是公开资源引用。
    """
    try:
        handle: GameHandle | None = games.get(game_id)
    except LookupError:
        handle = None
    agents: AgentProfiles
    num_players: int
    if handle is not None and not handle.started:
        agents, num_players = handle.agents, handle.config.num_players
    else:
        try:
            meta = games.store.load_meta(game_id)
        except (GameNotFoundError, StoreError):
            if handle is None:
                raise HTTPException(status_code=404, detail=f"对局不存在：{game_id}") from None
            agents, num_players = handle.agents, handle.config.num_players  # 刚开局，meta 尚未落盘
        else:
            agents, num_players = meta.agents, meta.config.num_players
    # 头像晚于对局加到档案上的（老对局 meta 里 avatar=None）：按档案名在当前档案库里补一次。
    # 显示的是"该角色现在的头像"而非历史快照——头像是公开资源引用，不涉及任何对局信息。
    library: AgentLibraryStore = request.app.state.agent_library
    by_name: dict[str, str] | None = None
    out: dict[str, str] = {}
    for seat in range(num_players):
        p = profile_for(agents, seat)
        if p is None:
            continue
        if p.avatar is not None:
            out[str(seat)] = p.avatar
            continue
        if p.name is None:
            continue
        if by_name is None:
            by_name = {
                s.profile.name: s.profile.avatar
                for s in library.list()
                if s.profile.name is not None and s.profile.avatar is not None
            }
        if p.name in by_name:
            out[str(seat)] = by_name[p.name]
    return out


def _audio_visible_seqs(games: GameRegistry, game_id: str, info: TokenInfo) -> set[int] | None:
    """直播期间按 token 视角可见的事件 seq 集合；None = 不过滤（终局 / GM / 未开局）。
    与 /replay 口径一致：终局后全量；HOST 按观众处理。唯一可见性判定是 visible_events。"""
    if info.kind == "GM":
        return None
    try:
        handle = games.get(game_id)
    except LookupError:
        return None
    if not handle.started or handle.live_state().phase == Phase.GAME_OVER:
        return None
    viewer: Any = viewer_of(info)
    events = games.store.load_events(game_id)
    return {e.seq for e in visible_events(handle.live_state(), events, viewer)}


@router.get("/{game_id}/audio")
def audio_manifest_endpoint(
    game_id: str,
    request: Request,
    info: TokenInfo = Depends(resolve_viewer),
    games: GameRegistry = Depends(get_games),
) -> dict[str, list[dict[str, Any]]]:
    """发言音频清单 {seq: [{part, duration}]}（issue #103）；权限同 /replay，
    直播期间按视角过滤（issue #110）。"""
    sink: SpeechAudioSink = request.app.state.speech_audio
    manifest = sink.manifest(game_id)
    allowed = _audio_visible_seqs(games, game_id, info)
    if allowed is None:
        return manifest
    return {k: v for k, v in manifest.items() if int(k) in allowed}


@router.get("/{game_id}/audio/{seq}/{part}")
def audio_part_endpoint(
    game_id: str,
    seq: int,
    part: int,
    request: Request,
    info: TokenInfo = Depends(resolve_viewer),
    games: GameRegistry = Depends(get_games),
) -> FileResponse:
    """发言音频文件（issue #103）；视角解析同 /replay（`?token=` / `?share=` 均可，
    浏览器 `<audio>` 发不出 Authorization 头）。直播期间按视角过滤（issue #110）。"""
    sink: SpeechAudioSink = request.app.state.speech_audio
    allowed = _audio_visible_seqs(games, game_id, info)
    if allowed is not None and seq not in allowed:
        raise HTTPException(status_code=404, detail="音频不存在")
    path = sink.path_for(game_id, seq, part)
    if path is None:
        raise HTTPException(status_code=404, detail="音频不存在")
    return FileResponse(
        path,
        media_type="audio/wav",
        headers={"Cache-Control": "private, max-age=31536000, immutable"},
    )


@tts_router.get("/status")
async def tts_status_endpoint(request: Request, _: User = Depends(require_user)) -> TtsStatus:
    """TTS 服务探测状态（issue #103）；响应绝不含 api key。"""
    tts: TtsClient = request.app.state.tts
    return await tts.probe()


@router.post("/{game_id}/actions")
async def actions_endpoint(
    game_id: str,
    call: ToolCall,
    response: Response,
    info: TokenInfo = Depends(require_token),
    games: GameRegistry = Depends(get_games),
) -> ActionResponse:
    handle = _handle_for(games, game_id)
    require_kind(info, game_id, "PLAYER")
    assert info.seat is not None
    port = handle.human_ports.get(info.seat)
    if port is None:
        raise HTTPException(status_code=403, detail="该座位非外接玩家")
    action = parse_tool_call(call, actor_seat=info.seat)
    prompt = port.current_prompt
    submitted_version = prompt.observation.state_version if prompt is not None else 0
    fut = port.submit(action, state_version=call.state_version)
    try:
        outcome = await asyncio.wait_for(asyncio.shield(fut), timeout=ACCEPT_WAIT_SEC)
    except TimeoutError:
        # 同步窗口（issue #134）：裁决要等全体到齐，先回 202 受理；结果随后经 WS
        # action_result 或 GET /state 获得。fut 仍由 runner 回填，无人等待亦无妨。
        response.status_code = 202
        return ActionResponse(ok=True, state_version=submitted_version, accepted=True)
    return ActionResponse(
        ok=outcome.ok,
        event_id=outcome.event_id,
        state_version=outcome.state_version,
        rejected_reason=outcome.rejected_reason,
    )


@router.get("/{game_id}/my-turn")
async def my_turn_endpoint(
    game_id: str,
    wait: float = Query(default=25.0, le=30.0),
    info: TokenInfo = Depends(require_token),
    games: GameRegistry = Depends(get_games),
) -> Response:
    handle = _handle_for(games, game_id)
    require_kind(info, game_id, "PLAYER")
    assert info.seat is not None
    port = handle.human_ports.get(info.seat)
    if port is None:
        raise HTTPException(status_code=403, detail="该座位非外接玩家")
    deadline = time.time() + wait
    while True:
        remaining = deadline - time.time()
        if remaining <= 0:
            return Response(status_code=204)
        if handle.task is not None and handle.task.done():
            return Response(status_code=204)  # 对局已终局：立即结束长轮询
        prompt = await port.wait_armed(min(remaining, 0.25))
        if prompt is not None:
            return JSONResponse(_your_turn_payload(prompt))


def _your_turn_payload(prompt: TurnPrompt) -> dict[str, Any]:
    return {
        "observation": prompt.observation.model_dump(mode="json"),
        "available_tools": list(available_tools_for(prompt.observation)),
        "deadline_ts": prompt.deadline_ts,
    }
