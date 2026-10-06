"""FastAPI 装配（issue #30）。uvicorn 入口：`uvicorn app.main:app`。"""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.agent.skills import BUILTIN_SKILLS_DIR, SkillLibrary
from app.api import agents, avatars, providers, rest, ws
from app.api.deps import TokenRegistry
from app.runtime.agent_library import AgentLibraryStore, JsonFileAgentLibrary
from app.runtime.avatar_store import AvatarStore, FileAvatarStore
from app.runtime.experience_store import ExperienceStore, JsonFileExperienceStore
from app.runtime.game_runner import LobbyError, RunnerTimeouts
from app.runtime.player_port import NotYourTurnError, PlayerPort
from app.runtime.provider_probe import LiteLLMProbe, ProviderProbe
from app.runtime.provider_store import JsonFileProviderStore, ProviderStore
from app.runtime.registry import GameRegistry
from app.runtime.speech_audio import SpeechAudioSink
from app.runtime.tts import TtsClient, TtsConfig, build_tts_client
from app.schemas.actions import ToolCallError
from app.store.event_store import EventStore, JsonFileEventStore, StoreError

if TYPE_CHECKING:
    from app.runtime.registry import GameHandle


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
    avatar_store: AvatarStore | None = None,
    frontend_dist: Path | None = None,
    public_history: bool | None = None,
    tts_config: TtsConfig | None = None,
    tts_client: TtsClient | None = None,
    audio_dir: Path | None = None,
) -> FastAPI:
    app = FastAPI(title="AgentHowl API", version="0.1.0")
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
    app.state.speech_audio = SpeechAudioSink(audio_dir or Path("data/audio"), tts)
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
    )
    app.state.tokens = TokenRegistry()
    # 历史对局公开开关（issue #98）：默认开放已终局对局的无 token 回放
    if public_history is None:
        raw = os.environ.get("AGENTHOWL_PUBLIC_HISTORY", "1").strip().lower()
        public_history = raw not in ("0", "false", "no", "off")
    app.state.public_history = public_history
    app.state.agent_library = agent_library or JsonFileAgentLibrary(
        agents_dir or Path("data/agents")
    )
    # 头像存储（issue #102）：内容寻址，首次上传建目录
    app.state.avatar_store = avatar_store or FileAvatarStore(avatars_dir or Path("data/avatars"))
    app.include_router(rest.router, prefix="/api/v1")
    app.include_router(rest.tts_router, prefix="/api/v1")
    app.include_router(ws.router, prefix="/api/v1")
    app.include_router(agents.router, prefix="/api/v1")
    app.include_router(providers.router, prefix="/api/v1")
    app.include_router(avatars.router, prefix="/api/v1")

    def _handler(status: int):  # type: ignore[no-untyped-def]
        async def h(request: Request, exc: Exception) -> JSONResponse:
            return JSONResponse(status_code=status, content={"detail": str(exc)})

        return h

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
