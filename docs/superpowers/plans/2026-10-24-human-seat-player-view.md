# 真人入座与 Web 玩家视角 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 登录用户在 Lobby 给自己留一个座位，建局后直接进入玩家视角亲自打一局：轮到自己时在页面上发言 / 投票 / 夜间行动 / 竞选警长；对局进行中建局者的上帝视角被服务端封死。

**Architecture:** 后端只改 runtime + api 两层：`GameLobby` 支持指定座位，`GameHandle.seat_users` 把座位绑定到账号，`_session_viewer` / `resolve_viewer` 在「建局者已入座且未终局」时把 owner 的 cookie 解析成 PLAYER、拒绝 GM token；`/state` `/meta` 响应回传 `viewer`。前端同一 GamePage、同一 reducer：`Viewer` 加座位号，新增 `turn` store 消费 `your_turn` / `action_result` 帧，新增 `ActionBar` 组件按 `available_tools` 渲染；Lobby 新增「我自己」座位并编排 create → join → start。引擎零改动。

**Tech Stack:** Python 3.11 / FastAPI / Pydantic v2 / pytest（后端，uv）；React 18 / TypeScript strict / Zustand / Vitest + Testing Library（前端）。

**Spec:** `docs/superpowers/specs/2026-10-23-human-seat-player-view-design.md`

## Global Constraints

- `backend/app/engine` 零 diff；`frontend/src/engine/__fixtures__/*.json` 不变（任务 12 用 `git diff --stat` 核验）。
- 前端零信息过滤：所有可见性裁剪由服务端按视角决定；前端只渲染服务端给的字段，不做任何合法性裁决（只做「必须选目标」这类输入形态校验）。
- `app/runtime` `app/api` `app/cli` 不得在模块级 import `app.agent.agent_player` / `app.agent.llm_client`；守卫 `tests/test_agent_profile.py::test_importing_registry_does_not_load_litellm`。
- 密钥、`password_hash`、`session_id`、验证码永不进响应或日志。
- 后端门禁（在 `backend/` 下）：`uv run ruff check . && uv run ruff format --check . && uv run mypy app && uv run pytest -q --ignore=tests/test_api_e2e.py`（e2e 单独跑，已知 flaky `test_acceptance_human_can_take_any_seat[5]` #74 可忽略超时）。ruff 行宽 100。
- 前端门禁（在 `frontend/` 下）：`npm run check`（lint + tsc + vitest）。
- 文档与注释中文，标识符 / API / schema 英文。提交信息格式 `type(scope): 中文摘要 (issue #115)`，结尾 `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`。
- 文案常量：GM 封锁 403 detail 为 `建局者已入座，对局结束前不能查看上帝视角`；重复入座 409 detail 为 `你已入座 {seat} 号`；座位冲突 `座位 {seat} 已被占用`；越界 `座位号越界：{seat}（0–{n-1}）`。
- 有「我自己」座位时 Lobby 默认 `speech_timeout_sec=120`、`action_timeout_sec=60`，可改。

## Review Focus

1. **断线重连时正在自己的回合**：服务端重推当前 prompt，前端 `turn.prompt` 必须重新出现（任务 7 `ws.test.ts` 加「重连后再次收到 your_turn 覆盖 prompt」）。
2. **客户端时钟比服务端快，prompt 到达时 deadline 已过**：ActionBar 不得把提交按钮锁死（否则真人永远不能行动），只显示「可能已超时」提示，让服务端用 `action_result` / `error` 帧裁决（任务 9 测试「deadline 已过仍可提交」）。这是对 spec §4.4「到 0 禁用输入」的修正，理由如上，记入 ledger。
3. **投票没选目标就点提交**：不得发出空票面（后端会 400 `vote 需要显式 target_seat 或 abstain=true`）；提交按钮在未选目标且未选弃票时禁用（任务 9 测试）。
4. **建局者同时是 admin 并入座**：cookie 解析为 PLAYER 而不是 GM——正在打的人不该因为角色是 admin 就看到全局（任务 4 测试 `test_admin_owner_seated_is_player`）。
5. **join 成功、start 失败后留下未开局的半成品**：DELETE 必须能删掉未开局对局，否则 Lobby 的「删除这局」按钮点了 409（任务 3 测试 `test_delete_unstarted_game`）。

## 文件结构

后端（`backend/`）：
- `app/runtime/game_runner.py`：`GameLobby` 改为座位字典，`join(seat=)`。
- `app/runtime/registry.py`：`GameHandle.seat_users` / `owner_seat()`；`GameRegistry.join(..., seat, user_id)`。
- `app/schemas/games.py`：`JoinRequest.seat`；`SpectatorView.viewer`。
- `app/api/rest.py`：`GM_LOCKED_MSG`、`_owner_locked()`、`_session_viewer` / `resolve_viewer` 改判、`/state` `/meta` 的 `viewer`、PLAYER `seats` 补 `display_name`、DELETE 允许未开局。
- `app/api/ws.py`：`?token=` 路径的 GM 封锁 4403。
- 测试：`tests/test_game_runner.py`、`tests/test_registry.py`、`tests/test_api_lobby.py`、新建 `tests/test_api_host_plays.py`。

前端（`frontend/src`）：
- `api/tokens.ts`：`?player=`；`ViewerHint`。
- `api/player.ts`（新）：`PlayerObservation` / `ToolCall` / `YourTurn` / `ActionResult` 类型。
- `api/rest.ts`：`joinGame`、`viewerFrom`、`MetaResponse`、`ViewerValue`。
- `store/game.ts`：`Viewer` 加 `number`。
- `store/turn.ts`（新）：回合切片。
- `api/ws.ts`：消费 `your_turn` / `action_result`，返回 `send`。
- `lib/toolCalls.ts`（新）：ToolCall 构造纯函数。
- `components/ActionBar/`（新）：`ActionBar.tsx` + `ActionBar.module.css`。
- `components/NightOverlay/NightOverlay.tsx`：座位视角分支。
- `components/PhaseBar/PhaseBar.tsx`：「玩家」标签。
- `components/SeatCircle/SeatCircle.tsx`：`me` 标记。
- `components/ErrorState/ErrorState.tsx`：`locked` 错误态。
- `pages/GamePage.tsx`：以服务端 `viewer` 为准；ActionBar；「我是 N 号」；终局按钮。
- `lib/seats.ts` + `components/SeatAssignment/SeatAssignment.tsx` + `pages/Lobby.tsx`：「我自己」座位与三步编排。
- `App.tsx`：传 `ViewerHint`。

文档：`README.md`、`docs/specs/requirements.md`。

---

### Task 1: GameLobby 支持指定座位

**Files:**
- Modify: `backend/app/runtime/game_runner.py:55-93`（`GameLobby`）
- Test: `backend/tests/test_game_runner.py:125-150`（`TestLobby`）

**Interfaces:**
- Consumes: 无。
- Produces: `GameLobby.join(display_name: str, player_type: Literal["HUMAN","AGENT"] = "HUMAN", seat: int | None = None) -> int`；`GameLobby.empty_seats() -> list[int]`；`fill_with_bots` / `roster` / `is_full` / `game_meta` 签名不变，语义改为按座位号。

- [ ] **Step 1: 写失败测试**

在 `backend/tests/test_game_runner.py` 的 `class TestLobby` 内追加：

```python
    def test_join_specific_seat_and_conflicts(self) -> None:
        cfg = build_preset("std_9_kill_side")
        lobby = GameLobby(cfg, game_id="g1")
        assert lobby.join("Alice", seat=4) == 4
        assert lobby.join("Bob") == 0  # 不指定 → 最小空位
        assert lobby.empty_seats() == [1, 2, 3, 5, 6, 7, 8]
        with pytest.raises(LobbyError, match="座位 4 已被占用"):
            lobby.join("Carol", seat=4)
        with pytest.raises(LobbyError, match="座位号越界：9（0–8）"):
            lobby.join("Carol", seat=9)
        with pytest.raises(LobbyError, match="座位号越界：-1"):
            lobby.join("Carol", seat=-1)
        lobby.fill_with_bots()
        assert lobby.is_full and lobby.empty_seats() == []
        roster = lobby.roster()
        assert roster[4].display_name == "Alice" and roster[4].player_type == "HUMAN"
        assert roster[0].display_name == "Bob"
        assert [e.display_name for e in roster[1:4]] == ["Bot1", "Bot2", "Bot3"]
        assert [e.display_name for e in roster[5:]] == ["Bot5", "Bot6", "Bot7", "Bot8"]

    def test_fill_with_bots_names_by_real_seat(self) -> None:
        cfg = build_preset("std_9_kill_side")
        lobby = GameLobby(cfg, game_id="g1")
        lobby.join("Alice", seat=2)
        lobby.fill_with_bots(name_for=lambda s: f"P{s}")
        assert [e.display_name for e in lobby.roster()] == [
            "P0", "P1", "Alice", "P3", "P4", "P5", "P6", "P7", "P8"
        ]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && uv run pytest tests/test_game_runner.py::TestLobby -q`
Expected: 2 failed（`join() got an unexpected keyword argument 'seat'`）。

- [ ] **Step 3: 实现**

把 `backend/app/runtime/game_runner.py` 的 `GameLobby` 整段替换为：

```python
class GameLobby:
    """建局前大厅：收集座位（真人 join / bot 填充），产出 roster 与 GameMeta。

    座位按号存字典（issue #115）：join 可指定座位，不指定取最小空位；fill_with_bots 填所有空位。
    """

    def __init__(self, config: GameConfig, game_id: str) -> None:
        self._config = config
        self._game_id = game_id
        self._entries: dict[int, RosterEntry] = {}

    @property
    def is_full(self) -> bool:
        return len(self._entries) >= self._config.num_players

    def empty_seats(self) -> list[int]:
        return [s for s in range(self._config.num_players) if s not in self._entries]

    def join(
        self,
        display_name: str,
        player_type: Literal["HUMAN", "AGENT"] = "HUMAN",
        seat: int | None = None,
    ) -> int:
        if self.is_full:
            raise LobbyError(f"对局已满员（{self._config.num_players} 座）")
        n = self._config.num_players
        if seat is None:
            seat = self.empty_seats()[0]
        elif not 0 <= seat < n:
            raise LobbyError(f"座位号越界：{seat}（0–{n - 1}）")
        elif seat in self._entries:
            raise LobbyError(f"座位 {seat} 已被占用")
        self._entries[seat] = RosterEntry(display_name=display_name, player_type=player_type)
        return seat

    def fill_with_bots(self, name_for: Callable[[int], str] | None = None) -> None:
        """填满空位；name_for(seat) 给出展示名（issue #56 档案名），缺省 Bot{seat}。"""
        for seat in self.empty_seats():
            name = name_for(seat) if name_for is not None else f"Bot{seat}"
            self._entries[seat] = RosterEntry(display_name=name, player_type="AGENT")

    def roster(self) -> tuple[RosterEntry, ...]:
        if not self.is_full:
            raise LobbyError(f"未满员：{len(self._entries)}/{self._config.num_players}")
        return tuple(self._entries[s] for s in range(self._config.num_players))

    def game_meta(
        self, agents: AgentProfiles | None = None, owner_id: str | None = None
    ) -> GameMeta:
        return GameMeta(
            game_id=self._game_id,
            config=self._config,
            roster=tuple(
                SeatName(seat=i, display_name=e.display_name) for i, e in enumerate(self.roster())
            ),
            agents=dict(agents or {}),
            owner_id=owner_id,
        )
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && uv run pytest tests/test_game_runner.py tests/test_registry.py -q && uv run ruff check app/runtime/game_runner.py && uv run mypy app`
Expected: 全部通过（原有 `test_join_assigns_seats_and_rejects_overflow` 依旧成立：顺序加入得 0、1）。

- [ ] **Step 5: 提交**

```bash
git add backend/app/runtime/game_runner.py backend/tests/test_game_runner.py
git commit -m "feat(runtime): GameLobby 座位改字典，join 可指定座位 (issue #115)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 2: GameHandle 绑定座位账号，registry.join 支持 seat / user_id

**Files:**
- Modify: `backend/app/runtime/registry.py:50-98`（`GameHandle`）、`:205-215`（`GameRegistry.join`）
- Test: `backend/tests/test_registry.py`

**Interfaces:**
- Consumes: Task 1 的 `GameLobby.join(..., seat=)`。
- Produces: `GameHandle.seat_users: dict[int, str | None]`；`GameHandle.owner_seat() -> int | None`；`GameRegistry.join(handle, display_name, player_type, *, seat: int | None = None, user_id: str | None = None) -> int`。

- [ ] **Step 1: 写失败测试**

在 `backend/tests/test_registry.py` 末尾追加（文件已有 `_registry()`、`build_preset`、`LobbyError`、`pytest` 导入；若 `_registry` 不接受 `owner_id`，用 `reg.create(cfg, allow_spectators=False, owner_id="u_owner")`——`create` 已有 `owner_id` 参数）：

```python
async def test_join_by_seat_binds_user_and_owner_seat() -> None:
    reg = _registry()
    cfg = build_preset("std_9_kill_side").model_copy(update={"seed": 7})
    handle = reg.create(cfg, allow_spectators=False, owner_id="u_owner")
    assert handle.owner_seat() is None
    assert reg.join(handle, "Alice", "HUMAN", seat=3, user_id="u_owner") == 3
    assert handle.seat_users == {3: "u_owner"}
    assert handle.owner_seat() == 3
    assert 3 in handle.human_ports and 3 in handle.ports
    with pytest.raises(LobbyError, match="你已入座 3 号"):
        reg.join(handle, "Alice again", "HUMAN", user_id="u_owner")
    with pytest.raises(LobbyError, match="座位 3 已被占用"):
        reg.join(handle, "Bob", "HUMAN", seat=3, user_id="u_bob")
    # 外部客户端（user_id=None）不受「同账号一座」约束，顺序分配
    assert reg.join(handle, "Ext", "AGENT") == 0
    assert reg.join(handle, "Ext2", "AGENT") == 1
    assert handle.seat_users[0] is None and handle.seat_users[1] is None
    assert handle.owner_seat() == 3


async def test_owner_seat_none_for_ownerless_game() -> None:
    reg = _registry()
    cfg = build_preset("std_9_kill_side").model_copy(update={"seed": 7})
    handle = reg.create(cfg, allow_spectators=False)
    reg.join(handle, "Alice", "HUMAN", seat=0, user_id="u_x")
    assert handle.owner_seat() is None  # 无主局永不封锁
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && uv run pytest tests/test_registry.py -q -k "owner_seat or join_by_seat"`
Expected: FAIL（`join() got an unexpected keyword argument 'seat'` / 无 `owner_seat`）。

- [ ] **Step 3: 实现**

`backend/app/runtime/registry.py`，`GameHandle.__init__` 在 `self.providers: dict[int, Provider] = {}` 之后加：

```python
        # 座位 → 入座账号（issue #115）：登录入座记 user_id，host_token 入座记 None；
        # owner_seat() 据此判定「建局者本人在打」→ 上帝视角封锁
        self.seat_users: dict[int, str | None] = {}
```

在 `profile_for` 方法之前加：

```python
    def owner_seat(self) -> int | None:
        """建局者本人入座的座位（issue #115）；未入座或无主局 → None。"""
        if self.owner_id is None:
            return None
        for seat, uid in self.seat_users.items():
            if uid == self.owner_id:
                return seat
        return None
```

把 `GameRegistry.join` 替换为：

```python
    def join(
        self,
        handle: GameHandle,
        display_name: str,
        player_type: Literal["HUMAN", "AGENT"],
        *,
        seat: int | None = None,
        user_id: str | None = None,
    ) -> int:
        """经 API 加入的座位（真人或外部 Agent）一律配 HumanPlayerPort —— 同一玩家 API。

        seat=None 顺序分配；user_id 非空时同一账号在同一局只能占一个座位（issue #115）。
        """
        if handle.started:
            raise LobbyError("对局已开始，无法加入")
        if user_id is not None:
            for taken, uid in handle.seat_users.items():
                if uid == user_id:
                    raise LobbyError(f"你已入座 {taken} 号")
        seat = handle.lobby.join(display_name, player_type, seat=seat)
        port = HumanPlayerPort()
        handle.human_ports[seat] = port
        handle.ports[seat] = port
        handle.seat_users[seat] = user_id
        return seat
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && uv run pytest tests/test_registry.py tests/test_game_runner.py -q && uv run ruff check app && uv run mypy app`
Expected: 全部通过。

- [ ] **Step 5: 提交**

```bash
git add backend/app/runtime/registry.py backend/tests/test_registry.py
git commit -m "feat(runtime): 座位绑定账号 seat_users/owner_seat，join 支持指定座位与同账号去重 (issue #115)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 3: API —— join 指定座位、/state 与 /meta 回传 viewer、允许删除未开局对局

**Files:**
- Modify: `backend/app/schemas/games.py:35-37`（`JoinRequest`）、`:57-63`（`SpectatorView`）
- Modify: `backend/app/api/rest.py:136-157`（join）、`:290-330`（delete）、`:336-366`（state）、`:459-470`（meta）
- Test: `backend/tests/test_api_lobby.py`、新建 `backend/tests/test_api_host_plays.py`

**Interfaces:**
- Consumes: Task 2 的 `GameRegistry.join(..., seat=, user_id=)`。
- Produces: `POST /games/{id}/join` body `{display_name, player_type?, seat?}`；`GET /state` 三种视角响应都带顶层 `viewer`（`"GM"` / `"SPECTATOR"` / 座位号 int），PLAYER 响应的 `seats[i]` 多一个 `display_name`；`GET /meta` 返回 `GameMeta` 的 JSON 加 `viewer`；`DELETE /games/{id}` 对未开局对局返回 204。

- [ ] **Step 1: 写失败测试**

新建 `backend/tests/test_api_host_plays.py`（本任务只放前三组测试，Task 4 继续在这个文件追加）：

```python
"""真人入座与建局者玩家视角（issue #115）：指定座位、viewer 回传、GM 封锁、终局恢复。"""

from __future__ import annotations

import time
from typing import Any

from fastapi.testclient import TestClient

from app.cli.bot import RandomBot
from app.runtime.game_runner import RunnerTimeouts
from tests.conftest import bearer, login_as, make_app

PRESET = {"preset": "std_9_kill_side", "config_override": {"seed": 11}}


def _app() -> Any:
    return make_app(timeouts=RunnerTimeouts(speech_sec=10.0, action_sec=10.0))


def _create(client: TestClient) -> dict[str, Any]:
    r = client.post("/api/v1/games", json=PRESET)
    assert r.status_code == 200, r.text
    return r.json()


def _start(client: TestClient, created: dict[str, Any]) -> None:
    r = client.post(
        f"/api/v1/games/{created['game_id']}/start", json={}, headers=bearer(created["host_token"])
    )
    assert r.status_code == 200, r.text


def _play_to_end_via_cookie(client: TestClient, gid: str, seat: int, timeout: float = 30.0) -> None:
    """建局者用 cookie 连 WS 当玩家把整局打完（白盒选合法行动）。"""
    handle = client.app.state.games.get(gid)  # type: ignore[attr-defined]
    deadline = time.time() + timeout
    with client.websocket_connect(f"/api/v1/ws?game_id={gid}") as ws:
        while time.time() < deadline:
            frame = ws.receive_json()
            if frame["type"] == "game_over":
                break
            if frame["type"] == "your_turn":
                assert frame["observation"]["my_seat"] == seat
                from tests.test_api_play import _to_tool_call

                ws.send_json(_to_tool_call(RandomBot.choose_action(handle.runner.state, seat)))
    while not (handle.task is not None and handle.task.done()) and time.time() < deadline:
        time.sleep(0.05)
    assert handle.task is not None and handle.task.done()


class TestJoinBySeat:
    def test_join_specific_seat_conflicts_and_default(self) -> None:
        app = _app()
        with TestClient(app) as owner, TestClient(app) as ext:
            login_as(owner, "alice")
            created = _create(owner)
            gid, host = created["game_id"], created["host_token"]
            # 外部客户端（无 cookie，host_token）指定 5 号
            r = ext.post(
                f"/api/v1/games/{gid}/join", json={"display_name": "A", "seat": 5}, headers=bearer(host)
            )
            assert r.status_code == 200 and r.json()["seat"] == 5
            r = ext.post(
                f"/api/v1/games/{gid}/join", json={"display_name": "B", "seat": 5}, headers=bearer(host)
            )
            assert r.status_code == 409 and r.json()["detail"] == "座位 5 已被占用"
            r = ext.post(
                f"/api/v1/games/{gid}/join", json={"display_name": "C", "seat": 9}, headers=bearer(host)
            )
            assert r.status_code == 409 and r.json()["detail"] == "座位号越界：9（0–8）"
            r = ext.post(f"/api/v1/games/{gid}/join", json={"display_name": "D"}, headers=bearer(host))
            assert r.json()["seat"] == 0

    def test_same_account_cannot_join_twice(self) -> None:
        app = _app()
        with TestClient(app) as owner:
            login_as(owner, "alice")
            created = _create(owner)
            gid = created["game_id"]
            r = owner.post(f"/api/v1/games/{gid}/join", json={"display_name": "我", "seat": 2})
            assert r.status_code == 200 and r.json()["seat"] == 2
            r = owner.post(f"/api/v1/games/{gid}/join", json={"display_name": "我2"})
            assert r.status_code == 409 and r.json()["detail"] == "你已入座 2 号"


class TestViewerField:
    def test_state_and_meta_carry_viewer(self) -> None:
        app = _app()
        with TestClient(app) as owner, TestClient(app) as anon, TestClient(app) as admin:
            login_as(owner, "alice")
            login_as(admin, "root", role="admin")
            created = _create(owner)
            gid = created["game_id"]
            joined = owner.post(
                f"/api/v1/games/{gid}/join", json={"display_name": "我", "seat": 2}
            ).json()
            _start(owner, created)
            # PLAYER token：观察 + viewer=座位号 + seats 带 display_name
            st = owner.get(f"/api/v1/games/{gid}/state", headers=bearer(joined["player_token"])).json()
            assert st["viewer"] == 2 and st["my_seat"] == 2
            assert st["seats"][2]["display_name"] == "我"
            assert all("display_name" in s for s in st["seats"])
            # 分享 → SPECTATOR；admin cookie → GM（完整 state 带 players）
            sp = anon.get(f"/api/v1/games/{gid}/state", params={"share": created["share_token"]}).json()
            assert sp["viewer"] == "SPECTATOR" and "players" not in sp
            gm = admin.get(f"/api/v1/games/{gid}/state").json()
            assert gm["viewer"] == "GM" and "players" in gm
            _play_to_end_via_cookie(owner, gid, 2)
            meta = admin.get(f"/api/v1/games/{gid}/meta").json()
            assert meta["viewer"] == "GM" and meta["game_id"] == gid and "roster" in meta
            meta_sp = anon.get(
                f"/api/v1/games/{gid}/meta", params={"share": created["share_token"]}
            ).json()
            assert meta_sp["viewer"] == "SPECTATOR"


class TestDeleteUnstarted:
    def test_delete_unstarted_game(self) -> None:
        app = _app()
        with TestClient(app) as owner:
            login_as(owner, "alice")
            created = _create(owner)
            gid = created["game_id"]
            owner.post(f"/api/v1/games/{gid}/join", json={"display_name": "我", "seat": 0})
            assert owner.delete(f"/api/v1/games/{gid}").status_code == 204
            assert owner.get(f"/api/v1/games/{gid}/state").status_code == 404
            # token 已作废
            r = owner.get(f"/api/v1/games/{gid}/state", headers=bearer(created["gm_token"]))
            assert r.status_code == 401
```

说明：`_play_to_end_via_cookie` 依赖 Task 4 才能工作（建局者 cookie 在封锁期解析为 PLAYER）。本任务里 `test_state_and_meta_carry_viewer` 会在 `_play_to_end_via_cookie` 处失败——**允许**，Task 4 完成后转绿。本任务的通过判据是 `TestJoinBySeat`、`TestDeleteUnstarted` 两组通过，以及 `test_state_and_meta_carry_viewer` 在 `_play_to_end_via_cookie` 之前的断言全部成立（可临时用 `-x` 观察失败位置）。

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && uv run pytest tests/test_api_host_plays.py -q`
Expected: 422（`seat` 字段未知不会 422——`JoinRequest` 无 extra=forbid，会被忽略 → 座位号断言失败）、viewer 缺失 KeyError、DELETE 409。

- [ ] **Step 3: schema 改动**

`backend/app/schemas/games.py`：

```python
class JoinRequest(BaseModel):
    display_name: str
    player_type: Literal["HUMAN", "AGENT"] = "HUMAN"
    seat: int | None = None  # 指定座位（issue #115）；None = 顺序分配


class SpectatorView(BaseModel):
    game_id: str
    phase: str
    round: int
    seats: list[dict[str, Any]]
    sheriff_seat: int | None
    winner: str | None
    viewer: Literal["SPECTATOR"] = "SPECTATOR"  # 本次请求解析出的视角（issue #115）
```

- [ ] **Step 4: rest.py 改动**

`join_endpoint` 里把 `seat = games.join(handle, req.display_name, req.player_type)` 改为：

```python
    seat = games.join(
        handle, req.display_name, req.player_type, seat=req.seat, user_id=user_id
    )
```

`state_endpoint` 替换为：

```python
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
    if info.kind == "PLAYER":
        assert info.seat is not None
        obs = build_observation(live, info.seat).model_dump(mode="json")
        # 展示名是公开信息（观众视图也有），玩家页需要它渲染座位环；不动引擎的 observation
        names = {p.seat: p.display_name for p in live.players}
        obs["seats"] = [{**s, "display_name": names[int(s["seat"])]} for s in obs["seats"]]
        obs["viewer"] = info.seat
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
    ).model_dump(mode="json")
```

`meta_endpoint` 替换为：

```python
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
    return {**meta.model_dump(mode="json"), "viewer": viewer_of(info)}
```

`delete_game_endpoint`：把

```python
    if handle is not None and not (handle.task is not None and handle.task.done()):
        raise HTTPException(status_code=409, detail="对局进行中（或尚未开局），不能删除")
```

改为

```python
    # 未开局（issue #115：Lobby 三步编排中途失败的半成品）可删；已开局且 task 未结束 → 409
    if handle is not None and handle.started and not (handle.task is not None and handle.task.done()):
        raise HTTPException(status_code=409, detail="对局进行中，不能删除")
```

并把该函数 docstring 里「有 handle 且 task 未结束（含未开局）→ 409」改为「已开局且 task 未结束 → 409；未开局可删」。

- [ ] **Step 5: 跑测试**

Run: `cd backend && uv run pytest tests/test_api_host_plays.py -q -k "JoinBySeat or DeleteUnstarted" && uv run pytest tests/test_api_lobby.py tests/test_api_play.py tests/test_api_history.py -q && uv run ruff check app && uv run ruff format --check app && uv run mypy app`
Expected: 全部通过。若 `test_api_history.py` 里有「未开局删除 409」的断言，改成期待 204 并注明 issue #115。

- [ ] **Step 6: 提交**

```bash
git add backend/app/schemas/games.py backend/app/api/rest.py backend/tests/test_api_host_plays.py backend/tests/test_api_history.py
git commit -m "feat(api): join 指定座位，/state /meta 回传 viewer，PLAYER 座位带展示名，未开局对局可删 (issue #115)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 4: 建局者入座后的上帝视角封锁（REST + WS）

**Files:**
- Modify: `backend/app/api/rest.py:198-260`（`_finished` 之后加 `_owner_locked`；`_session_viewer`、`resolve_viewer`）
- Modify: `backend/app/api/ws.py:90-107`
- Test: `backend/tests/test_api_host_plays.py`（追加）；按需调整 `tests/test_api_e2e.py` 等既有测试

**Interfaces:**
- Consumes: Task 2 `GameHandle.owner_seat()`；Task 3 的测试文件与 `_play_to_end_via_cookie`。
- Produces: `rest.GM_LOCKED_MSG: str`；`rest._owner_locked(games, game_id) -> bool`；`_session_viewer` 在封锁中对 owner 返回 `TokenInfo(kind="PLAYER", seat=owner_seat)`；`resolve_viewer` 对 GM token 封锁中 403；WS `?token=` GM 封锁中 4403。

- [ ] **Step 1: 写失败测试**

在 `backend/tests/test_api_host_plays.py` 末尾追加：

```python
class TestGmLock:
    def _seated_game(self, owner: TestClient) -> tuple[str, dict[str, Any]]:
        created = _create(owner)
        gid = created["game_id"]
        r = owner.post(f"/api/v1/games/{gid}/join", json={"display_name": "我", "seat": 1})
        assert r.status_code == 200
        _start(owner, created)
        return gid, created

    def test_owner_cookie_is_player_and_gm_token_403_until_over(self) -> None:
        app = _app()
        with TestClient(app) as owner, TestClient(app) as anon, TestClient(app) as admin:
            login_as(owner, "alice")
            login_as(admin, "root", role="admin")
            gid, created = self._seated_game(owner)
            # cookie → PLAYER（1 号的观察）
            st = owner.get(f"/api/v1/games/{gid}/state").json()
            assert st["viewer"] == 1 and st["my_seat"] == 1 and "players" not in st
            # GM token 封锁
            r = owner.get(f"/api/v1/games/{gid}/state", headers=bearer(created["gm_token"]))
            assert r.status_code == 403
            assert r.json()["detail"] == "建局者已入座，对局结束前不能查看上帝视角"
            r = owner.get(f"/api/v1/games/{gid}/events", params={"token": created["gm_token"]})
            assert r.status_code == 403
            # 分享照旧观战；admin 照旧 GM
            assert (
                anon.get(f"/api/v1/games/{gid}/state", params={"share": created["share_token"]}).json()["viewer"]
                == "SPECTATOR"
            )
            assert admin.get(f"/api/v1/games/{gid}/state").json()["viewer"] == "GM"
            # 终局后恢复
            _play_to_end_via_cookie(owner, gid, 1)
            assert owner.get(f"/api/v1/games/{gid}/meta").json()["viewer"] == "GM"
            assert owner.get(f"/api/v1/games/{gid}/replay", headers=bearer(created["gm_token"])).status_code == 200
            assert owner.get(f"/api/v1/games/{gid}/meta", headers=bearer(created["gm_token"])).json()["viewer"] == "GM"

    def test_lock_applies_before_start_too(self) -> None:
        app = _app()
        with TestClient(app) as owner:
            login_as(owner, "alice")
            created = _create(owner)
            gid = created["game_id"]
            owner.post(f"/api/v1/games/{gid}/join", json={"display_name": "我", "seat": 0})
            # 未开局：cookie 解析为 PLAYER 后 /state 仍是 409（尚未开始），GM token 403
            assert owner.get(f"/api/v1/games/{gid}/state").status_code == 409
            assert owner.get(f"/api/v1/games/{gid}/state", headers=bearer(created["gm_token"])).status_code == 403

    def test_admin_owner_seated_is_player(self) -> None:
        app = _app()
        with TestClient(app) as root:
            login_as(root, "root", role="admin")
            gid, _created = self._seated_game(root)
            st = root.get(f"/api/v1/games/{gid}/state").json()
            assert st["viewer"] == 1 and st["my_seat"] == 1

    def test_unseated_owner_and_external_seat_keep_gm(self) -> None:
        app = _app()
        with TestClient(app) as owner, TestClient(app) as ext:
            login_as(owner, "alice")
            created = _create(owner)
            gid = created["game_id"]
            # 外部客户端用 host_token 入座：user_id=None，不触发封锁
            ext.post(f"/api/v1/games/{gid}/join", json={"display_name": "Ext", "seat": 0}, headers=bearer(created["host_token"]))
            _start(owner, created)
            assert owner.get(f"/api/v1/games/{gid}/state").json()["viewer"] == "GM"
            assert owner.get(f"/api/v1/games/{gid}/state", headers=bearer(created["gm_token"])).status_code == 200

    def test_ws_cookie_player_can_act_and_gm_token_4403(self) -> None:
        app = _app()
        with TestClient(app) as owner:
            login_as(owner, "alice")
            gid, created = self._seated_game(owner)
            from starlette.websockets import WebSocketDisconnect

            try:
                with owner.websocket_connect(f"/api/v1/ws?token={created['gm_token']}") as ws:
                    ws.receive_json()
                    raise AssertionError("GM token 应被 4403 关闭")
            except WebSocketDisconnect as exc:
                assert exc.code == 4403
            _play_to_end_via_cookie(owner, gid, 1)  # cookie 入口能收 your_turn 并提交

    def test_cookie_player_view_equals_player_token_view(self) -> None:
        app = _app()
        with TestClient(app) as owner:
            login_as(owner, "alice")
            created = _create(owner)
            gid = created["game_id"]
            joined = owner.post(f"/api/v1/games/{gid}/join", json={"display_name": "我", "seat": 4}).json()
            _start(owner, created)
            tok = bearer(joined["player_token"])
            a = owner.get(f"/api/v1/games/{gid}/state").json()
            b = owner.get(f"/api/v1/games/{gid}/state", headers=tok).json()
            # 快照可能相差一个 state_version（对局在跑）：只比字段集合与身份字段
            assert set(a) == set(b) and a["my_seat"] == b["my_seat"] == 4 and a["my_role"] == b["my_role"]
            ea = owner.get(f"/api/v1/games/{gid}/events").json()
            eb = owner.get(f"/api/v1/games/{gid}/events", headers=tok).json()
            n = min(len(ea), len(eb))
            assert ea[:n] == eb[:n] and all(e["visibility"] != "GM_ONLY" for e in ea)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && uv run pytest tests/test_api_host_plays.py -q`
Expected: `TestGmLock` 全部 FAIL（cookie 仍是 GM、gm_token 200），`test_state_and_meta_carry_viewer` 仍 FAIL。

- [ ] **Step 3: rest.py 实现**

在 `_finished` 之后、`_require_finished` 之前加：

```python
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
```

`_session_viewer` 替换为：

```python
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
```

`resolve_viewer` 的 token 分支在 `return info` 之前加：

```python
        if info.kind == "GM" and _owner_locked(games, game_id):
            raise HTTPException(status_code=403, detail=GM_LOCKED_MSG)
```

- [ ] **Step 4: ws.py 实现**

`backend/app/api/ws.py` 的 import 行改为：

```python
from app.api.rest import _owner_locked, _session_viewer, _share_viewer, _your_turn_payload, viewer_of
```

`if token:` 分支改为：

```python
    if token:
        info = tokens.resolve(token)
        if info is not None and info.kind == "GM" and _owner_locked(games, info.game_id):
            await ws.close(code=4403)  # 建局者已入座：上帝视角封锁（issue #115）
            return
```

（import 行超 100 列时按 ruff 自动换行。）

- [ ] **Step 5: 跑新测试与全量后端套件，修既有测试**

Run: `cd backend && uv run pytest tests/test_api_host_plays.py -q`
Expected: 全部通过（含 Task 3 遗留的 `test_state_and_meta_carry_viewer`）。

Run: `cd backend && uv run pytest -q --ignore=tests/test_api_e2e.py && uv run pytest tests/test_api_e2e.py -q`
预期有既有测试因行为变化失败：它们的 `client` 夹具已登录（cookie），又用 `host_token` 让「建局者本人」join，然后在对局进行中用 `gm_token` 或 cookie 读 GM 数据（例如 `tests/test_api_e2e.py` 约第 64–69 行 join、第 145 行用 `created["gm_token"]`）。修法统一为：这类测试里的 join 改为经**不带 cookie 的第二个 TestClient** 发送（`with TestClient(app) as ext:` + `headers=bearer(host_token)`，`user_id=None` 不触发封锁），并在改动处加注释 `# issue #115：建局者本人入座会封锁 GM 视角，这里用外部客户端入座`。不要为了让旧测试通过而放松封锁规则。`test_acceptance_human_can_take_any_seat[5]` 的超时是已知 flaky（#74），与本任务无关。

Run: `cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy app`
Expected: 干净。

- [ ] **Step 6: 提交**

```bash
git add backend/app/api/rest.py backend/app/api/ws.py backend/tests/
git commit -m "feat(api): 建局者入座后封锁上帝视角——cookie 解析为 PLAYER、GM token 403/4403，终局恢复 (issue #115)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 5: 前端路由 `?player=` 与 `Viewer` 类型扩展

**Files:**
- Modify: `frontend/src/api/tokens.ts`
- Modify: `frontend/src/store/game.ts:13`（`Viewer`）
- Modify: `frontend/src/components/PhaseBar/PhaseBar.tsx:86-89`
- Modify: `frontend/src/pages/GamePage.tsx:54-60`（props 类型）、`frontend/src/App.tsx`（无需改动，`hash.viewer` 类型自动跟随）
- Test: `frontend/src/api/tokens.test.ts`

**Interfaces:**
- Produces: `tokens.ts` 导出 `ViewerHint = "GM" | "SPECTATOR"`（URL 里的视角提示）；`ParsedHash.viewer?: ViewerHint`；`#/g/{id}?player=P` → `{route:"game", gameId, token:"P"}`；`store/game.ts` 的 `Viewer = "GM" | "SPECTATOR" | number`。本任务里裸 `#/g/{id}` 仍返回 `viewer:"GM"`（Task 6 改为不带提示）。

- [ ] **Step 1: 写失败测试**

`frontend/src/api/tokens.test.ts` 的 `cases` 数组里加三行：

```ts
    ["#/g/abc?player=P", { route: "game", gameId: "abc", token: "P" }],
    // gm 优先于 player（不信任 URL 的组合）；player 优先于 share
    ["#/g/abc?player=P&share=U", { route: "game", gameId: "abc", token: "P" }],
    ["#/g/abc?gm=T&player=P", { route: "game", gameId: "abc", token: "T", viewer: "GM" }],
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd frontend && npx vitest run src/api/tokens.test.ts`
Expected: 3 个用例失败（`?player=` 被忽略，返回 `viewer:"GM"`）。

- [ ] **Step 3: 实现**

`frontend/src/api/tokens.ts`：把 `export type Viewer = "GM" | "SPECTATOR";` 改为

```ts
/** URL 里的视角提示（issue #115）：`?gm=` → GM、`?share=` → SPECTATOR；`?player=` 与裸路径不给提示，
 * GamePage 以 `/state` / `/meta` 响应里的 `viewer` 为准。 */
export type ViewerHint = "GM" | "SPECTATOR";
```

`ParsedHash.viewer?: Viewer` 改为 `viewer?: ViewerHint`。文件头注释加一行 `#/g/{gameId}?player=…（玩家 token，issue #115）`。`/g/` 分支改为：

```ts
    const gm = query.get("gm");
    const player = query.get("player");
    const share = query.get("share");
    // 多个参数同时出现（不该发生，但不信任 URL）：gm > player > share——
    // 权限高的不能被同时携带的低权限参数降级。
    if (gm) {
      return { route: "game", gameId, token: gm, viewer: "GM" };
    }
    if (player) {
      return { route: "game", gameId, token: player };
    }
    if (share) {
      return { route: "game", gameId, share, viewer: "SPECTATOR" };
    }
    return { route: "game", gameId, viewer: "GM" };
```

`frontend/src/store/game.ts`：`export type Viewer = "GM" | "SPECTATOR";` 改为

```ts
/** 视角：上帝 / 观众 / 座位号（玩家，issue #115）。 */
export type Viewer = "GM" | "SPECTATOR" | number;
```

`frontend/src/pages/GamePage.tsx`：`GamePageProps.viewer?: Viewer` 改为 `viewer?: ViewerHint`，并加 `import type { ViewerHint } from "../api/tokens";`（保留 `store/game` 的 `Viewer` import，后面仍用）。

`frontend/src/components/PhaseBar/PhaseBar.tsx` 视角标签段改为：

```tsx
      <span className={`seg ${styles.seg}`}>
        <span className={`seg-opt ${viewer === "GM" ? styles.segOn : ""}`}>上帝</span>
        <span className={`seg-opt ${viewer === "SPECTATOR" ? styles.segOn : ""}`}>观众</span>
        <span className={`seg-opt ${typeof viewer === "number" ? styles.segOn : ""}`}>
          {typeof viewer === "number" ? `玩家 ${viewer}号` : "玩家"}
        </span>
      </span>
```

运行 `cd frontend && grep -rn "from \"../api/tokens\"\|from \"./tokens\"\|from \"../../api/tokens\"" src | grep -i viewer`，凡 import 了旧 `Viewer` 类型的地方改为 `ViewerHint`。

- [ ] **Step 4: 跑测试与类型检查**

Run: `cd frontend && npm run check`
Expected: 全绿。

- [ ] **Step 5: 提交**

```bash
git add frontend/src
git commit -m "feat(frontend): 路由支持 ?player= 玩家 token，Viewer 类型加座位号，顶栏显示玩家标签 (issue #115)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 6: GamePage 以服务端 `viewer` 为准；`joinGame`；封锁错误态

**Files:**
- Create: `frontend/src/api/player.ts`
- Modify: `frontend/src/api/rest.ts`（`joinGame`、`ViewerValue`、`viewerFrom`、`MetaResponse`）
- Modify: `frontend/src/api/tokens.ts`（裸路径不再给 `viewer:"GM"`）
- Modify: `frontend/src/components/ErrorState/ErrorState.tsx`（`locked`）
- Modify: `frontend/src/pages/GamePage.tsx`
- Test: `frontend/src/api/tokens.test.ts`、`frontend/src/api/rest.test.ts`、`frontend/src/pages/GamePage.test.tsx`

**Interfaces:**
- Consumes: Task 3 的 `/state` / `/meta` `viewer` 字段与 `/join` body；Task 5 的 `ViewerHint`、`Viewer`。
- Produces:
  - `api/player.ts`：`PlayerObservation`、`ObservedSeat`、`ToolCall { tool: string; arguments: Record<string, unknown> }`、`YourTurn { observation; available_tools: string[]; deadline_ts: number }`、`ActionResult { ok: boolean; event_id: string | null; state_version: number | null; rejected_reason: string | null }`。
  - `api/rest.ts`：`joinGame(gameId, body: JoinRequest): Promise<JoinResponse>`；`type ViewerValue = "GM" | "SPECTATOR" | number`；`viewerFrom(raw: Record<string, unknown>): ViewerValue | null`；`getMeta` 返回 `MetaResponse = GameMeta & { viewer?: ViewerValue }`。
  - `ErrorState`：`ErrorKind` 加 `"locked"`，新增可选 prop `playerHref?: string`。
  - GamePage 内部：`resolvedViewer: Viewer | null`、`myRole: RoleType | null`（Task 10 用）。

- [ ] **Step 1: 写失败测试**

`frontend/src/api/tokens.test.ts`：把 `["#/g/abc", ...]` 相关用例（若有）改为 `["#/g/abc", { route: "game", gameId: "abc" }]`，没有就新增这一行。

`frontend/src/api/rest.test.ts` 末尾追加：

```ts
import { joinGame, viewerFrom } from "./rest";

describe("viewerFrom / joinGame（issue #115）", () => {
  it("viewerFrom 只认 GM / SPECTATOR / 座位号", () => {
    expect(viewerFrom({ viewer: "GM" })).toBe("GM");
    expect(viewerFrom({ viewer: "SPECTATOR" })).toBe("SPECTATOR");
    expect(viewerFrom({ viewer: 3 })).toBe(3);
    expect(viewerFrom({ viewer: "3" })).toBeNull();
    expect(viewerFrom({})).toBeNull();
  });

  it("joinGame 走 cookie（same-origin）并带 seat", async () => {
    const fetchMock = vi.fn(async () =>
      new Response(JSON.stringify({ player_token: "P", seat: 2, ws_url: "/api/v1/ws?token=P" }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const res = await joinGame("g1", { display_name: "我", seat: 2 });
    expect(res.seat).toBe(2);
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("/api/v1/games/g1/join");
    expect(init.credentials).toBe("same-origin");
    expect(JSON.parse(init.body as string)).toEqual({ display_name: "我", seat: 2 });
    vi.unstubAllGlobals();
  });
});
```

（若文件顶部已 import `describe/it/expect/vi`，不要重复 import。）

`frontend/src/pages/GamePage.test.tsx` 追加：

```ts
describe("GamePage 视角以服务端为准（issue #115）", () => {
  it("/meta 的 viewer 覆盖 URL 提示", async () => {
    stubFetch(() => jsonResponse(200, { ...meta, viewer: "SPECTATOR" }));
    vi.stubGlobal("WebSocket", vi.fn());
    render(<GamePage gameId="g_x" token="t" viewer="GM" />);
    await screen.findByText(new RegExp(`已结束 · ${events.length} 条事件`));
    expect(useGameStore.getState().viewer).toBe("SPECTATOR");
  });

  it("建局者入座期间用 GM 链接进来 → 封锁错误态，给玩家入口", async () => {
    const fetchMock = vi.fn(async (rawUrl: string) => {
      const url = rawUrl.split("?")[0] as string;
      if (url.endsWith("/meta")) return jsonResponse(403, { detail: "对局未结束，上帝视角回放未开放" });
      if (url.endsWith("/state"))
        return jsonResponse(403, { detail: "建局者已入座，对局结束前不能查看上帝视角" });
      return jsonResponse(200, {});
    });
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("WebSocket", vi.fn());
    render(<GamePage gameId="g_x" token="T" viewer="GM" />);
    await screen.findByText("建局者已入座，对局结束前不能查看上帝视角");
    const link = screen.getByRole("link", { name: /以玩家身份进入/ });
    expect(link.getAttribute("href")).toBe("#/g/g_x");
  });
});
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd frontend && npx vitest run src/api src/pages/GamePage.test.tsx`
Expected: 新用例失败（`viewerFrom` 不存在、viewer 仍为 "GM"、403 落到通用错误态）。

- [ ] **Step 3: 新建 `frontend/src/api/player.ts`**

```ts
// 玩家视角的数据形状（issue #115）：对应 backend/app/engine/observation.py::PlayerObservation
// 与 app/api/rest.py::_your_turn_payload / ws.py 的 your_turn、action_result 帧。
// 零裁决：只是类型，前端不据此判断任何合法性。

import type { ElectionStage, RoleType } from "../engine/types";

/** `/state`（PLAYER 视角）把展示名补进 seats；WS your_turn 里的 observation 没有 display_name。 */
export interface ObservedSeat {
  seat: number;
  alive: boolean;
  is_sheriff: boolean;
  idiot_revealed: boolean;
  display_name?: string;
}

export interface PlayerObservation {
  game_id: string;
  state_version: number;
  my_seat: number;
  my_role: RoleType;
  my_status: "ALIVE" | "DEAD";
  /** 后端阶段名（含 HUNTER_SHOOT 等前端 Phase 枚举之外的值），按字符串处理。 */
  phase: string;
  round: number;
  seats: ObservedSeat[];
  sheriff_seat: number | null;
  badge_flow_claims: Record<string, number[]>;
  /** 私有信息：狼的 teammates / tonight_kill_proposals / tonight_kill_proposal、女巫的
   * antidote_available / poison_available / tonight_killed_seat、预言家 check_results、猎人 can_shoot…
   * 服务端给什么就是什么。 */
  private: Record<string, unknown>;
  election_stage: ElectionStage | string;
  sheriff_candidates: number[];
  vote_candidates: number[];
  pk_speech_pending: boolean;
  badge_only: boolean;
  available_actions: number[];
}

/** 提交给 WS / `POST /actions` 的工具调用（PRD §4.1）。 */
export interface ToolCall {
  tool: string;
  arguments: Record<string, unknown>;
}

export interface YourTurn {
  observation: PlayerObservation;
  available_tools: string[];
  /** 服务端截止时间（秒，Unix 时间戳）。 */
  deadline_ts: number;
}

export interface ActionResult {
  ok: boolean;
  event_id: string | null;
  state_version: number | null;
  rejected_reason: string | null;
}
```

- [ ] **Step 4: `rest.ts` 追加**

在 `startGame` 之后加：

```ts
export interface JoinRequest {
  display_name: string;
  /** 指定座位（issue #115）；不传顺序分配。 */
  seat?: number;
  player_type?: "HUMAN" | "AGENT";
}

export interface JoinResponse {
  player_token: string;
  seat: number;
  ws_url: string;
}

/** 入座（issue #115）：登录会话（cookie）即可，座位绑定当前账号。 */
export function joinGame(gameId: string, body: JoinRequest): Promise<JoinResponse> {
  return req<JoinResponse>("POST", `/games/${gameId}/join`, { body });
}

/** 服务端解析出的视角（issue #115）：`/state` 与 `/meta` 响应顶层的 `viewer`。 */
export type ViewerValue = "GM" | "SPECTATOR" | number;

export function viewerFrom(raw: Record<string, unknown>): ViewerValue | null {
  const v = raw.viewer;
  if (v === "GM" || v === "SPECTATOR" || typeof v === "number") return v;
  return null;
}

export type MetaResponse = GameMeta & { viewer?: ViewerValue };
```

`getMeta` 的返回类型改为 `Promise<MetaResponse>`（`req<MetaResponse>`）。

- [ ] **Step 5: `tokens.ts` 裸路径**

`return { route: "game", gameId, viewer: "GM" };` 改为 `return { route: "game", gameId };`，文件头注释里「裸 #/g/{gameId}（靠 cookie 登录态走 GM 视角…）」改为「裸 #/g/{gameId}（靠 cookie 登录态，视角由服务端决定：建局者已入座 → 玩家，否则 GM）」。

- [ ] **Step 6: `ErrorState.tsx`**

`ErrorKind` 加 `"locked"`；props 加 `playerHref?: string`；在 `if (kind === "auth")` 之前加分支：

```tsx
  if (kind === "locked") {
    return (
      <div className={styles.root} role="alert">
        <div className={styles.box}>
          <span className={styles.code}>403</span>
          <span className={styles.title}>上帝视角已封锁</span>
          <span className={styles.desc}>你已入座这局，对局结束前不能查看全局；终局后自动恢复。</span>
          {detail && <span className={styles.detail}>{detail}</span>}
          {playerHref && (
            <a className={`btn btn-primary ${styles.back}`} href={playerHref}>
              以玩家身份进入
            </a>
          )}
        </div>
      </div>
    );
  }
```

函数签名改为 `({ kind, attempt, detail, playerHref }: ErrorStateProps)`。

- [ ] **Step 7: `GamePage.tsx`**

1. import：加 `import { viewerFrom } from "../api/rest";`（并入现有 `../api/rest` import）、`import type { RoleType } from "../engine/types";`。
2. 组件内 state 区加：

```tsx
  // 视角由服务端决定（issue #115）：/state、/meta 的 viewer 字段；URL 里的 ?gm= / ?share= 只是提示。
  const [resolvedViewer, setResolvedViewer] = useState<Viewer | null>(null);
  // 玩家视角的身份：来自 /state 的 PlayerObservation.my_role（Task 10 的 ActionBar 也会更新它）。
  const [myRole, setMyRole] = useState<RoleType | null>(null);
```

3. 引导 effect 开头 `if (!gameId || !viewer) { setErrorKind("auth"); return; }` 改为 `if (!gameId) { setErrorKind("auth"); return; }`。
4. `/meta` 成功分支：`store.load(meta, { gameId, token: token ?? "", viewer, mode: "replay" });` 改为

```ts
        const v: Viewer = viewerFrom(meta as unknown as Record<string, unknown>) ?? viewer ?? "SPECTATOR";
        setResolvedViewer(v);
        store.load(meta, { gameId, token: token ?? "", viewer: v, mode: "replay" });
```

5. `/state` 成功分支：`useGameStore.getState().load(meta, { gameId, token: token ?? "", viewer, mode: "live" });` 改为

```ts
        const v: Viewer = viewerFrom(snapshot) ?? viewer ?? "SPECTATOR";
        setResolvedViewer(v);
        if (typeof v === "number" && typeof snapshot.my_role === "string") {
          setMyRole(snapshot.my_role as RoleType);
        }
        useGameStore.getState().load(meta, { gameId, token: token ?? "", viewer: v, mode: "live" });
```

6. `/state` 的 catch 里，在 `if (status === 409) {` 之前加：

```ts
        if (status === 403) {
          // 建局者已入座：GM 链接被服务端封锁（issue #115）
          setErrorKind("locked");
          setDetail(err instanceof ApiError ? err.detail : null);
          return;
        }
```

7. effect 清理函数里加 `setResolvedViewer(null); setMyRole(null);`。
8. 渲染：`<ErrorState kind={errorKind} attempt={attempt} detail={detail} />` 改为 `<ErrorState kind={errorKind} attempt={attempt} detail={detail} playerHref={gameId ? `#/g/${gameId}` : undefined} />`；loading 守卫 `viewer === undefined` 改为 `resolvedViewer === null`；其后所有 JSX 里的 `viewer={viewer}` 改为 `viewer={resolvedViewer}`（PhaseBar、NightSummary、NightOverlay）。`useEffect` 依赖数组 `[gameId, token, auth, viewer]` 不变。
9. `App.tsx` 的 `key` 加上 token：`key={`${hash.gameId ?? ""}:${hash.token ?? ""}:${hash.viewer ?? ""}:${hash.share ?? ""}`}`（从 `?player=` 跳到裸路径时强制重挂载，store 干净）。

- [ ] **Step 8: 跑检查**

Run: `cd frontend && npm run check`
Expected: 全绿（`GamePage.test.tsx` 既有用例传 `viewer="GM"` 且 fixture meta 无 viewer → 回落提示 "GM"，不受影响）。

- [ ] **Step 9: 提交**

```bash
git add frontend/src
git commit -m "feat(frontend): 对局页视角以服务端 viewer 为准，joinGame，GM 封锁错误态 (issue #115)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 7: `turn` store 与 WS 回合帧

**Files:**
- Create: `frontend/src/store/turn.ts`、`frontend/src/store/turn.test.ts`
- Modify: `frontend/src/api/ws.ts`
- Test: `frontend/src/api/ws.test.ts`

**Interfaces:**
- Consumes: Task 6 的 `YourTurn` / `ActionResult` / `ToolCall` 类型。
- Produces:
  - `useTurn` store：`{ prompt: YourTurn | null; pending: boolean; lastResult: ActionResult | null; lastError: string | null; setPrompt(p); markPending(); resolve(r); fail(detail); disconnected(); reset() }`。
  - `useLiveEvents(args): LiveEventsHandle`，`LiveEventsHandle = { send(call: ToolCall): boolean }`（socket 未打开返回 false）。

- [ ] **Step 1: 写失败测试**

新建 `frontend/src/store/turn.test.ts`：

```ts
import { beforeEach, describe, expect, it } from "vitest";
import type { YourTurn } from "../api/player";
import { useTurn } from "./turn";

const prompt = (v: number): YourTurn =>
  ({
    observation: { my_seat: 1, state_version: v, phase: "DAY_SPEECH" },
    available_tools: ["speak"],
    deadline_ts: 1000,
  }) as unknown as YourTurn;

beforeEach(() => useTurn.getState().reset());

describe("useTurn", () => {
  it("setPrompt 覆盖旧 prompt 并清掉上一次结果与错误", () => {
    useTurn.getState().fail("x");
    useTurn.getState().setPrompt(prompt(1));
    useTurn.getState().setPrompt(prompt(2));
    const s = useTurn.getState();
    expect(s.prompt?.observation.state_version).toBe(2);
    expect(s.lastError).toBeNull();
    expect(s.pending).toBe(false);
  });

  it("markPending → resolve(ok) 清 prompt；resolve(!ok) 保留 prompt 并记拒因", () => {
    useTurn.getState().setPrompt(prompt(1));
    useTurn.getState().markPending();
    expect(useTurn.getState().pending).toBe(true);
    useTurn.getState().resolve({ ok: false, event_id: null, state_version: null, rejected_reason: "夜里不能发言" });
    expect(useTurn.getState().pending).toBe(false);
    expect(useTurn.getState().prompt).not.toBeNull();
    expect(useTurn.getState().lastResult?.rejected_reason).toBe("夜里不能发言");
    useTurn.getState().markPending();
    useTurn.getState().resolve({ ok: true, event_id: "evt_1", state_version: 5, rejected_reason: null });
    expect(useTurn.getState().prompt).toBeNull();
    expect(useTurn.getState().lastResult?.ok).toBe(true);
  });

  it("fail / disconnected 只清 pending，不动 prompt", () => {
    useTurn.getState().setPrompt(prompt(1));
    useTurn.getState().markPending();
    useTurn.getState().fail("不是你的回合");
    expect(useTurn.getState().pending).toBe(false);
    expect(useTurn.getState().lastError).toBe("不是你的回合");
    expect(useTurn.getState().prompt).not.toBeNull();
    useTurn.getState().markPending();
    useTurn.getState().disconnected();
    expect(useTurn.getState().pending).toBe(false);
  });
});
```

`frontend/src/api/ws.test.ts`：把 `FakeWebSocket` 加上 `readyState = 1;`、`sent: string[] = [];`，`send()` 改为 `send(data: string): void { this.sent.push(data); }`；文件顶部加 `import { useTurn } from "../store/turn";`，`beforeEach` 里加 `useTurn.getState().reset();`。追加测试（沿用文件里 `renderHook(() => useLiveEvents({...}))`、`FakeWebSocket.instances[0]`、`act` 的既有写法）：

```ts
describe("回合帧（issue #115）", () => {
  it("your_turn 写入 turn.prompt；action_result ok 清掉；ok=false 保留并记拒因；error 帧记 lastError", () => {
    renderHook(() => useLiveEvents({ gameId: "g1", auth: { token: "tok" }, enabled: true }));
    const ws = FakeWebSocket.instances[0] as FakeWebSocket;
    ws.onopen?.();
    ws.emit({ type: "your_turn", observation: { my_seat: 0, state_version: 3 }, available_tools: ["vote"], deadline_ts: 99 });
    expect(useTurn.getState().prompt?.available_tools).toEqual(["vote"]);
    ws.emit({ type: "action_result", ok: false, event_id: null, state_version: null, rejected_reason: "目标已死亡" });
    expect(useTurn.getState().prompt).not.toBeNull();
    expect(useTurn.getState().lastResult?.rejected_reason).toBe("目标已死亡");
    ws.emit({ type: "action_result", ok: true, event_id: "evt_9", state_version: 4, rejected_reason: null });
    expect(useTurn.getState().prompt).toBeNull();
    ws.emit({ type: "error", detail: "行动窗口已关闭" });
    expect(useTurn.getState().lastError).toBe("行动窗口已关闭");
  });

  it("send 经 socket 发出 ToolCall 并置 pending；未连接返回 false", () => {
    const { result } = renderHook(() => useLiveEvents({ gameId: "g1", auth: { token: "tok" }, enabled: true }));
    const ws = FakeWebSocket.instances[0] as FakeWebSocket;
    ws.onopen?.();
    expect(result.current.send({ tool: "vote", arguments: { abstain: true } })).toBe(true);
    expect(JSON.parse(ws.sent[0] as string)).toEqual({ tool: "vote", arguments: { abstain: true } });
    expect(useTurn.getState().pending).toBe(true);
    ws.readyState = 3;
    expect(result.current.send({ tool: "vote", arguments: { abstain: true } })).toBe(false);
  });

  it("断线清 pending；重连后再次收到 your_turn 覆盖 prompt", () => {
    renderHook(() => useLiveEvents({ gameId: "g1", auth: { token: "tok" }, enabled: true }));
    const ws = FakeWebSocket.instances[0] as FakeWebSocket;
    ws.onopen?.();
    ws.emit({ type: "your_turn", observation: { state_version: 1 }, available_tools: ["speak"], deadline_ts: 1 });
    useTurn.getState().markPending();
    ws.close(1006);
    expect(useTurn.getState().pending).toBe(false);
    vi.advanceTimersByTime(1000);
    const ws2 = FakeWebSocket.instances[1] as FakeWebSocket;
    ws2.onopen?.();
    ws2.emit({ type: "your_turn", observation: { state_version: 2 }, available_tools: ["speak"], deadline_ts: 2 });
    expect(useTurn.getState().prompt?.deadline_ts).toBe(2);
  });
});
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd frontend && npx vitest run src/store/turn.test.ts src/api/ws.test.ts`
Expected: 失败（`./turn` 不存在；`useLiveEvents` 返回 void）。

- [ ] **Step 3: 新建 `frontend/src/store/turn.ts`**

```ts
// 回合 store（issue #115）：承接 WS 的 your_turn / action_result / error 帧，供 ActionBar 渲染。
// 零裁决：prompt 原样来自服务端；清不清 prompt 只看 action_result.ok。不 import React 组件。

import { create } from "zustand";
import type { ActionResult, YourTurn } from "../api/player";

interface TurnState {
  /** 最新一条 your_turn；提交成功（ok=true）后清空。 */
  prompt: YourTurn | null;
  /** 已发送、等待 action_result。 */
  pending: boolean;
  lastResult: ActionResult | null;
  /** WS error 帧（NotYourTurn / ToolCallError / 超时）。 */
  lastError: string | null;

  setPrompt(prompt: YourTurn): void;
  markPending(): void;
  resolve(result: ActionResult): void;
  fail(detail: string): void;
  disconnected(): void;
  reset(): void;
}

export const useTurn = create<TurnState>((set) => ({
  prompt: null,
  pending: false,
  lastResult: null,
  lastError: null,

  setPrompt(prompt) {
    set({ prompt, pending: false, lastResult: null, lastError: null });
  },
  markPending() {
    set({ pending: true, lastError: null });
  },
  resolve(result) {
    set((s) => ({ pending: false, lastResult: result, prompt: result.ok ? null : s.prompt }));
  },
  fail(detail) {
    set({ pending: false, lastError: detail });
  },
  disconnected() {
    set({ pending: false });
  },
  reset() {
    set({ prompt: null, pending: false, lastResult: null, lastError: null });
  },
}));
```

- [ ] **Step 4: 改 `ws.ts`**

1. import：`import { useCallback, useEffect, useRef } from "react";`、`import { useTurn } from "../store/turn";`、`import type { ActionResult, PlayerObservation, ToolCall } from "../api/player";`（同目录写 `./player`）。
2. 文件头注释第 4 行改为：`// / {type:"your_turn", observation, available_tools, deadline_ts} / {type:"action_result", ok, event_id, state_version, rejected_reason}（issue #115：写入 useTurn，供 ActionBar）`。
3. `WsFrame` 加字段：

```ts
  observation?: PlayerObservation;
  available_tools?: string[];
  deadline_ts?: number;
  ok?: boolean;
  event_id?: string | null;
  state_version?: number | null;
  rejected_reason?: string | null;
```

4. 新增导出类型并改 hook 签名：

```ts
export interface LiveEventsHandle {
  /** 经当前 WS 连接提交工具调用（issue #115）；socket 未打开返回 false，不入队。 */
  send(call: ToolCall): boolean;
}

export function useLiveEvents({ gameId, auth, enabled }: UseLiveEventsArgs): LiveEventsHandle {
```

5. `onmessage` 里 `else if (frame.type === "error" && frame.detail)` 分支改为同时 `useTurn.getState().fail(frame.detail);`，并在其后加：

```ts
        } else if (frame.type === "your_turn" && frame.observation) {
          useTurn.getState().setPrompt({
            observation: frame.observation,
            available_tools: frame.available_tools ?? [],
            deadline_ts: frame.deadline_ts ?? 0,
          });
        } else if (frame.type === "action_result") {
          const result: ActionResult = {
            ok: frame.ok === true,
            event_id: frame.event_id ?? null,
            state_version: frame.state_version ?? null,
            rejected_reason: frame.rejected_reason ?? null,
          };
          useTurn.getState().resolve(result);
```

6. `ws.onclose` 开头（`if (closingForCleanupRef.current) return;` 之后）加 `useTurn.getState().disconnected();`。
7. effect 清理函数末尾加 `useTurn.getState().reset();`。
8. hook 末尾（effect 之后）加并返回：

```ts
  const send = useCallback((call: ToolCall): boolean => {
    const ws = socketRef.current;
    if (ws === null || ws.readyState !== WebSocket.OPEN) return false;
    ws.send(JSON.stringify(call));
    useTurn.getState().markPending();
    return true;
  }, []);

  return { send };
```

`WebSocket.OPEN` 在测试里被 `vi.stubGlobal("WebSocket", FakeWebSocket)` 替换后不存在——改为比较常量 `1`：`ws.readyState !== 1`，并加注释 `// 1 === WebSocket.OPEN；不用静态属性，测试里的假 WebSocket 没有它`。

- [ ] **Step 5: 跑检查**

Run: `cd frontend && npm run check`
Expected: 全绿（GamePage 调 `useLiveEvents(...)` 忽略返回值不报错）。

- [ ] **Step 6: 提交**

```bash
git add frontend/src/store/turn.ts frontend/src/store/turn.test.ts frontend/src/api/ws.ts frontend/src/api/ws.test.ts
git commit -m "feat(frontend): turn store 承接 your_turn/action_result，WS hook 暴露 send (issue #115)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 8: `lib/toolCalls.ts` —— 工具调用构造纯函数

**Files:**
- Create: `frontend/src/lib/toolCalls.ts`、`frontend/src/lib/toolCalls.test.ts`

**Interfaces:**
- Consumes: Task 6 的 `ToolCall`、`PlayerObservation`。
- Produces（全部零 IO、零 React）：
  - `type NightActionType = "kill" | "check" | "save" | "poison" | "guard" | "shoot" | "skip"`
  - `type SheriffActionType = "run_for_sheriff" | "withdraw" | "vote_sheriff" | "pass_badge" | "tear_badge" | "set_speech_direction"`
  - `speakCall(content: string, claimRole?: RoleType | null, badgeFlow?: number[]): ToolCall`
  - `voteCall(target: number | null): ToolCall`（null → 弃票）
  - `nightActionCall(actionType: NightActionType, target: number | null): ToolCall`
  - `sheriffCall(actionType: SheriffActionType, opts?: { target?: number; direction?: "LEFT" | "RIGHT" }): ToolCall`
  - `selfDestructCall(): ToolCall`
  - `nightOptions(obs: PlayerObservation): NightActionType[]`（按 `my_role` 与 `phase`）
  - `needsTarget(actionType: NightActionType): boolean`
  - `aliveTargets(obs: PlayerObservation, includeSelf: boolean): number[]`
  - `ACTION_TOOLS: ReadonlySet<string>`（`speak` `vote` `night_action` `sheriff_action` `self_destruct`）

- [ ] **Step 1: 写失败测试**

新建 `frontend/src/lib/toolCalls.test.ts`：

```ts
import { describe, expect, it } from "vitest";
import type { PlayerObservation } from "../api/player";
import {
  ACTION_TOOLS,
  aliveTargets,
  needsTarget,
  nightActionCall,
  nightOptions,
  selfDestructCall,
  sheriffCall,
  speakCall,
  voteCall,
} from "./toolCalls";

function obs(extra: Partial<PlayerObservation>): PlayerObservation {
  return {
    game_id: "g",
    state_version: 1,
    my_seat: 2,
    my_role: "VILLAGER",
    my_status: "ALIVE",
    phase: "DAY_SPEECH",
    round: 1,
    seats: [0, 1, 2, 3].map((seat) => ({ seat, alive: seat !== 3, is_sheriff: false, idiot_revealed: false })),
    sheriff_seat: null,
    badge_flow_claims: {},
    private: {},
    election_stage: "",
    sheriff_candidates: [],
    vote_candidates: [],
    pk_speech_pending: false,
    badge_only: false,
    available_actions: [],
    ...extra,
  };
}

describe("toolCalls", () => {
  it("speak：content 必带，claim_role / badge_flow 可选", () => {
    expect(speakCall("你好")).toEqual({ tool: "speak", arguments: { content: "你好" } });
    expect(speakCall("我是预言家", "SEER", [1, 3])).toEqual({
      tool: "speak",
      arguments: { content: "我是预言家", claim_role: "SEER", badge_flow: [1, 3] },
    });
    expect(speakCall("x", null, [])).toEqual({ tool: "speak", arguments: { content: "x" } });
  });

  it("vote：目标或弃票，二者必有其一", () => {
    expect(voteCall(3)).toEqual({ tool: "vote", arguments: { target_seat: 3 } });
    expect(voteCall(null)).toEqual({ tool: "vote", arguments: { abstain: true } });
  });

  it("night_action / sheriff_action / self_destruct", () => {
    expect(nightActionCall("kill", 1)).toEqual({ tool: "night_action", arguments: { action_type: "kill", target_seat: 1 } });
    expect(nightActionCall("skip", null)).toEqual({ tool: "night_action", arguments: { action_type: "skip" } });
    expect(sheriffCall("run_for_sheriff")).toEqual({ tool: "sheriff_action", arguments: { action_type: "run_for_sheriff" } });
    expect(sheriffCall("vote_sheriff", { target: 4 })).toEqual({
      tool: "sheriff_action",
      arguments: { action_type: "vote_sheriff", target_seat: 4 },
    });
    expect(sheriffCall("set_speech_direction", { direction: "LEFT" })).toEqual({
      tool: "sheriff_action",
      arguments: { action_type: "set_speech_direction", direction: "LEFT" },
    });
    expect(selfDestructCall()).toEqual({ tool: "self_destruct", arguments: {} });
  });

  it("nightOptions 按角色与阶段", () => {
    expect(nightOptions(obs({ my_role: "WEREWOLF", phase: "NIGHT_WEREWOLF" }))).toEqual(["kill", "skip"]);
    expect(nightOptions(obs({ my_role: "SEER", phase: "NIGHT_SEER" }))).toEqual(["check"]);
    expect(nightOptions(obs({ my_role: "WITCH", phase: "NIGHT_WITCH" }))).toEqual(["save", "poison", "skip"]);
    expect(nightOptions(obs({ my_role: "GUARD", phase: "NIGHT_GUARD" }))).toEqual(["guard", "skip"]);
    expect(nightOptions(obs({ my_role: "HUNTER", phase: "HUNTER_SHOOT" }))).toEqual(["shoot", "skip"]);
    expect(nightOptions(obs({ my_role: "VILLAGER", phase: "NIGHT_WEREWOLF" }))).toEqual([]);
    expect(needsTarget("save")).toBe(false);
    expect(needsTarget("poison")).toBe(true);
  });

  it("aliveTargets 排除死者，可选排除自己", () => {
    expect(aliveTargets(obs({}), false)).toEqual([0, 1]);
    expect(aliveTargets(obs({}), true)).toEqual([0, 1, 2]);
    expect(ACTION_TOOLS.has("speak") && !ACTION_TOOLS.has("get_state")).toBe(true);
  });
});
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd frontend && npx vitest run src/lib/toolCalls.test.ts`
Expected: FAIL（模块不存在）。

- [ ] **Step 3: 新建 `frontend/src/lib/toolCalls.ts`**

```ts
// ToolCall 构造（issue #115）：ActionBar 的输入 → PRD §4.1 工具调用 body。
// 零 IO、零 React；只做形态转换，不判断合法性（引擎裁决，拒因经 action_result 回传）。
// 字段名对应 backend/app/schemas/actions.py::parse_tool_call。

import type { PlayerObservation, ToolCall } from "../api/player";
import type { RoleType } from "../engine/types";

export type NightActionType = "kill" | "check" | "save" | "poison" | "guard" | "shoot" | "skip";
export type SheriffActionType =
  | "run_for_sheriff"
  | "withdraw"
  | "vote_sheriff"
  | "pass_badge"
  | "tear_badge"
  | "set_speech_direction";

/** 需要 ActionBar 渲染输入的主动行动工具；其余（get_state 等只读）不渲染。 */
export const ACTION_TOOLS: ReadonlySet<string> = new Set([
  "speak",
  "vote",
  "night_action",
  "sheriff_action",
  "self_destruct",
]);

export function speakCall(content: string, claimRole?: RoleType | null, badgeFlow?: number[]): ToolCall {
  const args: Record<string, unknown> = { content };
  if (claimRole) args.claim_role = claimRole;
  if (badgeFlow && badgeFlow.length > 0) args.badge_flow = badgeFlow;
  return { tool: "speak", arguments: args };
}

/** null → 弃票（后端要求显式 target_seat 或 abstain=true）。 */
export function voteCall(target: number | null): ToolCall {
  return target === null
    ? { tool: "vote", arguments: { abstain: true } }
    : { tool: "vote", arguments: { target_seat: target } };
}

export function nightActionCall(actionType: NightActionType, target: number | null): ToolCall {
  const args: Record<string, unknown> = { action_type: actionType };
  if (target !== null) args.target_seat = target;
  return { tool: "night_action", arguments: args };
}

export function sheriffCall(
  actionType: SheriffActionType,
  opts: { target?: number; direction?: "LEFT" | "RIGHT" } = {},
): ToolCall {
  const args: Record<string, unknown> = { action_type: actionType };
  if (opts.target !== undefined) args.target_seat = opts.target;
  if (opts.direction !== undefined) args.direction = opts.direction;
  return { tool: "sheriff_action", arguments: args };
}

export function selfDestructCall(): ToolCall {
  return { tool: "self_destruct", arguments: {} };
}

/** 角色在当前阶段可选的夜间动作（UI 提示用；引擎仍会校验）。 */
export function nightOptions(obs: PlayerObservation): NightActionType[] {
  if (obs.phase === "HUNTER_SHOOT") return obs.my_role === "HUNTER" ? ["shoot", "skip"] : [];
  switch (obs.my_role) {
    case "WEREWOLF":
      return obs.phase === "NIGHT_WEREWOLF" ? ["kill", "skip"] : [];
    case "SEER":
      return obs.phase === "NIGHT_SEER" ? ["check"] : [];
    case "WITCH":
      return obs.phase === "NIGHT_WITCH" ? ["save", "poison", "skip"] : [];
    case "GUARD":
      return obs.phase === "NIGHT_GUARD" ? ["guard", "skip"] : [];
    default:
      return [];
  }
}

/** save 的目标固定是今晚刀口（服务端 private.tonight_killed_seat），skip 无目标；其余要选人。 */
export function needsTarget(actionType: NightActionType): boolean {
  return actionType !== "skip" && actionType !== "save";
}

export function aliveTargets(obs: PlayerObservation, includeSelf: boolean): number[] {
  return obs.seats
    .filter((s) => s.alive && (includeSelf || s.seat !== obs.my_seat))
    .map((s) => s.seat)
    .sort((a, b) => a - b);
}
```

- [ ] **Step 4: 跑检查**

Run: `cd frontend && npx vitest run src/lib/toolCalls.test.ts && npm run lint && npm run typecheck`
Expected: 通过。

- [ ] **Step 5: 提交**

```bash
git add frontend/src/lib/toolCalls.ts frontend/src/lib/toolCalls.test.ts
git commit -m "feat(frontend): ToolCall 构造纯函数（speak/vote/night/sheriff/self_destruct）(issue #115)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 9: `ActionBar` 组件

**Files:**
- Create: `frontend/src/components/ActionBar/ActionBar.tsx`、`ActionBar.module.css`、`ActionBar.test.tsx`

**Interfaces:**
- Consumes: Task 6 类型；Task 8 `lib/toolCalls.ts`；`engine/phases.ts` 的 `ROLE_ZH`。
- Produces: `export default function ActionBar(props: ActionBarProps)`，`ActionBarProps = { prompt: YourTurn | null; pending: boolean; lastResult: ActionResult | null; lastError: string | null; onSubmit(call: ToolCall): void; now?: () => number }`。

行为约定（spec §4.4 + Review Focus 2/3）：
- `prompt === null` → 一行状态文字「等待其他玩家…」。
- 多个主动工具可用 → tab 切换；一次只展示一个分组。
- 倒计时到 0 **不**禁用提交，只显示「可能已超时，以服务端裁决为准」；`pending` 时禁用提交。
- 投票未选目标且未选弃票 → 提交按钮禁用。
- 换回合（`observation.state_version` 变化）重置全部输入。

- [ ] **Step 1: 写失败测试**

新建 `frontend/src/components/ActionBar/ActionBar.test.tsx`：

```tsx
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { PlayerObservation, YourTurn } from "../../api/player";
import ActionBar from "./ActionBar";

function obs(extra: Partial<PlayerObservation>): PlayerObservation {
  return {
    game_id: "g",
    state_version: 1,
    my_seat: 2,
    my_role: "VILLAGER",
    my_status: "ALIVE",
    phase: "DAY_SPEECH",
    round: 1,
    seats: [0, 1, 2, 3].map((seat) => ({ seat, alive: seat !== 3, is_sheriff: false, idiot_revealed: false })),
    sheriff_seat: null,
    badge_flow_claims: {},
    private: {},
    election_stage: "",
    sheriff_candidates: [],
    vote_candidates: [],
    pk_speech_pending: false,
    badge_only: false,
    available_actions: [],
    ...extra,
  };
}

function prompt(tools: string[], extra: Partial<PlayerObservation> = {}, deadline = 10_000): YourTurn {
  return { observation: obs(extra), available_tools: [...tools, "get_state"], deadline_ts: deadline };
}

const base = { pending: false, lastResult: null, lastError: null, now: () => 9_000 };

describe("ActionBar", () => {
  it("没有 prompt 时只显示等待文字", () => {
    render(<ActionBar {...base} prompt={null} onSubmit={vi.fn()} />);
    expect(screen.getByRole("status")).toHaveTextContent("等待其他玩家…");
  });

  it("speak：输入内容后提交 speak 调用；空内容禁用", () => {
    const onSubmit = vi.fn();
    render(<ActionBar {...base} prompt={prompt(["speak", "self_destruct"])} onSubmit={onSubmit} />);
    const btn = screen.getByRole("button", { name: "发送发言" });
    expect(btn).toBeDisabled();
    fireEvent.change(screen.getByLabelText("发言内容"), { target: { value: "我是好人" } });
    fireEvent.change(screen.getByLabelText("声明身份"), { target: { value: "SEER" } });
    fireEvent.click(btn);
    expect(onSubmit).toHaveBeenCalledWith({ tool: "speak", arguments: { content: "我是好人", claim_role: "SEER" } });
  });

  it("vote：未选目标禁用；选弃票提交 abstain；选座位提交 target_seat", () => {
    const onSubmit = vi.fn();
    render(<ActionBar {...base} prompt={prompt(["vote", "speak"], { phase: "VOTE" })} onSubmit={onSubmit} />);
    const btn = screen.getByRole("button", { name: "确认投票" });
    expect(btn).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "弃票" }));
    fireEvent.click(btn);
    expect(onSubmit).toHaveBeenLastCalledWith({ tool: "vote", arguments: { abstain: true } });
    fireEvent.click(screen.getByRole("button", { name: "1号" }));
    fireEvent.click(btn);
    expect(onSubmit).toHaveBeenLastCalledWith({ tool: "vote", arguments: { target_seat: 1 } });
    // 死者 3 号不在候选里
    expect(screen.queryByRole("button", { name: "3号" })).toBeNull();
  });

  it("night_action：女巫看到刀口，save 不需选目标，poison 需要", () => {
    const onSubmit = vi.fn();
    render(
      <ActionBar
        {...base}
        prompt={prompt(["night_action"], {
          my_role: "WITCH",
          phase: "NIGHT_WITCH",
          private: { antidote_available: true, poison_available: true, tonight_killed_seat: 0 },
        })}
        onSubmit={onSubmit}
      />,
    );
    expect(screen.getByText(/今晚刀口：0号/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "救人" }));
    fireEvent.click(screen.getByRole("button", { name: "确认行动" }));
    expect(onSubmit).toHaveBeenLastCalledWith({
      tool: "night_action",
      arguments: { action_type: "save", target_seat: 0 },
    });
    fireEvent.click(screen.getByRole("button", { name: "毒" }));
    expect(screen.getByRole("button", { name: "确认行动" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "1号" }));
    fireEvent.click(screen.getByRole("button", { name: "确认行动" }));
    expect(onSubmit).toHaveBeenLastCalledWith({
      tool: "night_action",
      arguments: { action_type: "poison", target_seat: 1 },
    });
  });

  it("sheriff_action：报名阶段上警一键提交；警徽窗口只给移交 / 撕", () => {
    const onSubmit = vi.fn();
    const { rerender } = render(
      <ActionBar
        {...base}
        prompt={prompt(["sheriff_action", "speak"], { phase: "SHERIFF_ELECTION", election_stage: "candidacy" })}
        onSubmit={onSubmit}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "上警" }));
    expect(onSubmit).toHaveBeenLastCalledWith({ tool: "sheriff_action", arguments: { action_type: "run_for_sheriff" } });
    rerender(
      <ActionBar
        {...base}
        prompt={prompt(["sheriff_action"], { phase: "LAST_WORDS", badge_only: true, sheriff_seat: 2, state_version: 2 })}
        onSubmit={onSubmit}
      />,
    );
    expect(screen.queryByRole("button", { name: "上警" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "撕警徽" }));
    expect(onSubmit).toHaveBeenLastCalledWith({ tool: "sheriff_action", arguments: { action_type: "tear_badge" } });
  });

  it("self_destruct 需二次确认", () => {
    const onSubmit = vi.fn();
    render(<ActionBar {...base} prompt={prompt(["speak", "self_destruct"])} onSubmit={onSubmit} />);
    fireEvent.click(screen.getByRole("tab", { name: "自爆" }));
    fireEvent.click(screen.getByRole("button", { name: "自爆" }));
    expect(onSubmit).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "确认自爆" }));
    expect(onSubmit).toHaveBeenCalledWith({ tool: "self_destruct", arguments: {} });
  });

  it("deadline 已过：显示超时提示但仍可提交；pending 禁用；拒因与错误展示", () => {
    const onSubmit = vi.fn();
    const { rerender } = render(
      <ActionBar {...base} now={() => 20_000} prompt={prompt(["speak"])} onSubmit={onSubmit} />,
    );
    expect(screen.getByText(/可能已超时/)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("发言内容"), { target: { value: "x" } });
    expect(screen.getByRole("button", { name: "发送发言" })).not.toBeDisabled();
    rerender(
      <ActionBar
        {...base}
        pending
        lastResult={{ ok: false, event_id: null, state_version: null, rejected_reason: "夜里不能发言" }}
        lastError="行动窗口已关闭"
        prompt={prompt(["speak"])}
        onSubmit={onSubmit}
      />,
    );
    expect(screen.getByRole("button", { name: "发送发言" })).toBeDisabled();
    expect(screen.getByText("夜里不能发言")).toBeInTheDocument();
    expect(screen.getByText("行动窗口已关闭")).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd frontend && npx vitest run src/components/ActionBar`
Expected: FAIL（模块不存在）。

- [ ] **Step 3: 新建 `ActionBar.module.css`**

```css
/* 玩家行动区（issue #115）：位于对局页中栏 SpeechFeed 之下。 */

.root {
  border-top: 1px solid var(--color-divider);
  padding: var(--space-3) var(--space-4);
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  background: var(--color-surface);
}

.idle {
  border-top: 1px solid var(--color-divider);
  padding: var(--space-2) var(--space-4);
  font-size: 12.5px;
  color: var(--color-neutral-500);
}

.tabs {
  display: flex;
  gap: var(--space-2);
}

.tab {
  font-size: 12.5px;
  padding: 2px 10px;
  border-radius: 999px;
  border: 1px solid var(--color-divider);
  background: transparent;
  cursor: pointer;
}

.tabOn {
  border-color: var(--color-primary);
  color: var(--color-primary);
}

.row {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
  align-items: center;
}

.seatBtn {
  min-width: 44px;
}

.seatOn {
  outline: 2px solid var(--color-primary);
}

.textarea {
  width: 100%;
  min-height: 56px;
  resize: vertical;
}

.info {
  font-size: 12.5px;
  color: var(--color-neutral-500);
}

.footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 12.5px;
  color: var(--color-neutral-500);
}

.warn {
  color: var(--color-warning, #b45309);
}

.error {
  color: var(--color-danger, #b91c1c);
}

.danger {
  border-color: var(--color-danger, #b91c1c);
  color: var(--color-danger, #b91c1c);
}
```

- [ ] **Step 4: 新建 `ActionBar.tsx`**

```tsx
// ActionBar（issue #115，PRD §7.3）：玩家视角的行动区，按 your_turn.available_tools 渲染。
// 零裁决：只做输入形态校验（必须选目标、内容非空），合法性由引擎裁决并经 action_result 回传。
// 倒计时到 0 不锁提交（客户端时钟可能快于服务端），只提示「可能已超时」。

import { useEffect, useMemo, useState } from "react";
import type { ActionResult, PlayerObservation, ToolCall, YourTurn } from "../../api/player";
import { ROLE_ZH } from "../../engine/phases";
import type { RoleType } from "../../engine/types";
import {
  ACTION_TOOLS,
  aliveTargets,
  needsTarget,
  nightActionCall,
  nightOptions,
  selfDestructCall,
  sheriffCall,
  speakCall,
  voteCall,
  type NightActionType,
} from "../../lib/toolCalls";
import styles from "./ActionBar.module.css";

export interface ActionBarProps {
  prompt: YourTurn | null;
  pending: boolean;
  lastResult: ActionResult | null;
  lastError: string | null;
  onSubmit(call: ToolCall): void;
  /** 当前时间（秒）；测试注入，缺省 Date.now()/1000。 */
  now?: () => number;
}

const TOOL_ZH: Record<string, string> = {
  speak: "发言",
  vote: "投票",
  night_action: "夜间行动",
  sheriff_action: "警长",
  self_destruct: "自爆",
};

const NIGHT_ZH: Record<NightActionType, string> = {
  kill: "刀",
  check: "查验",
  save: "救人",
  poison: "毒",
  guard: "守护",
  shoot: "开枪",
  skip: "跳过",
};

const CLAIM_ROLES: RoleType[] = ["SEER", "WITCH", "HUNTER", "GUARD", "IDIOT", "VILLAGER", "WEREWOLF"];

const defaultNow = (): number => Date.now() / 1000;

function useCountdown(deadline: number | null, now: () => number): number | null {
  const [left, setLeft] = useState<number | null>(null);
  useEffect(() => {
    if (deadline === null) {
      setLeft(null);
      return;
    }
    const tick = (): void => setLeft(Math.max(0, Math.ceil(deadline - now())));
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, [deadline, now]);
  return left;
}

function SeatButtons({
  seats,
  selected,
  onPick,
}: {
  seats: number[];
  selected: number | null;
  onPick(seat: number): void;
}): JSX.Element {
  return (
    <div className={styles.row}>
      {seats.map((s) => (
        <button
          key={s}
          type="button"
          className={`btn btn-secondary ${styles.seatBtn} ${selected === s ? styles.seatOn : ""}`}
          aria-pressed={selected === s}
          onClick={() => onPick(s)}
        >
          {s}号
        </button>
      ))}
    </div>
  );
}

function privateNumber(obs: PlayerObservation, key: string): number | null {
  const v = obs.private[key];
  return typeof v === "number" ? v : null;
}

export default function ActionBar({
  prompt,
  pending,
  lastResult,
  lastError,
  onSubmit,
  now = defaultNow,
}: ActionBarProps): JSX.Element {
  const tools = useMemo(
    () => (prompt?.available_tools ?? []).filter((t) => ACTION_TOOLS.has(t)),
    [prompt],
  );
  const [tab, setTab] = useState<string | null>(null);
  const active = tab !== null && tools.includes(tab) ? tab : (tools[0] ?? null);
  const [text, setText] = useState("");
  const [claim, setClaim] = useState<RoleType | "">("");
  const [badgeFlow, setBadgeFlow] = useState("");
  const [target, setTarget] = useState<number | null>(null);
  const [abstain, setAbstain] = useState(false);
  const [night, setNight] = useState<NightActionType | null>(null);
  const [confirmDestruct, setConfirmDestruct] = useState(false);
  const left = useCountdown(prompt?.deadline_ts ?? null, now);

  // 新回合（state_version 变化）重置全部输入
  const version = prompt?.observation.state_version ?? -1;
  useEffect(() => {
    setTab(null);
    setText("");
    setClaim("");
    setBadgeFlow("");
    setTarget(null);
    setAbstain(false);
    setNight(null);
    setConfirmDestruct(false);
  }, [version]);

  if (prompt === null) {
    return (
      <div className={styles.idle} role="status">
        等待其他玩家…
      </div>
    );
  }
  const obs = prompt.observation;
  const submit = (call: ToolCall): void => {
    if (!pending) onSubmit(call);
  };

  let body: JSX.Element | null = null;
  if (active === "speak") {
    const showBadgeFlow = obs.phase === "SHERIFF_ELECTION" || obs.phase === "SHERIFF_PK";
    const flow = badgeFlow
      .split(/[,，\s]+/)
      .filter((s) => s !== "")
      .map(Number)
      .filter((n) => Number.isInteger(n));
    body = (
      <>
        <textarea
          className={`input ${styles.textarea}`}
          aria-label="发言内容"
          value={text}
          placeholder="轮到你发言…"
          onChange={(e) => setText(e.target.value)}
        />
        <div className={styles.row}>
          <label className={styles.info}>
            声明身份{" "}
            <select
              className="input"
              aria-label="声明身份"
              value={claim}
              onChange={(e) => setClaim(e.target.value as RoleType | "")}
            >
              <option value="">不声明</option>
              {CLAIM_ROLES.map((r) => (
                <option key={r} value={r}>
                  {ROLE_ZH[r]}
                </option>
              ))}
            </select>
          </label>
          {showBadgeFlow && (
            <label className={styles.info}>
              警徽流（座位号，逗号分隔）{" "}
              <input
                className="input"
                aria-label="警徽流"
                value={badgeFlow}
                onChange={(e) => setBadgeFlow(e.target.value)}
              />
            </label>
          )}
          <button
            type="button"
            className="btn btn-primary"
            disabled={pending || text.trim() === ""}
            onClick={() => submit(speakCall(text.trim(), claim || null, showBadgeFlow ? flow : []))}
          >
            发送发言
          </button>
        </div>
      </>
    );
  } else if (active === "vote") {
    const candidates = obs.vote_candidates.length > 0 ? obs.vote_candidates : aliveTargets(obs, false);
    body = (
      <>
        <SeatButtons
          seats={candidates}
          selected={abstain ? null : target}
          onPick={(s) => {
            setTarget(s);
            setAbstain(false);
          }}
        />
        <div className={styles.row}>
          <button
            type="button"
            className={`btn btn-secondary ${abstain ? styles.seatOn : ""}`}
            aria-pressed={abstain}
            onClick={() => {
              setAbstain(true);
              setTarget(null);
            }}
          >
            弃票
          </button>
          <button
            type="button"
            className="btn btn-primary"
            disabled={pending || (target === null && !abstain)}
            onClick={() => submit(voteCall(abstain ? null : target))}
          >
            确认投票
          </button>
        </div>
      </>
    );
  } else if (active === "night_action") {
    const options = nightOptions(obs);
    const killed = privateNumber(obs, "tonight_killed_seat");
    const teammates = Array.isArray(obs.private.teammates) ? (obs.private.teammates as number[]) : null;
    const proposals = obs.private.tonight_kill_proposals as Record<string, number> | undefined;
    const includeSelf = night === "kill" || night === "guard";
    const chosenTarget = night === "save" ? killed : target;
    body =
      options.length === 0 ? (
        <span className={styles.info}>本阶段无需你行动。</span>
      ) : (
        <>
          <div className={styles.info}>
            {teammates !== null && <span>狼队友：{teammates.length > 0 ? teammates.map((s) => `${s}号`).join("、") : "无"}　</span>}
            {proposals !== undefined && Object.keys(proposals).length > 0 && (
              <span>
                本轮提案：
                {Object.entries(proposals)
                  .map(([from, to]) => `${from}号→${to}号`)
                  .join("，")}
                　
              </span>
            )}
            {obs.my_role === "WITCH" && (
              <span>
                今晚刀口：{killed === null ? "未知" : `${killed}号`} · 解药
                {obs.private.antidote_available ? "可用" : "已用"} · 毒药
                {obs.private.poison_available ? "可用" : "已用"}
              </span>
            )}
          </div>
          <div className={styles.row}>
            {options.map((o) => (
              <button
                key={o}
                type="button"
                className={`btn btn-secondary ${night === o ? styles.seatOn : ""}`}
                aria-pressed={night === o}
                onClick={() => {
                  setNight(o);
                  setTarget(null);
                }}
              >
                {NIGHT_ZH[o]}
              </button>
            ))}
          </div>
          {night !== null && needsTarget(night) && (
            <SeatButtons seats={aliveTargets(obs, includeSelf)} selected={target} onPick={setTarget} />
          )}
          <div className={styles.row}>
            <button
              type="button"
              className="btn btn-primary"
              disabled={pending || night === null || (needsTarget(night) && target === null)}
              onClick={() => night !== null && submit(nightActionCall(night, chosenTarget))}
            >
              确认行动
            </button>
          </div>
        </>
      );
  } else if (active === "sheriff_action") {
    const isSheriff = obs.sheriff_seat === obs.my_seat;
    const isCandidate = obs.sheriff_candidates.includes(obs.my_seat);
    const voting =
      (obs.phase === "SHERIFF_ELECTION" && obs.election_stage === "vote") || obs.phase === "SHERIFF_PK";
    const badgeWindow = obs.badge_only || (isSheriff && obs.phase === "LAST_WORDS");
    const buttons: JSX.Element[] = [];
    if (badgeWindow) {
      buttons.push(
        <SeatButtons key="pass-seats" seats={aliveTargets(obs, false)} selected={target} onPick={setTarget} />,
        <button
          key="pass"
          type="button"
          className="btn btn-primary"
          disabled={pending || target === null}
          onClick={() => target !== null && submit(sheriffCall("pass_badge", { target }))}
        >
          移交警徽
        </button>,
        <button key="tear" type="button" className={`btn btn-secondary ${styles.danger}`} disabled={pending} onClick={() => submit(sheriffCall("tear_badge"))}>
          撕警徽
        </button>,
      );
    } else {
      if (obs.phase === "SHERIFF_ELECTION" && obs.election_stage === "candidacy" && !isCandidate) {
        buttons.push(
          <button key="run" type="button" className="btn btn-primary" disabled={pending} onClick={() => submit(sheriffCall("run_for_sheriff"))}>
            上警
          </button>,
        );
      }
      if (isCandidate) {
        buttons.push(
          <button key="withdraw" type="button" className="btn btn-secondary" disabled={pending} onClick={() => submit(sheriffCall("withdraw"))}>
            退水
          </button>,
        );
      }
      if (voting && !isCandidate && obs.sheriff_candidates.length > 0) {
        buttons.push(
          <SeatButtons key="vote-seats" seats={obs.sheriff_candidates} selected={target} onPick={setTarget} />,
          <button
            key="vote"
            type="button"
            className="btn btn-primary"
            disabled={pending || target === null}
            onClick={() => target !== null && submit(sheriffCall("vote_sheriff", { target }))}
          >
            投给候选人
          </button>,
        );
      }
      if (isSheriff) {
        buttons.push(
          <button key="left" type="button" className="btn btn-secondary" disabled={pending} onClick={() => submit(sheriffCall("set_speech_direction", { direction: "LEFT" }))}>
            从左发言
          </button>,
          <button key="right" type="button" className="btn btn-secondary" disabled={pending} onClick={() => submit(sheriffCall("set_speech_direction", { direction: "RIGHT" }))}>
            从右发言
          </button>,
        );
      }
    }
    body =
      buttons.length === 0 ? (
        <span className={styles.info}>当前没有可用的警长行动。</span>
      ) : (
        <div className={styles.row}>{buttons}</div>
      );
  } else if (active === "self_destruct") {
    body = (
      <div className={styles.row}>
        <span className={styles.info}>狼人自爆：立即出局并跳过本轮白天发言。</span>
        {confirmDestruct ? (
          <button type="button" className={`btn btn-secondary ${styles.danger}`} disabled={pending} onClick={() => submit(selfDestructCall())}>
            确认自爆
          </button>
        ) : (
          <button type="button" className={`btn btn-secondary ${styles.danger}`} disabled={pending} onClick={() => setConfirmDestruct(true)}>
            自爆
          </button>
        )}
      </div>
    );
  }

  return (
    <div className={styles.root} role="region" aria-label="行动区">
      {tools.length > 1 && (
        <div className={styles.tabs} role="tablist">
          {tools.map((t) => (
            <button
              key={t}
              type="button"
              role="tab"
              aria-selected={active === t}
              className={`${styles.tab} ${active === t ? styles.tabOn : ""}`}
              onClick={() => setTab(t)}
            >
              {TOOL_ZH[t] ?? t}
            </button>
          ))}
        </div>
      )}
      {body}
      <div className={styles.footer}>
        <span>
          {pending
            ? "提交中…"
            : left === null
              ? ""
              : left === 0
                ? "可能已超时，以服务端裁决为准"
                : `剩余 ${left} 秒`}
        </span>
        <span>
          {lastResult !== null && !lastResult.ok && lastResult.rejected_reason && (
            <span className={styles.error}>{lastResult.rejected_reason}</span>
          )}
          {lastError && <span className={styles.warn}> {lastError}</span>}
        </span>
      </div>
    </div>
  );
}
```

若 `ROLE_ZH` 在 `engine/phases.ts` 里不含 `IDIOT` 等某个角色键，按 `RoleType` 全集补齐该表（它是 `Record<RoleType, string>`，tsc 会报）。

- [ ] **Step 5: 跑检查**

Run: `cd frontend && npx vitest run src/components/ActionBar && npm run lint && npm run typecheck`
Expected: 通过。若 `btn` 全局样式类名与仓库约定不同，参考 `components/VotePanel` 里按钮的 className 改成一致写法，不要新造全局类。

- [ ] **Step 6: 提交**

```bash
git add frontend/src/components/ActionBar
git commit -m "feat(frontend): ActionBar——按 available_tools 渲染发言/投票/夜间/警长/自爆 (issue #115)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 10: GamePage 接入玩家视角（ActionBar、身份栏、夜间遮罩、座位标记、终局入口）

**Files:**
- Modify: `frontend/src/pages/GamePage.tsx`、`frontend/src/pages/GamePage.module.css`
- Modify: `frontend/src/components/NightOverlay/NightOverlay.tsx`
- Modify: `frontend/src/components/SeatCircle/SeatCircle.tsx`、`SeatCircle.module.css`
- Test: `frontend/src/pages/GamePage.test.tsx`、`frontend/src/components/NightOverlay/NightOverlay.test.tsx`（有则追加，无则新建）

**Interfaces:**
- Consumes: Task 6 的 `resolvedViewer` / `myRole`；Task 7 `useTurn` 与 `useLiveEvents(...).send`；Task 9 `ActionBar`。
- Produces: `NightOverlay` 新增 prop `acting?: boolean`；`SeatCircle` 新增 prop `me?: number | null`。

- [ ] **Step 1: 写失败测试**

`frontend/src/pages/GamePage.test.tsx` 追加（需要 `import { useTurn } from "../store/turn";`）：

```ts
describe("GamePage 玩家视角（issue #115）", () => {
  const playerState = {
    viewer: 2,
    game_id: "g_x",
    state_version: 7,
    my_seat: 2,
    my_role: "SEER",
    my_status: "ALIVE",
    phase: "DAY_SPEECH",
    round: 1,
    seats: [0, 1, 2].map((seat) => ({ seat, alive: true, is_sheriff: false, idiot_revealed: false, display_name: `P${seat}` })),
    sheriff_seat: null,
    badge_flow_claims: {},
    private: {},
    election_stage: "",
    sheriff_candidates: [],
    vote_candidates: [],
    pk_speech_pending: false,
    badge_only: false,
    available_actions: [],
  };

  it("/state 为 PlayerObservation 时显示身份栏与行动区，收到 your_turn 后出现发言输入", async () => {
    const fetchMock = vi.fn(async (rawUrl: string) => {
      const url = rawUrl.split("?")[0] as string;
      if (url.endsWith("/meta")) return jsonResponse(403, { detail: "对局未结束" });
      if (url.endsWith("/state")) return jsonResponse(200, playerState);
      if (url.endsWith("/avatars")) return jsonResponse(200, {});
      return jsonResponse(200, {});
    });
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("WebSocket", vi.fn(() => ({ close() {} })));
    render(<GamePage gameId="g_x" token="P" />);
    await screen.findByText(/我是 2号 · 预言家/);
    expect(screen.getByText("等待其他玩家…")).toBeInTheDocument();
    expect(useGameStore.getState().viewer).toBe(2);
    act(() =>
      useTurn.getState().setPrompt({
        observation: { ...playerState, phase: "DAY_SPEECH" } as never,
        available_tools: ["speak", "get_state"],
        deadline_ts: Date.now() / 1000 + 60,
      }),
    );
    expect(await screen.findByLabelText("发言内容")).toBeInTheDocument();
    useTurn.getState().reset();
  });
});
```

`frontend/src/components/NightOverlay/NightOverlay.test.tsx`（新建或追加）：

```tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import NightOverlay from "./NightOverlay";

describe("NightOverlay 座位视角（issue #115）", () => {
  it("非本人行动阶段遮罩「请闭眼」；本人行动中不遮罩；白天不渲染", () => {
    const { rerender, container } = render(<NightOverlay phase="NIGHT_WEREWOLF" viewer={3} />);
    expect(screen.getByText("请闭眼，等待其他角色行动")).toBeInTheDocument();
    rerender(<NightOverlay phase="NIGHT_WEREWOLF" viewer={3} acting />);
    expect(container).toBeEmptyDOMElement();
    rerender(<NightOverlay phase="DAY_SPEECH" viewer={3} />);
    expect(container).toBeEmptyDOMElement();
  });
});
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd frontend && npx vitest run src/pages/GamePage.test.tsx src/components/NightOverlay`
Expected: FAIL。

- [ ] **Step 3: `NightOverlay.tsx`**

props 加 `acting?: boolean`（「本人正在该夜间阶段行动」）；函数开头 `if (!isNight(phase)) return null;` 之后加：

```tsx
  if (typeof viewer === "number") {
    // 座位视角（issue #115）：轮到自己行动时不遮（ActionBar 在下方），否则只告知闭眼，不提示哪个角色在动
    if (acting) return null;
    return (
      <div className={styles.rootSpectator} aria-hidden="true">
        <div className={styles.cardSpectator}>
          <span className={styles.title}>天黑请闭眼</span>
          <span className={styles.role} style={{ color: "var(--color-neutral-400)" }}>
            请闭眼，等待其他角色行动
          </span>
        </div>
      </div>
    );
  }
```

签名改为 `({ phase, viewer, acting = false }: NightOverlayProps)`。

- [ ] **Step 4: `SeatCircle.tsx`**

`SeatCircleProps` 加 `/** 本人座位（玩家视角，issue #115）；非玩家传 null / 不传。 */ me?: number | null;`，解构加 `me = null`。在每个座位的 `<div className={styles.disc} …>…</div>` 之后、同一座位容器内加：

```tsx
              {me === p.seat && <span className={styles.me}>我</span>}
```

`SeatCircle.module.css` 加：

```css
.me {
  position: absolute;
  top: -6px;
  right: -6px;
  font-size: 10px;
  line-height: 1;
  padding: 2px 5px;
  border-radius: 999px;
  background: var(--color-primary);
  color: var(--color-on-primary, #fff);
}
```

（`.seat` 若不是 `position: relative/absolute`，确认后再放；它按 `left/top` 百分比定位，已是 absolute。）

- [ ] **Step 5: `GamePage.tsx`**

1. import：`import ActionBar from "../components/ActionBar/ActionBar";`、`import { useTurn } from "../store/turn";`、`ROLE_ZH` 并入 `../engine/phases` 的 import。
2. `useLiveEvents({...})` 改为 `const live = useLiveEvents({...});`。
3. 派生区加：

```tsx
  const turnPrompt = useTurn((s) => s.prompt);
  const turnPending = useTurn((s) => s.pending);
  const turnResult = useTurn((s) => s.lastResult);
  const turnError = useTurn((s) => s.lastError);
  const isPlayer = typeof resolvedViewer === "number";
  // 身份以最新 your_turn 为准（/state 只在引导时读一次）
  useEffect(() => {
    if (turnPrompt !== null) setMyRole(turnPrompt.observation.my_role);
  }, [turnPrompt]);
```

4. 中栏 JSX 改为：

```tsx
        <div className={styles.center}>
          {isPlayer && (
            <div className={styles.playerBar}>
              <span>
                我是 {resolvedViewer}号{myRole !== null ? ` · ${ROLE_ZH[myRole]}` : ""}
              </span>
              {over && (
                <button
                  type="button"
                  className="btn btn-secondary"
                  onClick={() => {
                    const target = `#/g/${gameId ?? ""}`;
                    if (window.location.hash === target) window.location.reload();
                    else window.location.hash = target;
                  }}
                >
                  查看全局回放
                </button>
              )}
            </div>
          )}
          <SpeechFeed
            items={items}
            cursor={cursor}
            state={view}
            speakingSeat={speaking}
            avatars={avatars}
          />
          {isPlayer && (
            <ActionBar
              prompt={turnPrompt}
              pending={turnPending}
              lastResult={turnResult}
              lastError={turnError}
              onSubmit={(call) => {
                if (!live.send(call)) useTurn.getState().fail("连接未就绪，请稍后重试");
              }}
            />
          )}
          <NightOverlay phase={view.phase} viewer={resolvedViewer} acting={isPlayer && turnPrompt !== null} />
        </div>
```

5. `<SeatCircle … />` 加 `me={isPlayer ? resolvedViewer : null}`。
6. `GamePage.module.css` 加：

```css
.playerBar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: var(--space-2) var(--space-4);
  font-size: 13px;
  font-weight: 500;
  border-bottom: 1px solid var(--color-divider);
}
```

- [ ] **Step 6: 跑检查**

Run: `cd frontend && npm run check`
Expected: 全绿。

- [ ] **Step 7: 提交**

```bash
git add frontend/src
git commit -m "feat(frontend): 对局页玩家视角——身份栏、ActionBar、夜间遮罩、座位「我」标记、终局回放入口 (issue #115)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 11: Lobby「我自己」座位与 create → join → start 编排

**Files:**
- Modify: `frontend/src/lib/seats.ts`、`frontend/src/lib/seats.test.ts`
- Modify: `frontend/src/components/SeatAssignment/SeatAssignment.tsx`
- Modify: `frontend/src/pages/Lobby.tsx`、`frontend/src/pages/Lobby.test.tsx`

**Interfaces:**
- Consumes: Task 6 `joinGame`；`api/history.ts` 的 `deleteGame(gameId)`；`store/auth.ts` 的 `useAuth`（`user.username`）。
- Produces: `seats.ts` 导出 `ME = "me"`、`meSeat(assignment: SeatSlot[]): number | null`；`SeatSlot.agentId` 取值扩为「库 id | `ME` | null」；`assignmentSummary` 返回新增 `humanSeat: number | null`，`agentSeats` 不计「我自己」。

- [ ] **Step 1: 写失败测试**

`frontend/src/lib/seats.test.ts` 追加（沿用文件里的 `LIBRARY` / `agent()`）：

```ts
import { ME, meSeat } from "./seats";

describe("「我自己」座位（issue #115）", () => {
  it("meSeat 找到真人座位；buildAgentsPayload 不把它写进 agents；summary 单独计数", () => {
    const assignment: SeatSlot[] = [
      { seat: 0, agentId: "a_owl" },
      { seat: 1, agentId: ME },
      { seat: 2, agentId: null },
    ];
    expect(meSeat(assignment)).toBe(1);
    expect(meSeat([{ seat: 0, agentId: null }])).toBeNull();
    const payload = buildAgentsPayload(assignment, "a_fox", LIBRARY);
    expect(Object.keys(payload).sort()).toEqual(["*", "0"]);
    const summary = assignmentSummary(assignment, null);
    expect(summary).toEqual({ agentSeats: 1, restSeats: 1, filled: false, humanSeat: 1 });
    expect(memoryConflicts(assignment, LIBRARY).has(ME)).toBe(false);
  });
});
```

（若 `LIBRARY` 里的 `a_fox` 配了 `memory_id`，`buildAgentsPayload` 会抛「填满档案不得配置 memory_id」——改用库里无 memory_id 的那个档案 id 作 fill，或传 `null` 并把期望键改为 `["0"]`。）

`frontend/src/pages/Lobby.test.tsx` 追加：

```tsx
import { useAuth } from "../store/auth";

const PRESET = {
  name: "std_9_kill_side",
  num_players: 9,
  roles: [],
  sheriff: true,
  win_condition: "KILL_SIDE",
  description_zh: "标准 9 人局",
};

function stubLobbyFetch(joinStatus = 200): ReturnType<typeof vi.fn> {
  const fetchMock = vi.fn(async (rawUrl: string, init?: RequestInit) => {
    const url = rawUrl.split("?")[0] as string;
    const ok = (body: unknown, status = 200): Response =>
      new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
    if (url.endsWith("/tts/status")) return ok({ enabled: false, ok: false, url: null, detail: null, supports_style: false });
    if (url.endsWith("/presets")) return ok([PRESET]);
    if (url.endsWith("/games") && init?.method === "POST")
      return ok({ game_id: "g9", host_token: "H", gm_token: "G", share_token: null, config: {}, agents: {}, voice: false, narration: false });
    if (url.endsWith("/join"))
      return joinStatus === 200 ? ok({ player_token: "P", seat: 3, ws_url: "/api/v1/ws?token=P" }) : ok({ detail: "座位 3 已被占用" }, joinStatus);
    if (url.endsWith("/start")) return ok({ ok: true, num_players: 9 });
    if (init?.method === "DELETE") return new Response(null, { status: 204 });
    return ok([]);
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function bodyOf(fetchMock: ReturnType<typeof vi.fn>, suffix: string): Record<string, unknown> {
  const call = fetchMock.mock.calls.find(([u]) => (u as string).split("?")[0]?.endsWith(suffix)) as
    | [string, RequestInit]
    | undefined;
  return JSON.parse((call?.[1]?.body as string) ?? "{}") as Record<string, unknown>;
}

async function pickMeOnSeat3(): Promise<void> {
  await screen.findByText("标准 9 人局");
  fireEvent.click(screen.getByRole("button", { name: /下一步 · 分配座位/ }));
  fireEvent.change(await screen.findByLabelText("3号 座位"), { target: { value: "me" } });
  fireEvent.click(screen.getByRole("button", { name: /下一步 · 汇总/ }));
}

describe("Lobby 我自己入座（issue #115）", () => {
  it("建局 → 以 3 号入座 → 开始 → 跳到玩家页；带真人时限", async () => {
    const fetchMock = stubLobbyFetch();
    useAuth.setState({ status: "authed", user: { username: "alice" } as never });
    window.location.hash = "#/";
    render(<Lobby />);
    await pickMeOnSeat3();
    expect(screen.getByText(/你将以 3号 入座/)).toBeInTheDocument();
    fireEvent.click(screen.getAllByRole("button", { name: "创建并开始" })[0] as HTMLElement);
    await vi.waitFor(() => expect(window.location.hash).toBe("#/g/g9?player=P"));
    expect(bodyOf(fetchMock, "/join")).toEqual({ display_name: "alice", seat: 3 });
    const create = bodyOf(fetchMock, "/games");
    expect(create.config_override).toEqual({ speech_timeout_sec: 120, action_timeout_sec: 60 });
    expect(create.agents).toEqual({});
  });

  it("join 失败：展示错误并可删除这局", async () => {
    const fetchMock = stubLobbyFetch(409);
    useAuth.setState({ status: "authed", user: { username: "alice" } as never });
    window.location.hash = "#/";
    render(<Lobby />);
    await pickMeOnSeat3();
    fireEvent.click(screen.getAllByRole("button", { name: "创建并开始" })[0] as HTMLElement);
    await screen.findByText(/409 · 座位 3 已被占用/);
    fireEvent.click(screen.getByRole("button", { name: "删除这局" }));
    await vi.waitFor(() =>
      expect(
        fetchMock.mock.calls.some(([u, init]) => (u as string).endsWith("/games/g9") && (init as RequestInit).method === "DELETE"),
      ).toBe(true),
    );
    expect(window.location.hash).toBe("#/");
  });
});
```

（文件顶部已有 `fireEvent, render, screen` 与 `vi` 的 import；`vi.waitFor` 需 vitest ≥ 0.34，否则用 `@testing-library/react` 的 `waitFor`。）

- [ ] **Step 2: 跑测试确认失败**

Run: `cd frontend && npx vitest run src/lib/seats.test.ts src/pages/Lobby.test.tsx`
Expected: FAIL（`ME` 不存在；座位下拉没有 `me` 选项）。

- [ ] **Step 3: `seats.ts`**

```ts
/** 座位槽里的「我自己（真人）」哨兵值（issue #115）；库里的 agent_id 都是 `a_` 前缀，不会撞。 */
export const ME = "me";

/** 一行座位的选择；`agentId` 为 null = 随机 bot（有 fill 时该座由 `"*"` 覆盖），为 ME = 我自己。 */
export interface SeatSlot {
  seat: number;
  agentId: string | null;
}

export function meSeat(assignment: SeatSlot[]): number | null {
  return assignment.find((s) => s.agentId === ME)?.seat ?? null;
}
```

`buildAgentsPayload` 的循环里 `if (slot.agentId === null) continue;` 改为 `if (slot.agentId === null || slot.agentId === ME) continue;`。`memoryConflicts` 同样跳过 `ME`。`AssignmentSummary` 加 `humanSeat: number | null`，`assignmentSummary` 改为：

```ts
export function assignmentSummary(
  assignment: SeatSlot[],
  fill: string | null,
): AssignmentSummary {
  const humanSeat = meSeat(assignment);
  const agentSeats = assignment.filter((s) => s.agentId !== null && s.agentId !== ME).length;
  const restSeats = assignment.length - agentSeats - (humanSeat === null ? 0 : 1);
  return { agentSeats, restSeats, filled: fill !== null, humanSeat };
}
```

（保留原函数里 `filled` 的既有算法；若原实现对 `filled` 另有条件，沿用之。）

- [ ] **Step 4: `SeatAssignment.tsx`**

import `ME`。组件里加 `const meTaken = assignment.some((s) => s.agentId === ME);`。座位下拉第一个 `<option value="">…</option>` 之后插入：

```tsx
                    <option value={ME} disabled={meTaken && slot.agentId !== ME}>
                      我自己（真人）{meTaken && slot.agentId !== ME ? "（已在其他座位）" : ""}
                    </option>
```

图例第二行追加文案：「「我自己」只能占一个座位；建局后你以该座位入座并直接进入玩家页。」

- [ ] **Step 5: `Lobby.tsx`**

1. import：`joinGame` 并入 `../api/rest` 的 import；`import { deleteGame } from "../api/history";`、`import { ME, meSeat } from "../lib/seats";`（并入现有 seats import）、`import { useAuth } from "../store/auth";`。
2. state 区加：

```tsx
  const user = useAuth((s) => s.user);
  const [displayName, setDisplayName] = useState("");
  const [speechTimeout, setSpeechTimeout] = useState("120");
  const [actionTimeout, setActionTimeout] = useState("60");
  /** 三步编排中途失败留下的未开局对局：给「删除这局」用。 */
  const [failedGame, setFailedGame] = useState<string | null>(null);
  const me = meSeat(assignment);
  const effectiveName = displayName.trim() || user?.username || "我";
```

3. `createAndStart` 整体替换为：

```tsx
  async function createAndStart(): Promise<void> {
    if (preset === null || creating) return;
    setCreating(true);
    setCreateError(null);
    setFailedGame(null);
    let gameId: string | null = null;
    try {
      const body: CreateGameRequest = { preset: preset.name, agents: agentsPayload, voice, narration: voice && narration };
      const override: Record<string, unknown> = {};
      const seedTrimmed = seed.trim();
      if (seedTrimmed !== "") {
        const n = Number(seedTrimmed);
        if (!Number.isInteger(n)) throw new ApiError(400, "seed 必须是整数");
        override.seed = n;
      }
      if (me !== null) {
        // 真人座位：发言 / 行动时限放宽（issue #115）
        const sp = Number(speechTimeout);
        const ac = Number(actionTimeout);
        if (!Number.isInteger(sp) || sp <= 0 || !Number.isInteger(ac) || ac <= 0) {
          throw new ApiError(400, "时限必须是正整数（秒）");
        }
        override.speech_timeout_sec = sp;
        override.action_timeout_sec = ac;
      }
      if (Object.keys(override).length > 0) body.config_override = override;
      const res = await createGame(body);
      gameId = res.game_id;
      if (me === null) {
        await startGame(res.game_id, res.host_token);
        setCreated({ gameId: res.game_id, gmToken: res.gm_token, shareToken: res.share_token });
        return;
      }
      // 我自己入座：建局 → 以指定座位入座（cookie）→ 开始 → 直接进玩家页；GM 链接不展示
      const joined = await joinGame(res.game_id, { display_name: effectiveName, seat: me });
      await startGame(res.game_id, res.host_token);
      window.location.hash = `#/g/${res.game_id}?player=${encodeURIComponent(joined.player_token)}`;
    } catch (err) {
      setCreateError(err instanceof ApiError ? `${err.status} · ${err.detail}` : String(err));
      if (gameId !== null) setFailedGame(gameId);
    } finally {
      setCreating(false);
    }
  }

  async function discardFailedGame(): Promise<void> {
    if (failedGame === null) return;
    try {
      await deleteGame(failedGame);
      setFailedGame(null);
      setCreateError(null);
    } catch (err) {
      setCreateError(err instanceof ApiError ? `${err.status} · ${err.detail}` : String(err));
    }
  }
```

4. 步骤 3 的说明文字 `创建后自动开始，你以上帝视角实时观看。` 改为：

```tsx
                {me === null
                  ? "创建后自动开始，你以上帝视角实时观看。"
                  : `你将以 ${me}号 入座，创建后直接进入玩家页；对局结束前看不到上帝视角。`}
```

5. 步骤 3 的 `review` 区块内，`seed` 行之后加（仅 `me !== null` 时渲染）：

```tsx
              {me !== null && (
                <>
                  <div className={styles.reviewRow}>
                    <span className={styles.reviewKey}>我的显示名</span>
                    <input
                      className="input"
                      aria-label="我的显示名"
                      value={displayName}
                      placeholder={user?.username ?? "我"}
                      onChange={(e) => setDisplayName(e.target.value)}
                    />
                  </div>
                  <div className={styles.reviewRow}>
                    <span className={styles.reviewKey}>发言时限（秒）</span>
                    <input className="input" aria-label="发言时限" inputMode="numeric" value={speechTimeout} onChange={(e) => setSpeechTimeout(e.target.value)} />
                  </div>
                  <div className={styles.reviewRow}>
                    <span className={styles.reviewKey}>行动时限（秒）</span>
                    <input className="input" aria-label="行动时限" inputMode="numeric" value={actionTimeout} onChange={(e) => setActionTimeout(e.target.value)} />
                  </div>
                </>
              )}
```

6. `{createError && <div className={styles.error}>{createError}</div>}` 改为：

```tsx
            {createError && (
              <div className={styles.error}>
                {createError}
                {failedGame !== null && (
                  <>
                    {" "}
                    <button type="button" className="btn btn-ghost" onClick={() => void discardFailedGame()}>
                      删除这局
                    </button>
                  </>
                )}
              </div>
            )}
```

7. `navHint` 文案改为 `me === null ? "POST /games → /start → #/g/{id}?gm=…" : "POST /games → /join → /start → #/g/{id}?player=…"`。
8. 汇总侧栏文案：`{summary.agentSeats} 个 Agent` 之后若 `summary.humanSeat !== null` 追加 ` · 我在 ${summary.humanSeat}号`。
9. 步骤 2 说明追加一句「选「我自己」即亲自入座一个座位。」

- [ ] **Step 6: 跑检查**

Run: `cd frontend && npm run check`
Expected: 全绿。既有 Lobby 旁白测试的 fetch 桩返回 `[]` 给 `/presets`，不受影响。

- [ ] **Step 7: 提交**

```bash
git add frontend/src
git commit -m "feat(frontend): Lobby 支持「我自己」入座——create→join→start 编排、真人时限、失败可删 (issue #115)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 12: 文档与全量门禁

**Files:**
- Modify: `README.md`（「API 快速开始」第 2 步注释、「多用户」节）
- Modify: `docs/specs/requirements.md`（M4 判据状态）
- 核验：引擎零 diff、fixtures 零 diff

- [ ] **Step 1: README**

在 `## 多用户 / Multi-user` 节末尾追加小节：

```markdown
### 自己入座 / Play a seat yourself（issue #115）

- Lobby 第 2 步把任一座位选成「我自己（真人）」，第 3 步可改显示名与时限（默认发言 120 秒、行动 60 秒），点「创建并开始」后直接进入玩家页 `#/g/{id}?player=…`。
- 玩家页只显示你这个座位可见的信息；轮到你时底部行动区按阶段给出发言 / 投票 / 夜间技能 / 警长行动 / 自爆。
- **上帝视角封锁**：建局者入座后，到对局结束前 `?gm=` 链接返回 403、裸 `#/g/{id}` 自动变成玩家页；分享链接仍是观众视角；终局后自动恢复，可看全局回放。
- API：`POST /games/{id}/join` 支持 `seat` 指定座位；`GET /state` `GET /meta` 响应带 `viewer`（`GM` / `SPECTATOR` / 座位号）。
```

「API 快速开始」第 2 步的注释 `# 2) （可选）真人加入任意空座…` 后补一行 `#    body 可带 "seat": N 指定座位（issue #115）`。

- [ ] **Step 2: requirements.md**

找到 M4 一行（`- **M4 — 玩家视角 + 真人参与**…`），在其后追加一行：`  - 2026-10：Web 玩家视角与真人入座已实现（issue #115 子项目一，spec `docs/superpowers/specs/2026-10-23-human-seat-player-view-design.md`）；阵营组队见子项目二。`

- [ ] **Step 3: 全量门禁**

```bash
cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy app && uv run pytest -q --ignore=tests/test_api_e2e.py && uv run pytest tests/test_api_e2e.py -q
cd ../frontend && npm run check
cd .. && git diff --stat main -- backend/app/engine frontend/src/engine/__fixtures__
```

Expected：后端全绿（e2e 的 `test_acceptance_human_can_take_any_seat[5]` 超时属已知 #74）；前端全绿；最后一条 `git diff --stat` **无输出**（引擎与 fixtures 零改动）。

- [ ] **Step 4: 提交**

```bash
git add README.md docs/specs/requirements.md
git commit -m "docs: 真人入座与玩家视角使用说明，M4 状态 (issue #115)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```
