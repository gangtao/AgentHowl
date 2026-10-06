"""REST 端点（PRD §5.2）。零裁决：鉴权/序列化/转发（issue #30）。"""

from __future__ import annotations

import logging
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from pydantic import ValidationError

from app.agent.profile import AgentProfiles, profile_for
from app.api.deps import (
    TokenInfo,
    TokenRegistry,
    get_games,
    get_tokens,
    optional_token,
    require_kind,
    require_token,
)
from app.api.views import event_json_for_viewer
from app.engine.config import build_preset
from app.engine.events import Event, EventType, Visibility
from app.engine.observation import build_observation, visible_events
from app.engine.phases import Phase
from app.runtime.agent_library import AgentLibraryStore
from app.runtime.history import GameSummary, is_finished, list_history
from app.runtime.player_port import NotYourTurnError, TurnPrompt
from app.runtime.registry import GameHandle, GameRegistry
from app.runtime.speech_audio import SpeechAudioSink
from app.runtime.tts import TtsClient, TtsStatus
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
    GameMeta,
    GameNotFoundError,
    InvalidGameIdError,
    StoreError,
    event_to_json,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/games", tags=["games"])
tts_router = APIRouter(prefix="/tts", tags=["tts"])


@router.post("")
async def create_game_endpoint(
    req: CreateGameRequest,
    request: Request,
    games: GameRegistry = Depends(get_games),
    tokens: TokenRegistry = Depends(get_tokens),
) -> CreateGameResponse:
    try:
        config = build_preset(req.preset).model_copy(update=req.config_override)
        config = type(config).model_validate(config.model_dump())  # override 后全量校验
    except (KeyError, ValueError, ValidationError) as exc:
        raise ToolCallError(f"preset/config_override 非法：{exc}") from exc
    # 发言配音（issue #103）：开局前探测，不可用则 400，不悄悄降级
    tts: TtsClient = request.app.state.tts
    if req.voice:
        status = await tts.probe()
        if not status.ok:
            raise HTTPException(
                status_code=400,
                detail=f"TTS 服务不可用，无法开启语音：{status.detail or ''}".rstrip("："),
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
        )
    except ValueError as exc:
        raise ToolCallError(f"agents 非法：{exc}") from exc
    host_token = tokens.issue(TokenInfo(game_id=handle.game_id, seat=None, kind="HOST"))
    spectator_token = (
        tokens.issue(TokenInfo(game_id=handle.game_id, seat=None, kind="SPECTATOR"))
        if req.allow_spectators
        else None
    )
    gm_token = tokens.issue(TokenInfo(game_id=handle.game_id, seat=None, kind="GM"))
    return CreateGameResponse(
        game_id=handle.game_id,
        host_token=host_token,
        spectator_token=spectator_token,
        gm_token=gm_token,
        # 回显 handle.config 而非请求侧 config：未指定 seed 时 registry 会抽一个随机种子写入
        config=handle.config.model_dump(mode="json"),
        agents=handle.agents,
        voice=handle.voice_enabled,
    )


@router.post("/{game_id}/join")
def join_endpoint(
    game_id: str,
    req: JoinRequest,
    games: GameRegistry = Depends(get_games),
    tokens: TokenRegistry = Depends(get_tokens),
) -> JoinResponse:
    handle = games.get(game_id)
    seat = games.join(handle, req.display_name, req.player_type)
    token = tokens.issue(TokenInfo(game_id=game_id, seat=seat, kind="PLAYER"))
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


def _public_history(request: Request) -> bool:
    return bool(getattr(request.app.state, "public_history", True))


def _require_history_access(info: TokenInfo | None, public: bool) -> None:
    if info is None and not public:
        raise HTTPException(status_code=401, detail="缺少 Bearer token")


@router.get("")
def list_games_endpoint(
    request: Request,
    info: TokenInfo | None = Depends(optional_token),
    games: GameRegistry = Depends(get_games),
) -> list[GameSummary]:
    """历史对局列表（issue #98）：文件里的全部对局 + registry 的进行中状态。"""
    _require_history_access(info, _public_history(request))
    return list_history(games.store, games)


@router.delete("/{game_id}", status_code=204, response_class=Response)
def delete_game_endpoint(
    game_id: str,
    request: Request,
    games: GameRegistry = Depends(get_games),
    tokens: TokenRegistry = Depends(get_tokens),
) -> Response:
    """删除历史对局（issue #100）：删事件文件 + 摘 handle + 作废该局 token。

    权限跟随 AGENTHOWL_PUBLIC_HISTORY：开关关 → 一律 404（功能不存在，带 token 也一样）。
    有 handle 且 task 未结束（含未开局）→ 409；已终局 / 崩溃 / 仅存文件的中断局都可删。
    不触碰 agent 跨局记忆（experience）——那是档案的数据，不随对局走。
    """
    if not _public_history(request):
        raise HTTPException(status_code=404, detail=f"对局不存在：{game_id}")
    try:
        handle: GameHandle | None = games.get(game_id)
    except LookupError:
        handle = None
    if handle is not None and not (handle.task is not None and handle.task.done()):
        raise HTTPException(status_code=409, detail="对局进行中（或尚未开局），不能删除")
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


def _finished_from_store(games: GameRegistry, game_id: str) -> GameMeta:
    """registry 没有该局时退回事件文件：存在且已终局才开放，否则与现状同样的 404/403。

    注：GameNotFoundError 是 StoreError 的子类而非 LookupError（核对 event_store.py），
    两者都要捕获才能把"文件不存在"映射成 404（而非落到全局 StoreError→500 handler）。
    非法 game_id（_check_game_id 拒绝的字符）与损坏事件文件也从 StoreError 派生或直出——
    同样映射成 404，而不是把文件名/解析错误回给匿名访客（终审 m1）。
    """
    try:
        meta = games.store.load_meta(game_id)
    except (LookupError, GameNotFoundError, StoreError):
        raise HTTPException(status_code=404, detail=f"对局不存在：{game_id}") from None
    if not is_finished(games.store.load_events(game_id)):
        raise HTTPException(status_code=403, detail="对局未结束，上帝视角回放未开放")
    return meta


def _finished_or_handle(
    games: GameRegistry,
    game_id: str,
    info: TokenInfo | None,
    public: bool,
    *kinds: str,
    require_finished: bool = True,
) -> None:
    """三个终局接口共用的门槛（issue #98 fix round 1，评审 Blocker 1 / Ruling 3-4）。

    有 handle（对局在本进程注册过）：
      - 无 token：仅当开关开 + 已终局才放行，否则 401——与改造前一致，未变。
      - 有 token：开关开且已终局时，**任意有效 token 都降级为匿名放行**——不再校验 kind /
        game_id（既然该局对匿名完全公开，持 token 的访问者不该比匿名更受限，这是刻意的不对称：
        "终局 + 公开" 这一条件本身已经是最宽的闸门，token 只在它不满足时才需要起约束作用）；
        否则（未终局，或开关关）按原逻辑校验 kind，并按 `require_finished` 决定是否额外要求
        GAME_OVER —— `/speeches` 传 `False` 以保留"进行中/未开局也可读"的现状，`/replay` `/meta`
        保持默认 `True`。

    无 handle（registry 没有该局，典型如重启后换了新 registry）：
      - 开关关：不走 store 回退，与改造前严格一致——无 token 401（`require_token` 当年的
        行为：没带 token 根本进不到 `_handle_for`），带了（哪怕有效）token 则 404（`games.get`
        的裸 `LookupError`），都不理会 kind。
      - 开关开：退回 store；存在性/终局判断（`_finished_from_store` → 404/403）先于任何 token
        逻辑；通过后与上面"有 handle + 已终局 + 公开"同理，不再校验 kind。
    """
    try:
        handle = games.get(game_id)
    except LookupError:
        if not public:
            if info is None:
                raise HTTPException(status_code=401, detail="缺少 Bearer token") from None
            raise HTTPException(status_code=404, detail=f"对局不存在：{game_id}") from None
        _finished_from_store(games, game_id)
        return
    # 匿名 401 必须先于 ensure_healthy（终审 M1）：live_state() 只读 runner.state，不碰 task
    # 健康状态，崩溃 runner 不会让这行炸；这样未认证访客拿不到崩溃对局的内部异常文本。
    finished = handle.started and handle.live_state().phase == Phase.GAME_OVER
    if info is None and not (public and finished):
        raise HTTPException(status_code=401, detail="缺少 Bearer token")
    handle.ensure_healthy()
    if info is None or (public and finished):
        return
    require_kind(info, game_id, *kinds)
    if require_finished and not finished:
        raise HTTPException(status_code=403, detail="对局未结束，上帝视角回放未开放")


def _viewer_for(info: TokenInfo) -> Any:
    """token → 可见性 viewer：座位号 / "SPECTATOR" / "GM"（GM 全量，issue #26）。"""
    if info.kind == "PLAYER":
        return info.seat
    return "GM" if info.kind == "GM" else "SPECTATOR"


def games_store_events(games: GameRegistry, game_id: str) -> list[Event]:
    return games.store.load_events(game_id)


@router.get("/{game_id}/state")
def state_endpoint(
    game_id: str,
    info: TokenInfo = Depends(require_token),
    games: GameRegistry = Depends(get_games),
) -> dict[str, Any]:
    handle = _handle_for(games, game_id)
    require_kind(info, game_id, "PLAYER", "SPECTATOR", "GM")
    live = handle.live_state()  # 未开局 → LobbyError(409)
    if info.kind == "PLAYER":
        assert info.seat is not None
        return build_observation(live, info.seat).model_dump(mode="json")
    if info.kind == "GM":
        return live.model_dump(mode="json")
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
    ).model_dump(mode="json")


@router.get("/{game_id}/speeches")
def speeches_endpoint(
    game_id: str,
    request: Request,
    round: int | None = Query(default=None),
    phase: str | None = Query(default=None),
    info: TokenInfo | None = Depends(optional_token),
    games: GameRegistry = Depends(get_games),
) -> list[SpeechItem]:
    _finished_or_handle(
        games,
        game_id,
        info,
        _public_history(request),
        "PLAYER",
        "SPECTATOR",
        "GM",
        require_finished=False,  # 进行中/未开局也可读：规格 §2.2 要求 /speeches 行为完全同现状
    )
    try:
        handle: GameHandle | None = games.get(game_id)
    except LookupError:
        handle = None  # 无活 handle：已经过 _finished_or_handle 校验，必已终局，事件齐全
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
    info: TokenInfo = Depends(require_token),
    games: GameRegistry = Depends(get_games),
) -> list[dict[str, Any]]:
    handle = _handle_for(games, game_id)
    require_kind(info, game_id, "PLAYER", "SPECTATOR", "GM")
    if not handle.started:
        return []
    viewer: Any = _viewer_for(info)
    events = games.store.load_events(game_id, from_seq=from_seq)
    visible = visible_events(handle.live_state(), events, viewer)
    return [event_json_for_viewer(e, viewer) for e in visible]


@router.get("/{game_id}/replay")
def replay_endpoint(
    game_id: str,
    request: Request,
    info: TokenInfo | None = Depends(optional_token),
    games: GameRegistry = Depends(get_games),
) -> list[dict[str, Any]]:
    _finished_or_handle(
        games, game_id, info, _public_history(request), "PLAYER", "SPECTATOR", "HOST", "GM"
    )
    return [event_to_json(e) for e in games.store.load_events(game_id)]


@router.get("/{game_id}/meta")
def meta_endpoint(
    game_id: str,
    request: Request,
    info: TokenInfo | None = Depends(optional_token),
    games: GameRegistry = Depends(get_games),
) -> GameMeta:
    """对局头记录（配置 / 名单 / 各座位实际生效的 Agent 档案，issue #64）。

    与 /replay 同一门槛：终局后才开放——档案含模型与技能等 GM 层信息，不经 observation 暴露。
    """
    _finished_or_handle(
        games, game_id, info, _public_history(request), "PLAYER", "SPECTATOR", "HOST", "GM"
    )
    return games.store.load_meta(game_id)


@router.get("/{game_id}/avatars")
def avatars_endpoint(
    game_id: str,
    request: Request,
    info: TokenInfo | None = Depends(optional_token),
    games: GameRegistry = Depends(get_games),
) -> dict[str, str]:
    """座位 → 头像 id（issue #102）。直播中：本局任意有效 token；终局：公开策略同 /replay。

    来源：已开局取 GameMeta.agents（开局时实际生效的档案，真人占座已剔除），否则取 handle.agents
    按 profile_for 展开 "*"。只含有头像的座位；头像 id 本就是公开资源引用。
    """
    _finished_or_handle(
        games,
        game_id,
        info,
        _public_history(request),
        "PLAYER",
        "SPECTATOR",
        "HOST",
        "GM",
        require_finished=False,
    )
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


@router.get("/{game_id}/audio")
def audio_manifest_endpoint(
    game_id: str,
    request: Request,
    info: TokenInfo | None = Depends(optional_token),
    games: GameRegistry = Depends(get_games),
) -> dict[str, list[dict[str, Any]]]:
    """发言音频清单 {seq: [{part, duration}]}（issue #103）；权限同 /replay。"""
    _finished_or_handle(
        games,
        game_id,
        info,
        _public_history(request),
        "PLAYER",
        "SPECTATOR",
        "HOST",
        "GM",
        require_finished=False,
    )
    sink: SpeechAudioSink = request.app.state.speech_audio
    return sink.manifest(game_id)


@router.get("/{game_id}/audio/{seq}/{part}")
def audio_part_endpoint(
    game_id: str,
    seq: int,
    part: int,
    request: Request,
    token: str | None = Query(default=None),
    info: TokenInfo | None = Depends(optional_token),
    tokens: TokenRegistry = Depends(get_tokens),
    games: GameRegistry = Depends(get_games),
) -> FileResponse:
    """发言音频文件（issue #103）；权限同 /replay，另外接受 `?token=` 查询参数（fix round 1）：
    浏览器 `<audio>` 元素发不出 Authorization 头，直播期间（未终局）这个端点走
    `_finished_or_handle` 的「无 token 必须 401」分支——没有这条 query token 后路，
    直播配音在匿名场景下（含公开历史关闭时的正常对局内观众）一句都放不出来。
    等价于 WS 端点早就有的 `?token=` 先例（`wsUrl()`）。"""
    if info is None and token is not None:
        info = tokens.resolve(token)
        if info is None:
            raise HTTPException(status_code=401, detail="token 无效")
    _finished_or_handle(
        games,
        game_id,
        info,
        _public_history(request),
        "PLAYER",
        "SPECTATOR",
        "HOST",
        "GM",
        require_finished=False,
    )
    sink: SpeechAudioSink = request.app.state.speech_audio
    path = sink.path_for(game_id, seq, part)
    if path is None:
        raise HTTPException(status_code=404, detail="音频不存在")
    return FileResponse(
        path,
        media_type="audio/wav",
        headers={"Cache-Control": "private, max-age=31536000, immutable"},
    )


@tts_router.get("/status")
async def tts_status_endpoint(request: Request) -> TtsStatus:
    """TTS 服务探测状态（issue #103）；响应绝不含 api key。"""
    tts: TtsClient = request.app.state.tts
    return await tts.probe()


@router.post("/{game_id}/actions")
async def actions_endpoint(
    game_id: str,
    call: ToolCall,
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
    try:
        outcome = await port.submit_and_wait(action, timeout=10.0)
    except TimeoutError:
        raise NotYourTurnError("行动窗口已关闭（可能已超时代打）") from None
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
