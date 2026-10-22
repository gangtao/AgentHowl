"""FastAPI 装配（issue #30）。uvicorn 入口：`uvicorn app.main:app`。"""

from __future__ import annotations

import logging
import os
import re
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.agent.skills import BUILTIN_SKILLS_DIR, SkillLibrary
from app.api import admin, agents, auth, avatars, providers, rest, voices, ws
from app.api.auth import UnverifiedError
from app.api.deps import TokenRegistry
from app.runtime.agent_library import AgentLibraryStore, JsonFileAgentLibrary
from app.runtime.avatar_store import AvatarStore, FileAvatarStore
from app.runtime.experience_store import ExperienceStore, JsonFileExperienceStore
from app.runtime.game_runner import LobbyError, RunnerTimeouts
from app.runtime.mailer import MailConfig, Mailer, NullMailer, SmtpMailer
from app.runtime.narration import NarrationCache, NarrationConfig
from app.runtime.player_port import NotYourTurnError, PlayerPort
from app.runtime.provider_probe import LiteLLMProbe, ProviderProbe
from app.runtime.provider_store import JsonFileProviderStore, ProviderStore
from app.runtime.ratelimit import DEFAULT_RULES, RateLimiter
from app.runtime.registry import GameRegistry
from app.runtime.secret import load_secret
from app.runtime.speech_audio import SpeechAudioSink
from app.runtime.tts import TtsClient, TtsConfig, build_tts_client
from app.runtime.users import SqliteUserStore, UserStore, bootstrap_admin
from app.runtime.voice_anchors import VoiceAnchorStore
from app.schemas.actions import ToolCallError
from app.store.event_store import EventStore, JsonFileEventStore, StoreError

if TYPE_CHECKING:
    from app.runtime.registry import GameHandle


_TOKEN_RE = re.compile(r"((?:token|share)=)[^&\s\"]+")


class _MaskTokenFilter(logging.Filter):
    """uvicorn access log 里的 `?token=…`（/ws、/audio 文件端点）脱敏为 token=***（issue #108）。"""

    def filter(self, record: logging.LogRecord) -> bool:
        if record.args and isinstance(record.args, tuple):
            record.args = tuple(
                _TOKEN_RE.sub(r"\1***", a) if isinstance(a, str) else a for a in record.args
            )
        if isinstance(record.msg, str) and ("token=" in record.msg or "share=" in record.msg):
            record.msg = _TOKEN_RE.sub(r"\1***", record.msg)
        return True


def install_access_log_filter() -> logging.Filter:
    """幂等：同一个 logger 只挂一个。"""
    log = logging.getLogger("uvicorn.access")
    for f in log.filters:
        if isinstance(f, _MaskTokenFilter):
            return f
    flt = _MaskTokenFilter()
    log.addFilter(flt)
    return flt


def _bootstrap_admin_from_env(users: UserStore) -> None:
    """AGENTHOWL_ADMIN_USERNAME/EMAIL/PASSWORD 三者齐全 → 建 admin；只配了部分 → fail-loud。"""
    keys = ("AGENTHOWL_ADMIN_USERNAME", "AGENTHOWL_ADMIN_EMAIL", "AGENTHOWL_ADMIN_PASSWORD")
    vals = [os.environ.get(k, "").strip() for k in keys]
    if any(vals) and not all(vals):
        raise ValueError(f"管理员引导变量须同时配置：{', '.join(keys)}")
    if all(vals):
        created = bootstrap_admin(users, username=vals[0], email=vals[1], password=vals[2])
        if created is not None:
            logging.getLogger(__name__).info("已创建管理员 %s", created.username)
    if not any(u.role == "admin" for u in users.list()):
        logging.getLogger(__name__).warning(
            "用户表里没有管理员：配置 AGENTHOWL_ADMIN_* 或用 app.cli.claim 后再提升"
        )


def create_app(
    *,
    store: EventStore | None = None,
    timeouts: RunnerTimeouts | None = None,
    data_dir: Path | None = None,
    agent_port_factory: Callable[[int, GameHandle], PlayerPort] | None = None,
    skills_dir: Path | None = None,
    memory_dir: Path | None = None,
    experience_store: ExperienceStore | None = None,
    agents_dir: Path | None = None,
    agent_library: AgentLibraryStore | None = None,
    providers_dir: Path | None = None,
    provider_store: ProviderStore | None = None,
    provider_probe: ProviderProbe | None = None,
    avatars_dir: Path | None = None,
    voices_dir: Path | None = None,
    avatar_store: AvatarStore | None = None,
    frontend_dist: Path | None = None,
    tts_config: TtsConfig | None = None,
    tts_client: TtsClient | None = None,
    audio_dir: Path | None = None,
    narration_config: NarrationConfig | None = None,
    user_store: UserStore | None = None,
    users_db: Path | None = None,
    mailer: Mailer | None = None,
    secret: bytes | None = None,
    rate_limiter: RateLimiter | None = None,
    cookie_secure: bool | None = None,
) -> FastAPI:
    app = FastAPI(title="AgentHowl API", version="0.1.0")
    install_access_log_filter()
    # 内置目录允许缺失（打包场景，容忍过滤）；显式指定的外部目录原样传给 load，
    # 不存在则 fail-loud（终审 F3：此前 is_dir() 过滤会静默吞掉打错的路径）。
    dirs: list[Path] = [BUILTIN_SKILLS_DIR] if BUILTIN_SKILLS_DIR.is_dir() else []
    if skills_dir is not None:
        dirs.append(skills_dir)  # 显式指定的外部目录不存在 → SkillLibrary.load 报错（fail-loud）
    skill_library = SkillLibrary.load(dirs) if dirs else SkillLibrary.empty()
    # Provider 存储（issue #26）：惰性建目录，密钥明文文件权限 0600
    app.state.provider_store = provider_store or JsonFileProviderStore(
        providers_dir or Path("data/providers")
    )
    app.state.provider_probe = provider_probe or LiteLLMProbe()
    # 发言配音（issue #103）：TTS 客户端只认 OpenAI-speech 协议；未配置 URL → Disabled
    tts = tts_client or build_tts_client(tts_config or TtsConfig.from_env())
    app.state.tts = tts
    # 描述声线锚点（句句同一个人）：data/voices
    app.state.voice_anchors = VoiceAnchorStore(voices_dir or Path("data/voices"))
    # GM 旁白（issue #110）：配置校验 fail-loud；句子缓存全局共用
    narration = narration_config or NarrationConfig.from_env(data_dir=Path("data"))
    app.state.speech_audio = SpeechAudioSink(
        audio_dir or Path("data/audio"),
        tts,
        app.state.voice_anchors,
        narration=narration,
        narration_cache=NarrationCache(narration.cache_dir),
    )
    # 跨局记忆目录（issue #59）：惰性建目录，无 memory_id 的运行永不落盘
    app.state.games = GameRegistry(
        store=store or JsonFileEventStore(data_dir or Path("data/games")),
        timeouts=timeouts,
        agent_port_factory=agent_port_factory,
        skill_library=skill_library,
        experience_store=experience_store
        or JsonFileExperienceStore(memory_dir or Path("data/agent_memory")),
        provider_store=app.state.provider_store,
        speech_audio=app.state.speech_audio,
        experience_store_for=lambda owner_id: JsonFileExperienceStore(
            (memory_dir or Path("data/agent_memory")) / owner_id
        ),
    )
    app.state.tokens = TokenRegistry()
    # 用户与会话（issue #114）
    base_dir = Path("data")
    app.state.users = user_store or SqliteUserStore(
        users_db or Path(os.environ.get("AGENTHOWL_USERS_DB", "data/users.db"))
    )
    if mailer is None:
        mail_cfg = MailConfig.from_env()  # HOST 有而 FROM 无 → ValueError（fail-loud）
        if mail_cfg is None:
            logging.getLogger(__name__).warning("未配置 AGENTHOWL_SMTP_HOST：注册免邮箱验证")
            mailer = NullMailer()
        else:
            mailer = SmtpMailer(mail_cfg)
    app.state.mailer = mailer
    app.state.secret = secret if secret is not None else load_secret(base_dir)
    app.state.rate_limiter = rate_limiter or RateLimiter(DEFAULT_RULES)
    if cookie_secure is None:
        cookie_secure = os.environ.get("AGENTHOWL_COOKIE_SECURE", "1").strip().lower() not in (
            "0",
            "false",
            "no",
            "off",
        )
    app.state.cookie_secure = cookie_secure
    app.state.trust_proxy = os.environ.get("AGENTHOWL_TRUST_PROXY", "0").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )
    _bootstrap_admin_from_env(app.state.users)
    app.state.agent_library = agent_library or JsonFileAgentLibrary(
        agents_dir or Path("data/agents")
    )
    # 头像存储（issue #102）：内容寻址，首次上传建目录
    app.state.avatar_store = avatar_store or FileAvatarStore(avatars_dir or Path("data/avatars"))
    app.include_router(auth.router, prefix="/api/v1")
    app.include_router(admin.router, prefix="/api/v1")

    @app.get("/api/v1/health")
    def health() -> dict[str, bool]:
        return {"ok": True}

    app.include_router(rest.router, prefix="/api/v1")
    app.include_router(rest.tts_router, prefix="/api/v1")
    app.include_router(ws.router, prefix="/api/v1")
    app.include_router(agents.router, prefix="/api/v1")
    app.include_router(providers.router, prefix="/api/v1")
    app.include_router(avatars.router, prefix="/api/v1")
    app.include_router(voices.router, prefix="/api/v1")

    def _handler(status: int):  # type: ignore[no-untyped-def]
        async def h(request: Request, exc: Exception) -> JSONResponse:
            return JSONResponse(status_code=status, content={"detail": str(exc)})

        return h

    async def _unverified(request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(
            status_code=401, content={"detail": "邮箱未验证", "reason": "unverified"}
        )

    app.add_exception_handler(UnverifiedError, _unverified)
    app.add_exception_handler(LobbyError, _handler(409))
    app.add_exception_handler(NotYourTurnError, _handler(409))
    app.add_exception_handler(ToolCallError, _handler(400))
    app.add_exception_handler(LookupError, _handler(404))
    app.add_exception_handler(StoreError, _handler(500))
    # runner task 崩溃后 handle.ensure_healthy() 抛出裸 RuntimeError，需兜底为 500（否则落到
    # Starlette 默认异常页，客户端拿不到 JSON detail）——issue #30 Task 5 复审发现。
    app.add_exception_handler(RuntimeError, _handler(500))
    # 前端产物（issue #26）：存在则整站挂到 /；API 路由已先注册，/api/v1 不受影响
    dist = (
        frontend_dist
        if frontend_dist is not None
        else Path(__file__).resolve().parents[2] / "frontend" / "dist"
    )
    if dist.is_dir():
        from fastapi.staticfiles import StaticFiles

        app.mount("/", StaticFiles(directory=str(dist), html=True), name="frontend")
    return app


_env_skills = os.environ.get("AGENTHOWL_SKILLS_DIR")
app = create_app(skills_dir=Path(_env_skills) if _env_skills else None)
