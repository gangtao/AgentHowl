# Agent 头像实现计划（issue #102）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 档案可挂一张上传的头像，座位环、发言卡、档案卡显示它；无头像退回「名字首字 + 座位色」占位。

**Architecture:** `AgentProfile.avatar` 存内容寻址 id（sha256 前 16 位 + 扩展名），文件在 `data/avatars/`，经
`PUT/GET /api/v1/avatars` 上传/读取；对局页经新端点 `GET /games/{id}/avatars` 拿「座位 → 头像 id」映射
（直播/回放同一条路），前端零过滤地渲染。引擎零改动。

**Tech Stack:** Python 3.11 / FastAPI / Pydantic v2 / pytest；React 18 / TS strict / Vitest / Testing Library。

**Spec:** `docs/superpowers/specs/2026-10-05-agent-avatar-voice-design.md`（§2、§3、§5、§6）

## Global Constraints

- `backend/app/engine` 零 diff；`frontend/src/engine/__fixtures__` 不变。
- `app/runtime`、`app/api` 不得模块级 import `app.agent.agent_player` / `app.agent.llm_client`（litellm 惰性加载）。
- 头像 id 正则 `^[0-9a-f]{16}\.(png|jpg|webp)$`，触盘前必校验；`data/avatars` 不整目录挂 `StaticFiles`。
- 上传上限 512 KB（`MAX_AVATAR_BYTES = 512 * 1024`），超限 413；类型按魔数判，不符 415；不引入 Pillow、`python-multipart`。
- `GET /api/v1/avatars/{id}` 不鉴权，响应头 `Cache-Control: public, max-age=31536000, immutable`。
- 前端零信息过滤：只渲染服务端给的 id；`SeatCircle` 现有「角色缩写零过滤」语义不变（未知显示 `?`）。
- 中文注释 / 英文标识符；`uv run ruff check . && uv run ruff format --check . && uv run mypy app`、`npm run check` 全绿后再提交。
- 提交信息带 `(issue #102)` 与 `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`。

---

### Task 1: 后端 —— `AgentProfile.avatar` 字段 + `AvatarStore`

**Files:**
- Modify: `backend/app/agent/profile.py:31-55`
- Create: `backend/app/runtime/avatar_store.py`
- Test: `backend/tests/test_agent_profile.py`（追加）、`backend/tests/test_avatar_store.py`（新建）

**Interfaces:**
- Produces: `AVATAR_ID_PATTERN: str`；`AgentProfile.avatar: str | None`；
  `sniff_image(data: bytes) -> str | None`（返回 `"png" | "jpg" | "webp"` 或 None）；
  `class AvatarStore(Protocol)`：`put(data: bytes) -> str`（返回 avatar_id；类型不认 → `UnsupportedImageError`）、`path_for(avatar_id: str) -> Path | None`（不存在 → None；id 不合法 → `ValueError`）；
  `InMemoryAvatarStore`、`FileAvatarStore(data_dir: Path)`；`MAX_AVATAR_BYTES = 512 * 1024`。

- [ ] **Step 1: 写档案字段的失败测试**

在 `backend/tests/test_agent_profile.py` 末尾追加：

```python
def test_avatar_field_pattern_and_default() -> None:
    """issue #102：avatar 是内容 id（16 hex + 扩展名），默认 None；非法形状拒绝（路径穿越防护）。"""
    from pydantic import ValidationError

    assert AgentProfile(model="x").avatar is None
    ok = AgentProfile(model="x", avatar="3f9a1c0b7e2d4a66.png")
    assert ok.avatar == "3f9a1c0b7e2d4a66.png"
    for bad in ("../x.png", "3f9a1c0b7e2d4a66.gif", "3F9A1C0B7E2D4A66.png", "abc.png", ""):
        with pytest.raises(ValidationError):
            AgentProfile(model="x", avatar=bad)
    # 不进 LLM 配置
    cfg = to_agent_config(ok, build_preset("std_9_kill_side"))
    assert not hasattr(cfg, "avatar")
```

确认文件顶部已 import `pytest`、`AgentProfile`、`to_agent_config`、`build_preset`（现有测试已用到；缺哪个补哪个）。

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && uv run pytest tests/test_agent_profile.py::test_avatar_field_pattern_and_default -q`
Expected: FAIL（`avatar` 未定义，`extra="forbid"` 报错）

- [ ] **Step 3: 加字段**

`backend/app/agent/profile.py`，在 `STAR = "*"` 之后加常量，在 `provider` 字段之后加字段：

```python
# 头像资源 id（issue #102）：内容 sha256 前 16 位 + 扩展名；触盘前都按此正则校验（路径穿越防护）
AVATAR_ID_PATTERN = r"^[0-9a-f]{16}\.(png|jpg|webp)$"
```

```python
    # 头像资源 id（issue #102）：None = 无头像（前端占位）；不进 LLM 上下文
    avatar: str | None = Field(default=None, pattern=AVATAR_ID_PATTERN)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && uv run pytest tests/test_agent_profile.py -q`
Expected: 全部 PASS（含 `test_importing_registry_does_not_load_litellm`）

- [ ] **Step 5: 写 AvatarStore 的失败测试**

新建 `backend/tests/test_avatar_store.py`：

```python
"""AvatarStore（issue #102）：魔数识别、内容寻址、幂等、非法 id 拒绝。"""

from pathlib import Path

import pytest

from app.runtime.avatar_store import (
    AvatarStore,
    FileAvatarStore,
    InMemoryAvatarStore,
    UnsupportedImageError,
    sniff_image,
)

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
JPG = b"\xff\xd8\xff\xe0" + b"\x00" * 32
WEBP = b"RIFF" + b"\x00\x00\x00\x00" + b"WEBP" + b"\x00" * 32


def test_sniff_image() -> None:
    assert sniff_image(PNG) == "png"
    assert sniff_image(JPG) == "jpg"
    assert sniff_image(WEBP) == "webp"
    assert sniff_image(b"GIF89a" + b"\x00" * 32) is None
    assert sniff_image(b"hello world") is None
    assert sniff_image(b"") is None


@pytest.fixture(params=["memory", "file"])
def store(request: pytest.FixtureRequest, tmp_path: Path) -> AvatarStore:
    if request.param == "memory":
        return InMemoryAvatarStore()
    return FileAvatarStore(tmp_path / "avatars")


def test_put_is_content_addressed_and_idempotent(store: AvatarStore) -> None:
    a = store.put(PNG)
    assert len(a) == 20 and a.endswith(".png") and a[:16] == a[:16].lower()
    assert store.put(PNG) == a  # 同内容同 id
    assert store.put(JPG) != a
    assert store.path_for(a) is not None
    assert store.path_for(a).read_bytes() == PNG  # type: ignore[union-attr]


def test_put_rejects_unknown_type(store: AvatarStore) -> None:
    with pytest.raises(UnsupportedImageError):
        store.put(b"not an image")


def test_path_for_missing_and_illegal(store: AvatarStore) -> None:
    assert store.path_for("0000000000000000.png") is None
    for bad in ("../x.png", "x.png", "0000000000000000.gif"):
        with pytest.raises(ValueError):
            store.path_for(bad)


def test_file_store_does_not_rewrite_existing(tmp_path: Path) -> None:
    store = FileAvatarStore(tmp_path / "avatars")
    a = store.put(PNG)
    p = tmp_path / "avatars" / a
    before = p.stat().st_mtime_ns
    assert store.put(PNG) == a
    assert p.stat().st_mtime_ns == before
    assert not list((tmp_path / "avatars").glob("*.tmp"))
```

- [ ] **Step 6: 跑测试确认失败**

Run: `cd backend && uv run pytest tests/test_avatar_store.py -q`
Expected: FAIL（ModuleNotFoundError）

- [ ] **Step 7: 实现 AvatarStore**

新建 `backend/app/runtime/avatar_store.py`：

```python
"""头像存储（issue #102）：内容寻址（sha256 前 16 位 + 扩展名）、按魔数识别类型、幂等写入。

只存公开内容（头像随 /meta 对已终局对局公开），不需要 0600；不缩放、不做孤儿清理（规格 §3.1 非目标）。
"""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
from pathlib import Path
from typing import Protocol

from app.agent.profile import AVATAR_ID_PATTERN

MAX_AVATAR_BYTES = 512 * 1024
_ID_RE = re.compile(AVATAR_ID_PATTERN)


class UnsupportedImageError(ValueError):
    """字节不是 PNG / JPEG / WebP。"""


def sniff_image(data: bytes) -> str | None:
    """按魔数判类型：PNG `89 50 4E 47`、JPEG `FF D8 FF`、WebP `RIFF....WEBP`；不认识 → None。"""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return None


def avatar_id_for(data: bytes) -> str:
    ext = sniff_image(data)
    if ext is None:
        raise UnsupportedImageError("只支持 PNG / JPEG / WebP")
    return f"{hashlib.sha256(data).hexdigest()[:16]}.{ext}"


def check_avatar_id(avatar_id: str) -> None:
    if not _ID_RE.fullmatch(avatar_id):
        raise ValueError(f"非法 avatar_id：{avatar_id!r}")


class AvatarStore(Protocol):
    def put(self, data: bytes) -> str: ...

    def path_for(self, avatar_id: str) -> Path | None: ...


class InMemoryAvatarStore:
    """测试用：path_for 仍返回真实临时文件路径，让 FileResponse 路径可用。"""

    def __init__(self) -> None:
        self._dir = Path(tempfile.mkdtemp(prefix="agenthowl-avatars-"))
        self._inner = FileAvatarStore(self._dir)

    def put(self, data: bytes) -> str:
        return self._inner.put(data)

    def path_for(self, avatar_id: str) -> Path | None:
        return self._inner.path_for(avatar_id)


class FileAvatarStore:
    def __init__(self, data_dir: Path) -> None:
        self._dir = data_dir  # 首次 put 时创建

    def put(self, data: bytes) -> str:
        avatar_id = avatar_id_for(data)
        path = self._dir / avatar_id
        if path.exists():
            return avatar_id  # 内容寻址：已存在即幂等，不重写
        self._dir.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self._dir, suffix=".tmp")
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(data)
            os.replace(tmp, path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
        return avatar_id

    def path_for(self, avatar_id: str) -> Path | None:
        check_avatar_id(avatar_id)
        path = self._dir / avatar_id
        return path if path.is_file() else None
```

- [ ] **Step 8: 跑测试 + 门禁**

Run: `cd backend && uv run pytest tests/test_avatar_store.py tests/test_agent_profile.py -q && uv run ruff check . && uv run ruff format . && uv run mypy app`
Expected: 全 PASS，ruff/mypy 干净

- [ ] **Step 9: 提交**

```bash
git add backend/app/agent/profile.py backend/app/runtime/avatar_store.py backend/tests/test_agent_profile.py backend/tests/test_avatar_store.py
git commit -m "feat(runtime): AgentProfile.avatar 字段与内容寻址 AvatarStore (issue #102)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 2: 后端 —— 头像上传/读取端点 + `GET /games/{id}/avatars`

**Files:**
- Create: `backend/app/api/avatars.py`
- Modify: `backend/app/main.py:30-81`（`avatars_dir` / `avatar_store` 参数、`app.state.avatar_store`、挂路由）
- Modify: `backend/app/api/rest.py`（`meta_endpoint` 之后加 `avatars_endpoint`）
- Test: `backend/tests/test_api_avatars.py`（新建）

**Interfaces:**
- Consumes: Task 1 的 `AvatarStore` / `MAX_AVATAR_BYTES` / `UnsupportedImageError` / `profile_for`。
- Produces: `PUT /api/v1/avatars`（raw body）→ `200 {"avatar_id": str, "bytes": int}`；`GET /api/v1/avatars/{avatar_id}` → 图片；
  `GET /api/v1/games/{game_id}/avatars` → `dict[str, str]`（座位号字符串 → avatar_id，只含有头像的座位）；
  `create_app(avatars_dir: Path | None = None, avatar_store: AvatarStore | None = None)`。

- [ ] **Step 1: 写失败测试**

新建 `backend/tests/test_api_avatars.py`：

```python
"""头像端点（issue #102）：上传魔数/大小校验、内容寻址读取、对局座位头像映射。"""

import time

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.runtime.agent_library import InMemoryAgentLibrary
from app.runtime.avatar_store import InMemoryAvatarStore
from app.runtime.game_runner import RunnerTimeouts
from app.store.event_store import InMemoryEventStore

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
JPG = b"\xff\xd8\xff\xe0" + b"\x00" * 64


@pytest.fixture()
def client() -> TestClient:
    app = create_app(
        store=InMemoryEventStore(),
        agent_library=InMemoryAgentLibrary(),
        avatar_store=InMemoryAvatarStore(),
        timeouts=RunnerTimeouts(speech_sec=0.5, action_sec=0.5),
    )
    return TestClient(app)


def _put(client: TestClient, data: bytes, ctype: str = "image/png"):  # type: ignore[no-untyped-def]
    return client.put("/api/v1/avatars", content=data, headers={"Content-Type": ctype})


def test_upload_and_fetch_roundtrip(client: TestClient) -> None:
    r = _put(client, PNG)
    assert r.status_code == 200, r.text
    aid = r.json()["avatar_id"]
    assert aid.endswith(".png") and r.json()["bytes"] == len(PNG)
    assert _put(client, PNG).json()["avatar_id"] == aid  # 幂等
    assert _put(client, JPG, "image/jpeg").json()["avatar_id"].endswith(".jpg")
    g = client.get(f"/api/v1/avatars/{aid}")
    assert g.status_code == 200 and g.content == PNG
    assert g.headers["content-type"] == "image/png"
    assert "immutable" in g.headers["cache-control"]


def test_upload_rejects_bad_type_and_size(client: TestClient) -> None:
    assert _put(client, b"plain text here", "image/png").status_code == 415
    assert _put(client, b"GIF89a" + b"\x00" * 64, "image/gif").status_code == 415
    too_big = PNG + b"\x00" * (512 * 1024)
    assert _put(client, too_big).status_code == 413
    assert _put(client, b"").status_code == 415


def test_fetch_missing_or_illegal_id_404(client: TestClient) -> None:
    assert client.get("/api/v1/avatars/0000000000000000.png").status_code == 404
    assert client.get("/api/v1/avatars/..%2Fsecret.png").status_code == 404
    assert client.get("/api/v1/avatars/abc.gif").status_code == 404


def test_game_avatars_map_live_and_finished(client: TestClient) -> None:
    """建局时带头像的档案 → 直播中任意本局 token 可取映射；终局后匿名可取（公开策略同 /replay）。"""
    aid = _put(client, PNG).json()["avatar_id"]
    body = client.post(
        "/api/v1/games",
        json={
            "preset": "std_9_kill_side",
            "config_override": {"seed": 1},
            "agents": {"0": {"model": "x", "avatar": aid}, "1": {"model": "x"}},
        },
    ).json()
    gid = body["game_id"]
    assert client.get(f"/api/v1/games/{gid}/avatars").status_code == 401  # 未终局匿名不可
    spect = {"Authorization": f"Bearer {body['spectator_token']}"}
    r = client.get(f"/api/v1/games/{gid}/avatars", headers=spect)
    assert r.status_code == 200 and r.json() == {"0": aid}
    # 开局（档案 model=x 不会真调 LLM：registry 未配 agent_port_factory 时该座位仍是 RandomBot
    # —— 这里只验映射来源切到 GameMeta.agents 后仍一致）
    client.post(
        f"/api/v1/games/{gid}/start", json={}, headers={"Authorization": f"Bearer {body['host_token']}"}
    )
    handle = client.app.state.games.get(gid)  # type: ignore[attr-defined]
    deadline = time.time() + 30
    while not (handle.task is not None and handle.task.done()) and time.time() < deadline:
        time.sleep(0.05)
    assert handle.task is not None and handle.task.done()
    assert client.get(f"/api/v1/games/{gid}/avatars").json() == {"0": aid}  # 终局匿名
    assert client.get("/api/v1/games/g_nope/avatars").status_code == 404
```

注意：若 `agents` 带 `model="x"` 导致 `create` 校验失败（provider/model 校验），把 `"model"` 改成现有测试里用的占位值（看 `tests/test_api_agents.py` / `test_registry.py` 里 `create(... agents=...)` 的写法）；若默认 `agent_port_factory` 会为带档案座位建真 LLM 端口而导致开局崩溃，则改用 `create_app(agent_port_factory=lambda seat, handle: RandomBot 端口)`——参考 `tests/test_registry.py` 的 `_registry(agent_port_factory=...)` 与 `app.cli.bot` 里的随机端口实现。

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && uv run pytest tests/test_api_avatars.py -q`
Expected: FAIL（`create_app` 不接受 `avatar_store`）

- [ ] **Step 3: 写路由**

新建 `backend/app/api/avatars.py`：

```python
"""头像端点（issue #102）。上传：raw body（不用 multipart，免 python-multipart 依赖）；
读取：内容寻址，可永久缓存。无鉴权——头像随 /meta 对已终局对局公开，不是秘密。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

from app.runtime.avatar_store import MAX_AVATAR_BYTES, AvatarStore, UnsupportedImageError

router = APIRouter(prefix="/avatars", tags=["avatars"])

_MEDIA = {"png": "image/png", "jpg": "image/jpeg", "webp": "image/webp"}


def get_avatar_store(request: Request) -> AvatarStore:
    store: AvatarStore = request.app.state.avatar_store
    return store


@router.put("")
async def upload_avatar(request: Request) -> dict[str, object]:
    """PUT raw 图片字节 → {avatar_id, bytes}。超 512 KB → 413；魔数不是 PNG/JPEG/WebP → 415。"""
    length = request.headers.get("content-length")
    if length is not None and length.isdecimal() and int(length) > MAX_AVATAR_BYTES:
        raise HTTPException(status_code=413, detail=f"头像不能超过 {MAX_AVATAR_BYTES // 1024} KB")
    data = bytearray()
    async for chunk in request.stream():
        data.extend(chunk)
        if len(data) > MAX_AVATAR_BYTES:
            raise HTTPException(status_code=413, detail=f"头像不能超过 {MAX_AVATAR_BYTES // 1024} KB")
    try:
        avatar_id = get_avatar_store(request).put(bytes(data))
    except UnsupportedImageError as exc:
        raise HTTPException(status_code=415, detail=str(exc)) from exc
    return {"avatar_id": avatar_id, "bytes": len(data)}


@router.get("/{avatar_id}")
def fetch_avatar(avatar_id: str, request: Request) -> FileResponse:
    try:
        path = get_avatar_store(request).path_for(avatar_id)
    except ValueError:
        path = None  # 非法 id 与不存在同样 404，不回显校验信息
    if path is None:
        raise HTTPException(status_code=404, detail="头像不存在")
    return FileResponse(
        path,
        media_type=_MEDIA[avatar_id.rsplit(".", 1)[1]],
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )
```

- [ ] **Step 4: 装配 `create_app`**

`backend/app/main.py`：
- import：`from app.api import agents, avatars, providers, rest, ws` 与 `from app.runtime.avatar_store import AvatarStore, FileAvatarStore`。
- 签名加 `avatars_dir: Path | None = None, avatar_store: AvatarStore | None = None,`（放在 `provider_probe` 之后）。
- `app.state.agent_library = ...` 之后加：

```python
    # 头像存储（issue #102）：内容寻址，首次上传建目录
    app.state.avatar_store = avatar_store or FileAvatarStore(avatars_dir or Path("data/avatars"))
```
- `app.include_router(providers.router, prefix="/api/v1")` 之后加 `app.include_router(avatars.router, prefix="/api/v1")`。

- [ ] **Step 5: `GET /games/{game_id}/avatars`**

`backend/app/api/rest.py`，`meta_endpoint` 之后：

```python
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
    out: dict[str, str] = {}
    for seat in range(num_players):
        p = profile_for(agents, seat)
        if p is not None and p.avatar is not None:
            out[str(seat)] = p.avatar
    return out
```

补 import：`from app.agent.profile import AgentProfiles, profile_for`（`app.agent.profile` 不含 litellm，registry 已在 import 它）。

- [ ] **Step 6: 跑测试 + 门禁**

Run: `cd backend && uv run pytest tests/test_api_avatars.py tests/test_api_history.py tests/test_agent_profile.py -q && uv run ruff check . && uv run ruff format . && uv run mypy app`
Expected: 全 PASS；`test_importing_registry_does_not_load_litellm` 仍 PASS

- [ ] **Step 7: 提交**

```bash
git add backend/app/api/avatars.py backend/app/api/rest.py backend/app/main.py backend/tests/test_api_avatars.py
git commit -m "feat(api): PUT/GET /avatars 头像上传读取；GET /games/{id}/avatars 座位头像映射 (issue #102)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 3: 前端 —— `Avatar` 组件、上传 API、档案编辑器与档案卡

**Files:**
- Create: `frontend/src/api/avatars.ts`
- Create: `frontend/src/components/Avatar/Avatar.tsx`、`Avatar.module.css`、`Avatar.test.tsx`
- Modify: `frontend/src/api/agents.ts:10-21`（`avatar?: string | null`）
- Modify: `frontend/src/components/AgentEditor/AgentEditor.tsx`（FormState.avatar、头像区、submit）
- Modify: `frontend/src/components/AgentCard/AgentCard.tsx`（名字前小头像，compact 与完整版都加）
- Test: `frontend/src/components/AgentEditor/AgentEditor.test.tsx`（追加）

**Interfaces:**
- Consumes: Task 2 的 `PUT /api/v1/avatars`、`GET /api/v1/avatars/{id}`。
- Produces: `uploadAvatar(file: File): Promise<{avatar_id: string; bytes: number}>`、`avatarUrl(id: string): string`、`MAX_AVATAR_BYTES = 512 * 1024`；
  `<Avatar avatar={string|null} name={string} seat={number|null} size={number} color?={string} />`。

- [ ] **Step 1: 写 `Avatar` 的失败测试**

`frontend/src/components/Avatar/Avatar.test.tsx`：

```tsx
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import Avatar from "./Avatar";

describe("Avatar", () => {
  it("有 id 渲染 img，指向 /api/v1/avatars/{id}", () => {
    render(<Avatar avatar="3f9a1c0b7e2d4a66.png" name="夜枭" seat={3} size={40} />);
    const img = screen.getByRole("img", { name: /夜枭/ });
    expect(img).toHaveAttribute("src", "/api/v1/avatars/3f9a1c0b7e2d4a66.png");
  });
  it("无 id 渲染名字首字占位；空名用座位号", () => {
    render(<Avatar avatar={null} name="夜枭" seat={3} size={40} />);
    expect(screen.getByText("夜")).toBeInTheDocument();
    render(<Avatar avatar={null} name="" seat={5} size={40} />);
    expect(screen.getByText("5")).toBeInTheDocument();
  });
  it("img 加载失败退回占位", () => {
    render(<Avatar avatar="3f9a1c0b7e2d4a66.png" name="夜枭" seat={3} size={40} />);
    fireEvent.error(screen.getByRole("img"));
    expect(screen.queryByRole("img")).toBeNull();
    expect(screen.getByText("夜")).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd frontend && npx vitest run src/components/Avatar`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 实现 API 与组件**

`frontend/src/api/avatars.ts`：

```ts
// 头像上传/引用（issue #102）：PUT raw 字节；读取走内容寻址 URL，可永久缓存。

import { API_BASE, ApiError } from "./rest";

export const MAX_AVATAR_BYTES = 512 * 1024;
export const AVATAR_ACCEPT = "image/png,image/jpeg,image/webp";

export interface AvatarUpload {
  avatar_id: string;
  bytes: number;
}

export function avatarUrl(avatarId: string): string {
  return `${API_BASE}/avatars/${avatarId}`;
}

export async function uploadAvatar(file: File): Promise<AvatarUpload> {
  const res = await fetch(`${API_BASE}/avatars`, {
    method: "PUT",
    headers: { "Content-Type": file.type || "application/octet-stream" },
    body: file,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      detail = ((await res.json()) as { detail?: string }).detail ?? detail;
    } catch {
      /* 非 JSON 错误体 */
    }
    throw new ApiError(res.status, detail);
  }
  return (await res.json()) as AvatarUpload;
}
```

确认 `rest.ts` 导出 `API_BASE` 与 `ApiError(status, detail)`；若 `API_BASE` 未导出，导出它（不改值）。

`frontend/src/components/Avatar/Avatar.tsx`：

```tsx
// 头像（issue #102）：有 id 渲染 <img>（object-fit: cover，失败退占位）；无 id → 名字首字 + 座位色。
// 零过滤：id 来自服务端（档案或 /games/{id}/avatars），组件不做任何判断。

import { useState } from "react";
import { avatarUrl } from "../../api/avatars";
import styles from "./Avatar.module.css";

export interface AvatarProps {
  avatar: string | null;
  name: string;
  seat: number | null;
  size: number;
  /** 占位底色（CSS 颜色/变量）；缺省按座位号取一组柔和色。 */
  color?: string;
}

const PALETTE = ["#6c8cff", "#ff8c6c", "#5fbf8f", "#d98cff", "#ffc44d", "#4dc9d9", "#ff6ca8", "#8fa3b8"];

export function placeholderText(name: string, seat: number | null): string {
  const t = name.trim();
  if (t !== "") return Array.from(t)[0] as string;
  return seat === null ? "?" : String(seat);
}

export default function Avatar({ avatar, name, seat, size, color }: AvatarProps): JSX.Element {
  const [broken, setBroken] = useState(false);
  const dim = { width: size, height: size, fontSize: Math.round(size * 0.42) };
  if (avatar !== null && !broken) {
    return (
      <img
        className={styles.img}
        style={dim}
        src={avatarUrl(avatar)}
        alt={name || (seat !== null ? `${seat}号` : "头像")}
        onError={() => setBroken(true)}
      />
    );
  }
  const bg = color ?? PALETTE[seat === null ? 7 : seat % PALETTE.length];
  return (
    <span className={styles.placeholder} style={{ ...dim, background: bg }} aria-hidden="true">
      {placeholderText(name, seat)}
    </span>
  );
}
```

`Avatar.module.css`：

```css
.img,
.placeholder {
  border-radius: 50%;
  flex: none;
  display: inline-grid;
  place-items: center;
}
.img {
  object-fit: cover;
  background: var(--color-surface);
}
.placeholder {
  color: #fff;
  font-weight: 600;
  line-height: 1;
  user-select: none;
}
```

`frontend/src/api/agents.ts` 的 `AgentProfile` 加 `avatar?: string | null;`（放在 `provider` 之后）。

- [ ] **Step 4: 跑 Avatar 测试通过**

Run: `cd frontend && npx vitest run src/components/Avatar`
Expected: PASS

- [ ] **Step 5: 写 AgentEditor 的失败测试**

在 `frontend/src/components/AgentEditor/AgentEditor.test.tsx` 追加（沿用该文件现有的 render 辅助与 props；若现有测试用 `vi.stubGlobal("fetch", …)`，照同样方式 stub）：

```tsx
it("头像：上传成功写入 profile.avatar；超 512 KB 不发请求并提示（issue #102）", async () => {
  const fetchMock = vi.fn(
    async () =>
      new Response(JSON.stringify({ avatar_id: "3f9a1c0b7e2d4a66.png", bytes: 10 }), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
  );
  vi.stubGlobal("fetch", fetchMock);
  const onSave = vi.fn();
  renderEditor({ onSave }); // 用文件里现有的渲染辅助（名字/模型已填好，保存按钮可点）
  const input = screen.getByLabelText(/上传头像/) as HTMLInputElement;
  const big = new File([new Uint8Array(512 * 1024 + 1)], "big.png", { type: "image/png" });
  fireEvent.change(input, { target: { files: [big] } });
  expect(await screen.findByText(/不能超过 512 KB/)).toBeInTheDocument();
  expect(fetchMock).not.toHaveBeenCalled();
  const ok = new File([new Uint8Array(10)], "a.png", { type: "image/png" });
  fireEvent.change(input, { target: { files: [ok] } });
  await waitFor(() => expect(screen.getByRole("img", { name: /头像|夜枭/ })).toBeInTheDocument());
  fireEvent.click(screen.getByRole("button", { name: /保存|创建/ }));
  expect(onSave).toHaveBeenCalledWith(expect.objectContaining({ avatar: "3f9a1c0b7e2d4a66.png" }));
  fireEvent.click(screen.getByRole("button", { name: /移除头像/ }));
  expect(screen.queryByRole("img")).toBeNull();
});
```

把 `renderEditor`、保存按钮文案、`fireEvent`/`waitFor`/`vi` import 对齐到该测试文件现有写法。

- [ ] **Step 6: 跑测试确认失败**

Run: `cd frontend && npx vitest run src/components/AgentEditor`
Expected: 新用例 FAIL（找不到「上传头像」）

- [ ] **Step 7: 改 AgentEditor**

`FormState` 加 `avatar: string | null;`，`initialForm` 里 `avatar: p?.avatar ?? null,`；`submit()` 的 `profile` 加 `avatar: form.avatar,`。
新增 state `const [avatarNotice, setAvatarNotice] = useState<string | null>(null);` 与处理函数：

```tsx
  async function onAvatarFile(e: React.ChangeEvent<HTMLInputElement>): Promise<void> {
    const file = e.target.files?.[0];
    e.target.value = ""; // 同一文件可重选
    if (!file) return;
    if (file.size > MAX_AVATAR_BYTES) {
      setAvatarNotice(`头像不能超过 ${MAX_AVATAR_BYTES / 1024} KB`);
      return;
    }
    setAvatarNotice(null);
    try {
      const up = await uploadAvatar(file);
      setForm((f) => ({ ...f, avatar: up.avatar_id }));
    } catch (err) {
      setAvatarNotice(err instanceof ApiError ? err.detail : String(err));
    }
  }
```

表单顶部（名字字段之前）加头像区：

```tsx
          <div className={styles.field}>
            <span className={styles.label}>头像</span>
            <div className={styles.avatarRow}>
              <Avatar avatar={form.avatar} name={nameTrimmed} seat={null} size={56} />
              <label className="btn btn-secondary" htmlFor={`${uid}-avatar`}>
                上传头像
                <input
                  id={`${uid}-avatar`}
                  type="file"
                  accept={AVATAR_ACCEPT}
                  hidden
                  onChange={(e) => void onAvatarFile(e)}
                />
              </label>
              {form.avatar !== null && (
                <button
                  type="button"
                  className="btn btn-ghost"
                  onClick={() => setForm((f) => ({ ...f, avatar: null }))}
                >
                  移除头像
                </button>
              )}
              <span className="text-muted" style={{ fontSize: 12 }}>
                PNG / JPEG / WebP，≤ 512 KB，建议正方形
              </span>
            </div>
            {avatarNotice !== null && <div className={styles.error}>{avatarNotice}</div>}
          </div>
```

`<label htmlFor>` 包 `<input hidden>`：`getByLabelText(/上传头像/)` 能命中 input。`AgentEditor.module.css` 加 `.avatarRow { display:flex; align-items:center; gap: var(--space-3); flex-wrap: wrap; }`；`.field`/`.label`/`.error` 若文件里已有同名类则复用，没有则按相邻字段的类名改。
import：`import Avatar from "../Avatar/Avatar";`、`import { AVATAR_ACCEPT, MAX_AVATAR_BYTES, uploadAvatar } from "../../api/avatars";`、`import { ApiError } from "../../api/rest";`。

- [ ] **Step 8: AgentCard 小头像**

`AgentCard.tsx` 两处名字前加 `<Avatar avatar={p.avatar ?? null} name={p.name ?? ""} seat={null} size={compact ? 22 : 32} />`（compact 的 `compactHead`、完整版的 `.name` 所在容器），容器保证 `display:flex; align-items:center; gap:6px`（在 `AgentCard.module.css` 里给对应类补 flex，若已是 flex 不改）。

- [ ] **Step 9: 跑全套检查**

Run: `cd frontend && npm run check`
Expected: eslint / tsc / vitest 全绿（`SeatAssignment.test.tsx` 等现有测试不受影响）

- [ ] **Step 10: 提交**

```bash
git add frontend/src/api/avatars.ts frontend/src/api/agents.ts frontend/src/components/Avatar frontend/src/components/AgentEditor frontend/src/components/AgentCard
git commit -m "feat(frontend): Avatar 组件；档案编辑器上传/移除头像；档案卡显示头像 (issue #102)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 4: 前端 —— 对局页头像（座位环、发言卡）+ 文档

**Files:**
- Modify: `frontend/src/api/rest.ts`（`getGameAvatars`）
- Modify: `frontend/src/pages/GamePage.tsx`（引导后拉 `/avatars`，传给两个组件）
- Modify: `frontend/src/components/SeatCircle/SeatCircle.tsx` + `.module.css`（圆片用 `<Avatar>`，缩写缩成角标）
- Modify: `frontend/src/components/SpeechFeed/SpeechFeed.tsx` + `.module.css`（发言卡头部头像）
- Test: `SeatCircle.test.tsx`、`SpeechFeed.test.tsx`、`src/api/rest.test.ts`（追加）
- Docs: `README.md`（Agent 档案段落一句）、`docs/specs/requirements.md` §5.2 两行

**Interfaces:**
- Consumes: Task 2 `GET /games/{id}/avatars`；Task 3 `<Avatar>`。
- Produces: `getGameAvatars(gameId: string, token?: string): Promise<Record<string, string>>`；
  `SeatCircleProps.avatars?: Record<number, string>`；`SpeechFeedProps.avatars?: Record<number, string>`（缺省 `{}`）。

- [ ] **Step 1: 写失败测试**

`frontend/src/api/rest.test.ts` 追加（对齐文件里 `getMeta` 的测试写法）：

```ts
it("getGameAvatars：有 token 带 Authorization，无 token 不带", async () => {
  const fetchMock = vi.fn(async () => new Response(JSON.stringify({ "0": "a.png" }), { status: 200, headers: { "content-type": "application/json" } }));
  vi.stubGlobal("fetch", fetchMock);
  expect(await getGameAvatars("g_x", "tok")).toEqual({ "0": "a.png" });
  expect((fetchMock.mock.calls[0] as unknown as [string, RequestInit])[1].headers).toMatchObject({ Authorization: "Bearer tok" });
  await getGameAvatars("g_x");
  expect((fetchMock.mock.calls[1] as unknown as [string, RequestInit])[1].headers).not.toHaveProperty("Authorization");
});
```

`SeatCircle.test.tsx` 追加：

```tsx
it("有头像的座位渲染 img，其余占位首字；角色缩写仍按 state 显示（零过滤）", () => {
  render(
    <SeatCircle state={finalState} speaking={null} votes={{}} nightLines={[]} avatars={{ 0: "3f9a1c0b7e2d4a66.png" }} />,
  );
  const imgs = screen.getAllByRole("img");
  expect(imgs).toHaveLength(1);
  expect(imgs[0]).toHaveAttribute("src", "/api/v1/avatars/3f9a1c0b7e2d4a66.png");
  // 现有「角色缩写」断言不变：已知角色时每个座位仍有缩写角标
  expect(screen.queryAllByText("?")).toHaveLength(0);
});
```

现有 `getAllByText("?")` 用例保持（未知角色时角标显示 `?`，数量 = 玩家数）。

`SpeechFeed.test.tsx` 追加一个用例：传 `avatars={{ [seat]: "3f9a1c0b7e2d4a66.png" }}` 后该发言卡内出现 `img`，其它卡是占位（`queryAllByRole("img")` 长度 = 该座位发言条数）。

- [ ] **Step 2: 跑测试确认失败**

Run: `cd frontend && npx vitest run src/api/rest.test.ts src/components/SeatCircle src/components/SpeechFeed`
Expected: 新用例 FAIL

- [ ] **Step 3: API + GamePage**

`rest.ts`：

```ts
/** 座位 → 头像 id（issue #102）：直播中需本局 token；终局公开策略同 /replay。 */
export function getGameAvatars(gameId: string, token?: string): Promise<Record<string, string>> {
  return req<Record<string, string>>("GET", `/games/${gameId}/avatars`, { token });
}
```

`GamePage.tsx`：`const [avatars, setAvatars] = useState<Record<number, string>>({});`；在引导 effect 里，**三条路径**（replay 无 token、终局 /meta、直播 /state）加载成功后都调用：

```ts
      getGameAvatars(gameId, token || undefined)
        .then((m) => {
          if (!cancelled) setAvatars(Object.fromEntries(Object.entries(m).map(([k, v]) => [Number(k), v])));
        })
        .catch(() => {
          /* 头像拿不到只是没图：不阻断对局页 */
        });
```

（`cancelled` 用 effect 现有的清理标志；若没有，按现有写法加。）然后 `<SeatCircle … avatars={avatars} />`、`<SpeechFeed … avatars={avatars} />`。

- [ ] **Step 4: SeatCircle**

Props 加 `avatars?: Record<number, string>;`，解构默认 `avatars = {}`。圆片改为：

```tsx
              <div
                className={`${styles.disc} ${isSpeaking ? styles.speaking : ""}`}
                style={{ borderColor: color }}
              >
                <Avatar
                  avatar={avatars[p.seat] ?? null}
                  name={p.display_name}
                  seat={p.seat}
                  size={42}
                  color={known ? `color-mix(in srgb, ${color} 55%, var(--color-surface))` : undefined}
                />
                <span className={styles.abbr} style={{ color, borderColor: color }}>
                  {abbr}
                </span>
                {/* 警长 ★ / 痴 / ✕ / 票数 四个角标原样保留 */}
```

CSS：`.disc` 去掉 `display:grid; place-items:center`，改 `overflow: visible`；`.abbr` 改为左下角小角标：

```css
.abbr {
  position: absolute;
  bottom: -5px;
  left: -5px;
  min-width: 16px;
  height: 16px;
  padding: 0 3px;
  border-radius: 8px;
  border: 1px solid;
  background: var(--color-bg);
  font-size: 10px;
  font-weight: 600;
  display: grid;
  place-items: center;
}
```

`.idiot` 原本在左下（`bottom:-6px; left:-8px`）——改到左上 `top:-6px; left:-8px` 避免与缩写角标重叠。import `Avatar`。

- [ ] **Step 5: SpeechFeed**

Props 加 `avatars?: Record<number, string>`（默认 `{}`）。`.who` 里在座位号上方加 `<Avatar avatar={seat !== null ? (avatars[seat] ?? null) : null} name={seat !== null ? (nameOf.get(seat) ?? "") : ""} seat={seat} size={36} />`；`.card` 第一列已是 58px，`.who` 保持纵向排列（头像、座位号、名字）。import `Avatar`。

- [ ] **Step 6: 跑全套检查**

Run: `cd frontend && npm run check && npm run build`
Expected: 全绿

- [ ] **Step 7: 文档**

- `README.md` Agent 档案 / 档案库段落加一句：「档案可上传头像（PNG/JPEG/WebP ≤ 512 KB，存 `backend/data/avatars/`，内容寻址），座位环与发言卡显示；无头像显示名字首字（issue #102）。」
- `docs/specs/requirements.md` §5.2 端点表加两行：
  `| PUT | /api/v1/avatars | 上传头像（raw body，PNG/JPEG/WebP ≤512 KB，魔数校验）→ {avatar_id}，内容寻址幂等（issue #102） |`
  `| GET | /api/v1/avatars/{avatar_id} | 读取头像，immutable 缓存；不鉴权 |`
  `| GET | /api/v1/games/{game_id}/avatars | 座位 → 头像 id；直播中需本局 token，终局公开策略同 /replay（issue #102） |`
  并在 `AgentProfile` 字段说明处（§2.3 或档案小节）加 `avatar`。

- [ ] **Step 8: 提交**

```bash
git add frontend/src/api/rest.ts frontend/src/api/rest.test.ts frontend/src/pages/GamePage.tsx frontend/src/components/SeatCircle frontend/src/components/SpeechFeed README.md docs/specs/requirements.md
git commit -m "feat(frontend): 对局页座位环与发言卡显示头像（GET /games/{id}/avatars）；文档 (issue #102)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

## 自检

- 规格覆盖：§2 `avatar` 字段（T1）、§3.1 端点/存储（T1、T2）、§3.2 前端五处显示（T3 档案卡+编辑器、T4 座位环+发言卡；`SeatAssignment` 用的是 `AgentCard compact`，T3 已覆盖）、直播/回放同一取图路径（T2 新端点 + T4）、§3.3 测试（各任务）、§5 安全（id 正则、不挂 StaticFiles、不鉴权只限公开内容）、§6 兼容（字段默认 None）。
- 类型一致：`avatar_id` 形状 `^[0-9a-f]{16}\.(png|jpg|webp)$` 在 T1 常量、T2 404 分支、T3/T4 测试样例中一致；`Record<number,string>` 由 GamePage 把服务端 `Record<string,string>` 的键转数字后传下。
- 占位符扫描：无 TBD；T2 Step 1 对 `agents.model` 占位值与 `agent_port_factory` 的说明是明确的回退指令，不是留白。
