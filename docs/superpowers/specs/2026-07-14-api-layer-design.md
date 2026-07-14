# api 层设计 —— FastAPI REST + WebSocket + token 认证（issue #30，M2.3）

日期：2026-07-14
关联：issue #30（父 issue #25，PRD §4.1/§5）
前置：#28 store、#29 runtime（本分支叠于 feat/event-store，PR #33 合并后重定向 main）

## 目标

实现 `backend/app/api/` 与 `backend/app/schemas/`：REST + WS 薄层，只做鉴权、
序列化、转发；真人与 Agent 走完全相同的玩家 API。每条推送/响应按视角经
`build_observation()` / `visible_events` 过滤 —— 前端零过滤；api 层零裁决。

## 决策摘要

| 决策点 | 结论 |
|---|---|
| issue #37（竞选游标回放保真） | 本期不修；重连限"存活进程内 WS 重连"，#37 改标 M3 前置 |
| 真人行动桥接 | Future 型 `HumanPlayerPort`：runner 侧机制零改动，REST/WS 提交解析 Future |
| 广播异常隔离（#29 遗留前置） | 本期修：坏订阅者被摘除并记日志，不再中断同批投递 |
| 观战 | API 级 `allow_spectators` 建局开关（非 GameConfig 规则）；观战=PUBLIC 视角，GM 回放仅局终 |

## 模块划分

### app/runtime/registry.py（新，runtime 侧）
- `GameRegistry`：进程内对局登记表，`game_id -> GameHandle{lobby, store,
  connections, runner, task}`。
- 生命周期：`POST /games` 建 lobby + 签发 token；`start` 前校验**每个座位有
  port**（AI 座配 `BotPlayerPort`，真人座配 `HumanPlayerPort`），随后
  `asyncio.create_task(runner.run())`；task 异常 fail-loud：记录并在后续触碰
  该局的 API 调用返回 500 附因。
- 单进程内存态（PRD §8.1 MVP 口径）；store 用 `JsonFileEventStore`（可配目录），
  测试可注入 `InMemoryEventStore`。

### app/runtime/connection.py（加固，#29 评审前置项）
- `broadcast` 逐回调 try/except：回调抛错 → 摘除该订阅者 + `logging` 告警，
  继续投递后续订阅者；异常不进 runner `_commit`。投递顺序不变。

### app/runtime/player_port.py（扩展）
- `HumanPlayerPort`：
  - `act(observation, deadline_ts)`：置"已开窗"状态（供 my-turn 长轮询与 409
    判定），经已附着的 WS sender 推 `your_turn`（无连接则静默——玩家可经
    REST 发现），然后 `await` 一个 `asyncio.Future[Action]`。
  - `submit(action) -> None`：REST/WS 提交解析 Future；未开窗提交 → 抛
    `NotYourTurnError`（API 映射 409）。引擎拒绝后 runner 按既有重试机制再次
    `act` —— 端口重新开窗，拒因经 HTTP 响应体返回（PRD §4.1 统一信封）。
  - `attach_sender(cb)` / `detach_sender()`：WS 连接期挂接 `your_turn` 推送。
  - 超时/默认行动完全沿用 runner 既有机制，端口零超时逻辑。

### app/api/deps.py
- `TokenRegistry`（内存 dict，MVP）：`secrets.token_urlsafe` 不透明串 →
  `TokenInfo{game_id, seat: int | None, kind: PLAYER | SPECTATOR}`。
- REST `Authorization: Bearer <token>`；WS `?token=`。未知 token → 401；
  token 的 game_id 与路径不符 / 观战者调玩家端点 → 403。

### app/schemas/
- 请求/响应 Pydantic 模型。行动 body 即 PRD §4.1 工具调用：
  `{"tool": <name>, "arguments": {...}}`，tool → 引擎 Action 映射：
  - `speak` → `Speak`（content/claim_role[NONE→None]/badge_flow）
  - `vote` → `DayVote`（target_seat/abstain）
  - `night_action` → `NightAction`（action_type/target_seat）
  - `sheriff_action` → `SheriffAction`（action_type/target_seat/direction）
  - `bid_to_speak` → 原样转发（引擎按 config 裁决，未启用返回
    `BIDDING_NOT_IMPLEMENTED`）
  - `self_destruct` → `SelfDestruct`（**规格扩展**：§4.1 工具表漏列自爆，
    引擎 Action 联合已含，API 补齐该工具名）
  - `actor_seat` 一律取自 token，**不接受 body 指定**（防冒充）。
- 统一行动响应信封：`{ok, event_id, state_version, rejected_reason}`。

### app/api/rest.py —— PRD §5.2 全表（前缀 /api/v1）
| Endpoint | 语义 |
|---|---|
| POST /games | preset + config_override + num_ai_players + allow_spectators → game_id、host player_token、（可选）spectator_token |
| POST /games/{id}/join | display_name + player_type → player_token、seat、ws_url |
| POST /games/{id}/start | 仅房主 token；body `{fill_with_bots: bool = true}`：true 则缺员座位 AI 填充后开局，false 且未满员 → 409；起 runner task |
| GET /games/{id}/state | 玩家=`build_observation(live, seat)`；观战=公开视图（seats/phase/round/sheriff） |
| GET /games/{id}/speeches | store 中 PUBLIC 的 PLAYER_SPOKE/LAST_WORDS（round/phase 可选过滤，§4.1 get_speeches 口径） |
| POST /games/{id}/actions | 工具调用 → Action → `HumanPlayerPort.submit`；非开窗 409；引擎拒绝 → ok:false + rejected_reason |
| GET /games/{id}/my-turn | 长轮询：挂起至端口开窗（返回 your_turn 负载）或超时（204） |
| GET /games/{id}/events?from_seq= | store 事件经 `visible_events`（本 viewer）过滤；from_seq 闭区间（store 既有口径） |
| GET /games/{id}/replay | 仅 GAME_OVER 后；GM 全量事件日志 |

### app/api/ws.py
- `GET /api/v1/ws?token=&from_seq=`：鉴权 → （可选）按 from_seq 补发该视角
  历史事件 → 订阅 `ConnectionManager`（viewer=seat 或 SPECTATOR）→ 若玩家，
  `attach_sender` 到其 `HumanPlayerPort`。
- 服务器→客户端：`your_turn`（observation + available_tools + deadline_ts）、
  `game_event`（`{type, seq, event}`，已过滤）、`phase_change`（仅由**该视角
  可见的** PHASE_CHANGED 事件派生——多数 PHASE_CHANGED 为 GM_ONLY 属预期，
  权威 phase 始终随 your_turn/GET state 下发）、`game_over`（PUBLIC）。
- 客户端→服务器：行动帧与 POST /actions 等价（同 schema 同响应信封）。
- 断开：`detach_sender` + 取消订阅；重连凭同 token + from_seq 恢复视角
  （存活进程内；服务器重启恢复 = #37 之后的里程碑）。

### app/main.py
- FastAPI 装配：lifespan 持有 `GameRegistry`/`TokenRegistry`，路由挂载，
  异常处理器（StoreError/LobbyError/NotYourTurnError → 4xx 映射）。

## 硬约束（复述自 CLAUDE.md / issue #30）

- api 层不含任何裁决逻辑；intent 全部转发 runtime/port
- 信息隔离唯一实现点仍是引擎 `build_observation`/`visible_events`
- engine/store/runtime 不 import api；api 可 import 全部下层
- 新增生产依赖：`fastapi`、`uvicorn`；测试依赖：`httpx`（TestClient 需要）

## 测试策略（httpx TestClient，含 WS）

1. **全 AI 集成**：POST /games(num_ai=12) → start → 观战 WS 收流至 game_over；
   GET /replay 全量日志；store 回放终局口径一致。
2. **真人座集成**：8 AI + 1 真人；测试经 API 收 your_turn（WS）并提交合法行动
   （白盒从 registry 的 runner.state 选行动）；整局跑通。
3. **隔离经 API**：狼座 token 收到 WOLVES 事件、村民 token 收不到；观战永无
   GM_ONLY；与 test_isolation 口径一致。
4. **越权**：他人 token 提交 → 403；未开窗提交 → 409；观战者 POST actions →
   403；局中 GET /replay → 403；未知 token → 401。
5. **拒绝与重试**：提交非法工具调用 → ok:false + rejected_reason，随后合法
   提交成功（同一窗口内）。
6. **重连**：WS 断开后凭同 token + from_seq 重连，补发的事件序列 == 该视角
   错过的可见事件后缀；长轮询 my-turn 返回与 WS your_turn 同负载。
7. **广播隔离单测**：注入抛错订阅者 → 被摘除、其余订阅者照常收流、对局不受影响。
8. 质量门：`uv run pytest`、`uv run mypy app`（strict）、`uv run ruff check .`。

## 明确不做（YAGNI）

- #37 修复（M3 前置另行处理）；服务器重启续局；Redis/多进程/JWT；AFK bot 接管；
  竞价发言的引擎实现（工具转发即可，引擎按 config 拒绝）；前端（M3）；
  LLM Agent 接入（M2.4，届时 AgentPlayer 可同栈或经内部 port 直连）。
