# M3 前端：上帝视角直播 + 基础回放 + TS 同构 reducer — 设计文档

> 日期：2026-09-23 · 状态：已批准 · 关联：GitHub issue #26（M3）；前置 #37（游标入流，已合并）、#34（负载序列化，已合并）· 上游：`docs/specs/requirements.md` §1.3（硬约束）、§7（前端设计）、§9 M3；API/WS 实际契约以 `backend/app/api/{rest,ws,views}.py` 为准（PRD §7.4 示例帧字段与实现不一致处，以实现为准）

## 1. 目标与交付判据

观众打开一个链接就能**实时观看一局全 AI 对局**（默认上帝视角：身份、夜间行动全部可见），终局后可**拖动回放**；直播态与回放态用**同一个 TS `reduce()`** 推导 UI 状态，且该 reducer 与后端逐事件等价（金样对拍）。

**交付判据**：
- 后端新增 `gm_token`：持有者经 `/state`、`/events`、`/replay`、`/meta`、WS 拿到 GM 全量（含 `GM_ONLY` / `WOLVES` / `ROLE_SELF` 事件）；观众 token 行为逐字不变；GM 不能行动 / 不能开局。
- `python -m app.cli.export_fixture` 生成金样（meta + 全部事件 + 每条事件后的完整状态）；`make fixtures` 生成 4 个 preset 各 1 局并入库。
- `frontend/`：Vite + React 18 + TS strict + Zustand + Vitest；`npm run check`（lint + tsc + vitest）全绿；`make fe-check` 接入根 `make check`。
- Vitest 金样测试：4 个 fixture 逐事件 `reduce` 与后端状态深度相等；未知事件类型抛错。
- 对局页：GM 直播（座位环 / 发言流含夜间私有行 / 阶段栏 / 夜间遮罩 / 投票与竞选面板）跑到终局；观众链接同一页面只渲染 PUBLIC 事件。
- 回放：终局后 `GET /replay` 装入，`ReplayBar` 拖动 / 播放 / 步进 / 倍速；直播中亦可拨回历史再「回到直播」。
- 前端**零信息过滤**：所有可见性裁剪由服务端 token 决定，前端按事件存在与否渲染。
- 部署：`frontend/dist` 存在时后端挂静态站点；开发用 Vite 代理，不改 CORS。
- **模型服务 Provider（后端持久化）**：`GET/POST/PUT/DELETE /api/v1/providers`（`data/providers/<id>.json`，密钥永不回传）、`POST /providers/{id}/test`、`GET /providers/{id}/models`；`AgentProfile.provider` 指向 provider，调用时后端按 provider 传 `api_base` / `api_key`；`provider` 为空时行为与现状逐字相同（`model` 含 LiteLLM 前缀、走环境变量）。
- **Agent 档案库（后端持久化）**：`GET/POST/PUT/DELETE /api/v1/agents`（`data/agents/<agent_id>.json`），`GET /api/v1/skills`、`GET /api/v1/presets`；前端 **AgentLibrary / AgentEditor / SeatAssignment** 三个 UI 让用户定义 Agent（名字、模型、人格、技能、记忆标识）并挑选多个放到座位上开局，建局请求自动装成 `agents: {seat: AgentProfile}`。

## 2. 后端：GM token 与状态端点

- `app/api/deps.py`：`TokenInfo.kind: Literal["HOST", "PLAYER", "SPECTATOR", "GM"]`。
- `app/schemas/games.py`：`CreateGameResponse.gm_token: str`（建局响应新增；与 `host_token` 一样只给建局者）。`rest.py` 建局时 `tokens.issue(TokenInfo(game_id, seat=None, kind="GM"))`。
- 授权矩阵（`require_kind`）：
  | 端点 | HOST | PLAYER | SPECTATOR | GM |
  |---|---|---|---|---|
  | `POST /start` | ✅ | ✗ | ✗ | ✗ |
  | `GET /state` | ✗ | ✅（`PlayerObservation`） | ✅（`SpectatorView`） | ✅（`GameState.model_dump(mode="json")`） |
  | `GET /events`、`GET /speeches` | ✗ | ✅ | ✅ | ✅ |
  | `GET /replay`、`GET /meta` | ✅（终局后） | ✅ | ✅ | ✅ |
  | `POST /actions`、`GET /my-turn` | ✗ | ✅ | ✗ | ✗ |
  | WS | ✗（4403） | ✅ | ✅ | ✅ |
- viewer 映射：`GM` → `"GM"`（`visible_events` 全量；`event_json_for_viewer` 不裁 `meta`）；`/events` 与 WS 的 `viewer` 计算处各加一行。
- `/state` 的 GM 分支返回引擎 `GameState` 全量投影（`model_dump(mode="json")`），供前端重连时的兜底核对（正常路径以 `reduce` 为准，见 §5）。
- 测试（`tests/test_api_e2e.py` / `test_api_ws.py` / `test_api_lobby.py`）：GM `/events` 含三种非 PUBLIC 可见性事件且 `meta.skills` 保留；GM WS 帧同；观众流仍 100% PUBLIC；GM `/actions` 403、`/start` 403；`/state` GM 返回 `phase`/`players[*].role`。

## 2b. 后端：Agent 档案库与建局辅助端点

**存储（`app/runtime/agent_library.py`，IO 层）**
- 文档：`StoredAgent = {agent_id: str, profile: AgentProfile, created_at: str, updated_at: str}`；`agent_id` 服务端生成（`a_` + 8 位十六进制），文件 `data/agents/<agent_id>.json`，原子写（临时文件 + `os.replace`，与 `experience_store` 同法）；坏文件 → `StoreCorruptionError`（列表接口跳过并记 warning，单个读取 500）。
- `AgentLibraryStore` 协议：`list() -> list[StoredAgent]`、`get(id)`、`put(stored)`、`delete(id)`；`InMemoryAgentLibrary`（测试）与 `JsonFileAgentLibrary(dir)`；`create_app(agents_dir=None, agent_library=None)` 默认 `data/agents`（惰性建目录）。
- 校验：`profile` 走 `AgentProfile`（extra=forbid）；`profile.name` 必填且**库内唯一**（同名 409）；`memory_id` 可选、库内唯一（同 id 409——两个档案共用一份记忆会互相污染）；技能名经 `SkillLibrary.resolve` 校验（未知 → 400）；人格护栏 → 422（pydantic）。

**端点（`app/api/agents.py`，前缀 `/api/v1`，无鉴权——与建局一致，M3 单用户本地部署）**
| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/agents` | `[{agent_id, profile, created_at, updated_at}]`，按 `updated_at` 倒序 |
| POST | `/agents` | body `AgentProfile`（含 `name`）→ 201 `StoredAgent` |
| GET | `/agents/{id}` | 404 不存在 |
| PUT | `/agents/{id}` | 整体替换 `profile`；`updated_at` 刷新；改 `memory_id` 不迁移经验文件（文档说明） |
| DELETE | `/agents/{id}` | 204；不删除 `data/agent_memory/<memory_id>.json`（经验属于 `memory_id`，可被另一档案复用） |
| GET | `/skills` | `[{name, description, roles, phases}]`（`default_library()` + `AGENTHOWL_SKILLS_DIR`） |
| GET | `/presets` | `[{name, num_players, roles: [{role, count}], sheriff: bool, description_zh}]`（`_PRESETS`；中文说明表放 `app/schemas/presets.py`） |

- 建局请求不变：前端把 SeatAssignment 的结果装成 `agents: {"0": profile, "3": profile, "*": profile?}` 发 `POST /games`（档案内容随请求传，后端不按 `agent_id` 反查——`GameMeta.agents` 仍记录完整档案，与 #64 一致）。
- 测试（`tests/test_api_agents.py`、`tests/test_agent_library.py`）：CRUD 往返、同名 / 同 memory_id 409、未知技能 400、护栏 422、坏文件跳过、目录惰性创建、`/skills` 含内置 14 个、`/presets` 4 个且 `num_players` 正确。

## 2c. 后端：模型服务 Provider

**模型（`app/agent/provider.py`，纯 pydantic）**
- `ProviderKind = Literal["ollama", "openai", "anthropic", "openai_compatible", "gemini", "deepseek"]`——值即 LiteLLM 模型前缀（`openai_compatible` 映射为 LiteLLM 的 `openai/` 前缀 + 自定义 `api_base`）。
- `Provider = {provider_id: str, name: str, kind: ProviderKind, api_base: str | None, api_key: str | None, default_model: str | None, created_at, updated_at}`；`provider_id` 服务端生成（`p_` + 8 位十六进制）；`name` 库内唯一（409）。
- `ProviderPublic`（API 响应）：去掉 `api_key`，加 `has_key: bool`、`key_hint: str | None`（末 4 位）。
- `resolve_model(profile_model: str, provider: Provider | None) -> tuple[str, dict[str, str]]`：`provider` 为 None → `(profile_model, {})`（现状）；否则 `(f"{prefix}/{profile_model}", {"api_base": …, "api_key": …})`（只放非空项；`openai_compatible` → 前缀 `openai`）。

**存储（`app/runtime/provider_store.py`）**：`ProviderStore` 协议 `list/get/put/delete`；`InMemoryProviderStore` / `JsonFileProviderStore(dir)`（原子写；文件权限 `0600`；坏文件 → `StoreCorruptionError`，列表跳过并记 warning）；`create_app(providers_dir=None, provider_store=None)` 默认 `data/providers`（惰性建目录）。

**接入调用链**
- `AgentProfile.provider: str | None = None`（provider_id；`extra=forbid` 不变）。`validate_profiles(..., providers=None)`：给了 provider 集合时校验引用存在（未知 → 400）。
- `to_agent_config(profile, game_config, provider=None)` 用 `resolve_model` 填 `model` / `model_speech` / `reflection_model`（三者共用同一 provider）。**凭据绑定在每个端口的 `LiteLLMInstructorClient(api_base=, api_key=)` 实例上**（实现期附注：`build_agent_port` 本就为每个端口新建客户端，因此 `AgentConfig` / `complete_structured` / `memory.reflect` / `reflect_on_game` 签名零改动，`ScriptedLLMClient` 不受影响）。
- registry / CLI 建端口时按 `profile.provider` 从 `ProviderStore` 取 provider（registry 在 `start()`；CLI `--providers-dir`，默认 `data/providers`）；`GameRegistry(provider_store=)`。
- **隔离**：`GameMeta.agents` 记录的 `AgentProfile` 只含 `provider` id 与模型名，**永不含密钥**；日志（logger）不得打印 `api_key`；`/meta`、建局回显同理。

**端点（`app/api/providers.py`，前缀 `/api/v1`，无鉴权）**
| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/providers` | `[ProviderPublic]` |
| POST | `/providers` | body `{name, kind, api_base?, api_key?, default_model?}` → 201 `ProviderPublic` |
| GET / PUT / DELETE | `/providers/{id}` | PUT 时 `api_key` 省略 = 保留原密钥、`""` = 清除；DELETE 若有档案引用 → 409 列出档案名 |
| POST | `/providers/{id}/test` | 用 `default_model`（或 body `{model}`）发一条最小补全（`max_tokens=8`，5s 超时）→ `{ok, latency_ms, error?}` |
| GET | `/providers/{id}/models` | Ollama：`GET {api_base}/api/tags`；openai / openai_compatible / deepseek：`GET {api_base}/v1/models`；anthropic / gemini：返回内置静态列表；失败 → `{models: [], error}`（不 5xx） |

- 测试（`tests/test_provider.py`、`tests/test_api_providers.py`）：`resolve_model` 三种情形；响应不含 `api_key` 且 `key_hint` 正确；PUT 省略 / 清空密钥语义；被引用时 DELETE 409；文件 0600；`test` / `models` 端点用假 HTTP（`httpx.MockTransport`，唯一允许的 fake）；`to_agent_config` 填凭据；`AgentPlayerPort` 把 `api_base`/`api_key` 传给 `complete_structured`（ScriptedLLMClient 记录 kwargs）；`GameMeta.agents` 与建局回显不含密钥。

## 3. 金样导出 CLI（`backend/app/cli/export_fixture.py`）

```
python -m app.cli.export_fixture --preset std_9_kill_side --seed 3 --out ../frontend/src/engine/__fixtures__/std_9_kill_side-3.json
```
- 用随机 bot `run_game` 跑一局（零 LLM）；输出 JSON：
  ```json
  {"preset": "...", "seed": 3, "meta": <GameMeta>, "events": [<event_to_json>...],
   "states": [<GameState.model_dump(mode="json")> ...]}
  ```
  `states[i]` = `reduce_all(initial_state(meta), events[:i+1])`（即每条事件之后）；`meta.agents = {}`。
- 序列化规范（前后端共同遵守，§4 的规范化函数据此）：`frozenset` → **升序数组**；dict 的 int 键 → JSON 字符串键（pydantic 默认）；`tuple` → 数组；枚举 → 字符串值；`None` → `null`。`GameState.model_dump(mode="json")` 的 `frozenset` 默认序列化顺序不保证，导出时统一 `sorted`（在 CLI 内对 `acted_seats` / `sheriff_declared` / `sheriff_withdrawn` / `sheriff_confirmed` 做后处理）。
- `Makefile` `fixtures` 目标：4 个 preset（`std_9_kill_side`、`std_9_kill_all`、`std_12_yn_hunter_idiot`、`std_12_yn_hunter_guard`）各 seed=3 输出到 `frontend/src/engine/__fixtures__/`；README 写明「后端事件 schema 变更 → `make fixtures` → 前端测试变红即漂移，据此改 TS」。
- 后端测试：输出结构；`states[i]` 与 `reduce_all` 前缀相等（复用 `test_replay_invariant` 口径）；`frozenset` 字段已排序。

## 4. 前端工程与工具链（`frontend/`）

- Vite 5 + React 18 + TypeScript 5（`strict`、`noUncheckedIndexedAccess`）+ Zustand 4 + Vitest + `@testing-library/react` + ESLint（typescript-eslint recommended、react-hooks）+ Prettier；npm，`package-lock.json` 入库；`.nvmrc` = 20；CSS Modules，不引 UI 库。
- 目录：
  ```
  frontend/
    index.html  vite.config.ts  tsconfig.json  package.json  .eslintrc.cjs  .prettierrc
    src/main.tsx  src/App.tsx（hash 路由：#/ → Lobby，#/g/{gameId} → GamePage）
    src/engine/{types.ts, reduce.ts, phases.ts, select.ts, normalize.ts}  src/engine/__fixtures__/*.json  src/engine/*.test.ts
    src/api/{rest.ts, ws.ts, tokens.ts, agents.ts, providers.ts}
    src/store/game.ts
    src/components/{SeatCircle, SpeechFeed, PhaseBar, NightOverlay, VotePanel, ElectionPanel, ReplayBar,
                    AgentCard, AgentEditor, PersonalityEditor, SkillPicker, SeatAssignment,
                    ProviderCard, ProviderEditor, ModelSelect}/
    src/pages/{Lobby, AgentLibrary, Providers, GamePage}.tsx
    src/styles/{tokens.css（= docs/design/nocturne.css + 语义色）, global.css}
  ```
- `vite.config.ts`：`server.proxy = {"/api": {target: "http://localhost:8000", ws: true, changeOrigin: true}}`；`build.outDir = "dist"`。
- `package.json` scripts：`dev`、`build`、`preview`、`lint`、`typecheck`（`tsc --noEmit`）、`test`（vitest run）、`check`（lint && typecheck && test）。
- Makefile：`fe-install`（`npm ci`）、`fe-dev`、`fe-check`、`fe-build`、`fixtures`；`check` 目标在 `frontend/node_modules` 存在时追加 `fe-check`（缺 node 环境时后端 check 不受影响）。

## 5. TS 引擎（`src/engine/`，零依赖纯函数）

- `types.ts`：`Phase`、`ElectionStage`（含 `""`）、`RoleType`、`Faction`、`Visibility`、`EventType`（35 个）字面量联合；每个 payload 接口与 `events.py` 一一对应（含 #37：`PhaseChangedPayload{to, speech_order?, pending_hunter?, resume_token?}`、`ElectionStageChangedPayload{stage, speech_order?, skip_day}`、`SheriffVoteStartedPayload{candidates}`）；`Event = {seq, game_id, ts, type, actor_seat, payload, visibility, meta}`；`Player`、`NightActions`、`GameState`（字段与 `state.py` 逐一对应）。集合型字段在 TS 中为**升序 `number[]`**：`acted_seats`、`sheriff_declared`、`sheriff_withdrawn`、`sheriff_confirmed`；int 键 dict 为 `Record<string, …>`（`votes`、`sheriff_votes`、`wolf_proposals`、`seer_log`、`badge_flow_claims`）。`GameMeta = {game_id, config, roster: {seat, display_name}[], agents}`（`config` 按 `unknown`/宽松接口，reducer 只读 `config.num_players`、`config.sheriff.enabled` 等必要字段）。
- `reduce.ts`：`initialState(meta): GameState`（对齐 `event_store.initial_state`：全员 `VILLAGER`/`GOOD`、`alive=true`、`phase="LOBBY"`、`round=0`、其余默认）；`reduce(state, event): GameState`——先 `state_version + 1`，再按 `event.type` 分支，**逐条对齐 `events.py::reduce`**（§3 序列化规范下的语义：如 `SHERIFF_CANDIDACY` 在 `election_stage === "withdraw"` 时把座位并入 `sheriff_confirmed` 并保持升序）；未知 `type` → `throw new Error("未知事件类型")`。`reduceAll(initial, events)`。不可变更新（展开复制），不用 immer。
- `normalize.ts`：`normalizeState(s)`——把集合字段排序、`undefined` 转 `null`，用于金样比较与调试 diff。
- `phases.ts`：中文名表——`PHASE_ZH`（`NIGHT_WEREWOLF` → 狼人行动 …）、`ELECTION_STAGE_ZH`（与 `render.py::_ELECTION_STAGE_ZH` 同文案）、`ROLE_ZH`、`BADGE_LOST_ZH`、`WINNER_ZH`。
- `select.ts`：纯选择器（输入 `GameState` + `Event[]` 前缀）：`aliveSeats`、`wolfSeats`、`currentSpeaker`（`speech_order[speech_idx]`）、`voteTally(state, events)`（当前投票轮的 voter→target 与加权计票，来自最近 `VOTE_STARTED` 之后的 `VOTE_CAST`/`VOTE_RESULT`；`state` 提供 `config.sheriff.vote_weight` 与在场警长座位，用于加权）、`sheriffVoteTally(state, events)`（警上投票同口径计票，1 人 1 票）、`nightSummary(round)`（该夜的守 / 刀提议与决定 / 救 / 毒 / 查验 / 结算死亡——只在事件存在时给出）、`speechItems(events)`（发言 + 遗言 + 夜间私有行的统一 feed 项）。
- 金样测试 `reduce.test.ts`：对每个 fixture：`let s = initialState(meta); events.forEach((e, i) => { s = reduce(s, e); expect(normalizeState(s)).toEqual(normalizeState(states[i])) })`（失败信息含 `seq`/`type`/差异键），末态 `phase === "GAME_OVER"`；`reduce` 对 `type: "NOPE"` 抛错；`select` 的关键选择器在 fixture 上做几条断言（如 `voteTally` 与 `VOTE_RESULT.tally` 一致）。

## 6. store 与数据源（`src/store/game.ts`、`src/api/`）

- `useGameStore`（Zustand）状态：`gameId`、`token`、`viewer: "GM" | "SPECTATOR"`、`meta: GameMeta | null`、`events: Event[]`、`head: GameState | null`、`checkpoints: Map<number, GameState>`（每 50 条事件存一份）、`mode: "live" | "replay"`、`cursor: number | null`（回放游标 seq；`null` = 跟随最新）、`connection: "idle" | "connecting" | "open" | "closed" | "error"`、`error: string | null`、`playing: boolean`、`speed: number`。
- 动作：`load(meta)`（`head = initialState(meta)`）；`appendEvents(batch)`：按 `seq` 过滤已有、要求 `seq === lastSeq + 1`（乱序 / 缺口 → 记录 `gap` 并触发重连补发，不静默丢弃）、逐条 `reduce` 更新 `head`、按需存检查点；`setCursor(seq | null)`；`viewState()`：cursor 为 `null` → `head`，否则取 `≤ cursor` 的最近检查点 re-reduce 到 cursor（memo 上次结果）；`play/pause/setSpeed/stepForward/stepBack`（播放用 `setInterval` 按 `speed` 推进 cursor，到末尾自动暂停）。
- `src/api/rest.ts`：`createGame(req)`、`startGame(gameId, hostToken)`、`getMeta(gameId, token)`、`getReplay(gameId, token)`、`getEvents(gameId, token, fromSeq)`；`ApiError{status, detail}`；`Authorization: Bearer <token>`。
- `src/api/providers.ts`：`listProviders()`、`createProvider()`、`updateProvider()`、`deleteProvider()`、`testProvider(id, model?)`、`listModels(id)`；`useProviders()` store。
- `src/api/agents.ts`：`listAgents()`、`createAgent(profile)`、`updateAgent(id, profile)`、`deleteAgent(id)`、`listSkills()`、`listPresets()`；`useAgentLibrary()`（Zustand 小 store：`agents`、`skills`、`presets`、加载 / 错误态，进入 Lobby 或 AgentLibrary 时拉取）。
- `src/api/ws.ts`：`useLiveEvents({gameId, token, enabled})`——`useRef` 持 `WebSocket`（StrictMode 双挂载安全）、URL `/api/v1/ws?token=…&from_seq=<lastSeq+1>`；收到 `game_event` 帧推入 ref 缓冲，`requestAnimationFrame` 批量 `appendEvents`（每帧最多 200 条）；`phase_change` / `game_over` 帧仅用于轻提示（toast），状态一律来自 `reduce`；`error` 帧写 `error`；关闭码映射：4401 「token 无效」、4403「该 token 无权观战」、4404「对局不存在」、4409「对局尚未开始」；非终局的意外断线按指数退避（1s→8s）重连并从 `lastSeq + 1` 补发；`game_over` 后不再重连。
- 回放来源：进入对局页时若 `meta` 可取且 `head.phase === "GAME_OVER"`（或 `/replay` 200）→ `getReplay` 一次装入、`mode = "replay"`、`cursor = 0`；直播中拖动 `ReplayBar` 即 `cursor` 非 null（`mode` 仍 `live`，新事件继续追加到 `events`/`head`）；「回到直播」→ `cursor = null`。
- `src/api/tokens.ts`：token 只放 URL hash（`#/g/{gameId}?gm=…` 或 `?spec=…`），不写 localStorage；`viewer` 由哪个参数存在决定。
- GamePage 引导顺序固定为 `/meta` → （403 时退回）`/state`：`/meta` 与 `/replay` 只在终局（`GAME_OVER`）后开放（`rest.py::meta_endpoint`/`replay_endpoint` 同门槛，未终局一律 403），故 `/meta` 200 即代表终局对局 → 走上面的回放装入路径；403 代表对局仍在进行或尚未开局 → 改用 `/state`，200 即直播（`mode="live"`），409（未开局）转入轮询重试。

## 7. UI（`src/pages/`、`src/components/`）——供设计稿使用的界面规格

### 7.1 页面与路由
- `#/` **Lobby**：三步建局——选 preset → 分配座位（从档案库挑 Agent）→ 创建并开始。
- `#/agents` **AgentLibrary**：Agent 档案库（列表 / 新建 / 编辑 / 复制 / 删除 / 导入导出）。
- `#/providers` **Providers**：模型服务配置（地址 / 密钥 / 默认模型 / 测试连接 / 拉取模型列表）。
- 顶部导航：对局 · Agent 档案库 · 模型服务。
- `#/g/{gameId}?gm=<token>` / `#/g/{gameId}?spec=<token>` **GamePage**：直播 + 回放；同一页面，GM 与观众只差数据。

### 7.2 Lobby（三步）
```
┌ 步骤 1 选择对局 ─────────────────────────────────────────────┐
│ preset 卡片 ×4（9 人屠边 / 9 人屠城 / 12 人预女猎白 / 12 人预女猎守）│
│ 每张：人数、角色配置 chips、是否有警长、一句说明；seed 输入（默认随机） │
├ 步骤 2 分配座位 ─────────────────────────────────────────────┤
│ 左：档案库侧栏（搜索框；AgentCard 列表：名字 · 模型 · 技能 n · 性格摘要 · 记忆 id；│
│      「+ 新建」跳 AgentEditor 抽屉）                                 │
│ 右：座位表 N 行：[0号] [下拉：随机 bot | 档案A | 档案B …]  …          │
│      工具行：「用 ___ 填满其余座位」(写入 "*")、「全部随机 bot」、「随机打乱」│
│      同一档案可放多个座位（同 memory_id 除外：第二次选择时提示「该记忆已在 2号使用」并禁用）│
├ 步骤 3 创建并开始 ───────────────────────────────────────────┤
│ 汇总：N 座位（x 个 Agent，y 个随机 bot）、seed；主按钮「创建并开始」  │
│ 成功 → 分享卡片（上帝视角链接 / 观众链接 + 复制；安全提示）→ 进入对局页 │
└──────────────────────────────────────────────────────────────┘
```
- 步骤 2 的座位表把选择装成 `agents` 映射：座位专属 → `"{seat}"`，填满其余 → `"*"`，随机 bot 不写。
- 校验前置：`memory_id` 同局唯一由 UI 禁用保证，后端 400 仍原文展示；`"*"` 档案含 `memory_id` 时提示改用逐座位分配（后端会 400）。
- 错误：400/409/422 的 `detail` 原文展示在对应步骤下方。

### 7.2b AgentLibrary 与 AgentEditor
- **AgentLibrary 页**：顶部「Agent 档案库」+「新建」+「导入 JSON」+「导出全部」；网格 `AgentCard`：名字（大）、模型、发言 / 反思模型（有则小字）、技能 chips（最多 3 个 +n）、性格摘要（复用 `personality_summary` 口径：预设代码 / 描述前 12 字 / 首特质）、`记忆 {memory_id}`（有则）、更新时间；卡片操作：编辑、复制（名字加「副本」）、删除（确认框，提示「不会删除该记忆的经验文件」）。空态：插画 + 「还没有 Agent，先建一个」。
- **AgentEditor（右侧抽屉 / 独立页，表单分组）**：
  1. 基本：名字（必填，唯一校验即时提示）；**模型服务** `ModelSelect`：Provider 下拉（来自 `/providers`，末项「未配置——直接写 LiteLLM 模型串」= `provider` 为空的兼容模式）→ 模型下拉（`GET /providers/{id}/models` 的列表，可手输；默认取 provider 的 `default_model`）；发言模型 / 反思模型（可选，同一 provider 下的模型下拉）；温度（滑块 0–2，默认 0.3）；thinking 开关（仅 provider 为 ollama 时显示说明「推理模型思考开关」）。Provider 未配置时显示指向 `#/providers` 的引导链接。
  2. 技能 `SkillPicker`：来自 `GET /skills` 的多选清单（名称 + 描述 + 适用角色 / 阶段 chips）；「全部（*）」开关。
  3. 人格 `PersonalityEditor`：描述（多行，≤300，计数）；特质：从内置 15 词点选加入 + 每个一条 0–1 滑块（可自定义词，≤12 字）；预设：无 / MBTI（四轴 4 个分段选择器 + 可选每轴强度）/ Big Five（5 条滑块）；说话风格（≤100）。实时预览：右侧显示 `render_personality` 的等价文本（前端按同一规则渲染或调用后端预览端点——本期前端渲染一份只读预览，文案以后端为准，不做校验）。护栏短语命中时即时红字（前端复制 `FORBIDDEN_PHRASES` 列表仅做提示，最终以后端 422 为准）。
  4. 记忆：`memory_id`（可选；「按名字生成」按钮：拼音 / 转写为安全字符；唯一校验即时提示）；说明「同一 memory_id 的 Agent 跨局累积经验」。
  - 底部：保存 / 取消；保存失败展示后端 `detail`。

### 7.2c Providers 页
- 顶部「模型服务」+「新建」；卡片 `ProviderCard`：名字、类型徽标（Ollama / OpenAI / Anthropic / OpenAI 兼容 / Gemini / DeepSeek）、地址、密钥状态（「已配置 ····ab12」/「未配置」）、默认模型、连通状态点（最近一次测试：绿 / 红 / 灰未测）、被几个 Agent 引用；操作：编辑、测试连接、删除（被引用时禁用并提示引用的档案名）。
- `ProviderEditor`（抽屉）：名字、类型（选择后自动填默认地址：Ollama `http://localhost:11434`、OpenAI 留空、OpenAI 兼容必填）、API 地址、API 密钥（密码框；编辑时显示「保留现有密钥」占位，留空即不改，「清除」按钮）、默认模型（下拉，来自「拉取模型列表」按钮的结果，可手输）；「测试连接」按钮显示延迟 / 错误原文；保存 / 取消。
- 空态：「还没有模型服务。Ollama 用户：安装后点『新建』选择 Ollama，地址保持默认即可。」

### 7.3 GamePage 布局（桌面优先，≥1200px 三栏；<900px 纵向堆叠）
```
┌──────────────────────────────────────────────────────────────────────┐
│ PhaseBar: [第 2 轮] [夜晚·狼人行动]  ●直播 / ▶回放   视角: 上帝 | 观众  │
├──────────────┬───────────────────────────────┬───────────────────────┤
│ SeatCircle   │ SpeechFeed（主区，自动滚动）    │ 右栏（随阶段切换）      │
│ 环形 9/12 座 │ 2号发言（自称预言家 · 警徽流 3→5）│ VotePanel / ElectionPanel│
│ 角色牌(GM)   │ [GM] 狼队决定刀 5号            │ / NightSummary(GM)     │
│ 存活/出局    │ 【天亮】昨夜出局：5号           │                       │
│ 警长徽章     │ …                              │                       │
├──────────────┴───────────────────────────────┴───────────────────────┤
│ ReplayBar: |◀ ◀ ▶ ▶| ━━━━●━━━━━━━━ seq 87/190  速度 [1×▾]  [回到直播] │
└──────────────────────────────────────────────────────────────────────┘
```
- **PhaseBar**：轮次、阶段中文名（夜晚阶段前缀「夜晚·」，白天「白天·」，竞选显示子阶段），模式徽标（直播 = 红点脉冲，回放 = 灰色播放图标），视角标签，连接状态（重连中 / 已断开）。终局显示「游戏结束：好人阵营胜」横幅。
- **SeatCircle**：座位按顺时针环形排布（0 号在顶部），每座：座位号、显示名、状态（存活实心 / 出局灰化 + ✕）、警长徽章 ★、白痴翻牌标记、当前发言者高亮描边、被投票时显示票数小标。GM 视角每座显示角色牌（狼人红 / 神职金 / 村民灰）与阵营色边；观众视角角色牌为背面。夜间：GM 视角在环内画连线（狼 → 目标红色虚线、守卫 → 目标蓝、女巫救绿 / 毒紫、预言家查验黄），文本摘要同步出现在右栏 NightSummary。
- **SpeechFeed**：按事件顺序的时间线；条目类型：发言（座位号 + 名字 + 内容；`claim_role` 徽标「自称预言家」；`badge_flow` 徽标「警徽流 3→5」）、遗言、系统行（轮次分隔、天亮死讯、放逐、猎人开枪、自爆、警长当选 / 流失、游戏结束——文案取 `render.py`）、GM 私有行（灰底 `[GM]` 前缀：刀口提议 / 决定 / 重提、守、救 / 毒、查验结果）。新条目自动滚到底；用户上滚后暂停自动滚动并显示「有 N 条新消息」按钮。回放拖动时 feed 只显示 `≤ cursor` 的条目。
- **右栏**：按阶段切换——投票 / PK：`VotePanel`（voter → target 列表、实时计票条形、PK 候选标记、结果行）；竞选：`ElectionPanel`（上警名单、退水、警下投票计票、当选 / 警徽流失原因、发言方向）；夜间（GM）：`NightSummary`（本夜各角色行动的文本列表；观众视角显示「夜晚进行中…」占位）；其它阶段：`PlayerStatusPanel`（存活数、狼 / 好人数（GM）、警长）。
- **NightOverlay**：夜间阶段整页半透明深色遮罩 + 中央「天黑请闭眼」+ 当前行动角色（如「狼人请睁眼」）；GM 视角遮罩透明度更低以便看连线；观众视角只有文字。天亮时淡出。
- **ReplayBar**：seq 滑块（刻度按轮次分段着色：夜 / 天）、播放 / 暂停、上一条 / 下一条、倍速 0.5 / 1 / 2 / 4 / 8×、`seq X/Y`、「回到直播」（仅直播模式且 cursor 非 null 时可用）。键盘：空格播放暂停，←/→ 步进。
- 空 / 错误态：对局不存在（4404）、尚未开始（4409：显示「等待开局」并每 2s 重试）、token 无效、网络断开重连中。

### 7.4 视觉语言（给设计稿的约束）
- 深色主题为主（夜晚遮罩自然融合）；阵营色：狼 `#E5484D`、好人 / 神职 `#F5B041`、村民 `#9AA4B2`；状态色：存活白、出局 40% 灰；强调色蓝 `#3B82F6`（当前发言 / 交互）。
- 中文界面；座位号统一「N号」；文案沿用后端叙述口径（不自创规则用语）。
- 组件自适应：座位环按容器最小边缩放；发言流固定高度滚动；ReplayBar 固定底部。

### 7.5 设计定稿（Claude Design 项目「AgentHowl UI Mockups」，`docs/design/m3-ui-mockups.html` + `docs/design/nocturne.css`）

实现以设计稿为准；设计稿中的可复用 HTML/内联样式可直接转成 JSX + CSS Modules。与本文 §7.2–7.4 文字稿不同处以此节为准：

- **设计系统 Nocturne**：`src/styles/tokens.css` = `docs/design/nocturne.css` 原样（Inter、`--color-*` 阶梯、`--space-*` 0.7× 密度、`--radius-*`、`--shadow-*`、`.btn/.input/.field/.seg/.card/.tag/.nav/.dialog` 类）。交互强调色用 Nocturne 紫 `--color-accent`（取代 §7.4 的蓝）；主按钮是描边不填充。分隔线用「两端 48px 渐隐」渐变（`background: linear-gradient(to right, transparent, var(--color-divider) 48px, var(--color-divider) calc(100% - 48px), transparent) no-repeat bottom/100% 1px`）。
- **语义色**（tokens.css 追加）：狼 `--ah-wolf: #E5484D`、神职 `--ah-god: #F5B041`、村民 `--ah-villager: #9AA4B2`；夜间连线：狼刀 `#E5484D` 虚线 `2 1.6`、守护 `#3B82F6`、解药 `#34C38F`、毒药 `#A855F7`、查验 `#EAB308`；成功 `#34C38F`、警告 `#F5B041`、错误 `#E5484D`；`tint(c, p=22)` = `color-mix(in srgb, c p%, transparent)`。
- **导航**：`.nav` 56px，品牌「AgentHowl」+ 链接「新的一局」「Agent 档案库」「模型服务」（当前页 `aria-current="page"`）；页面容器 `padding: 36px var(--space-8) 32px 56px`。
- **GamePage**：`grid-template-rows: 48px [终局横幅 40px] minmax(0,1fr) 52px`；三栏 `320px minmax(0,1fr) 320px`；顶栏：品牌 / `game_id` 缩略（等宽字体、neutral-600）/ 轮次 `.tag-neutral` / 阶段中文（15px 500）/ 模式（直播 = 红点 `ah-pulse` 1.6s；回放 = ▶ 灰）/ 右侧「已连接 · seq N」+ 视角 `.seg`（上帝 | 观众，只读标签）。
  - **SeatCircle**：280×280 容器，座位 `left/top = 50 + 41·cos/sin(-90° + i·360°/n)` %，0 号顶部顺时针；座位圆 44–46px，`border 1.5px` 阵营色、背景 `tint(阵营色)`，圆内角色缩写（狼 / 预 / 巫 / 猎 / 守 / 痴 / 民），观众视角为 `?` + neutral；警长 ★ 徽章（16px，`#F5B041` 底 `#161826` 字，右上 -6px）；出局：整体 `opacity .42` + 圆内 ✕ 遮罩；当前发言 `box-shadow: 0 0 0 2px var(--color-accent), 0 0 18px …55%`；投票时右下票数小标（accent 底）；座位下方「N号 名字」10.5px neutral-400。圆心文字：发言中 / 投票中 + 大号数值。图例行；底部三卡：存活 / 狼·好人（观众视角无此卡）/ 警长。夜间 GM 视角 SVG `viewBox 0 0 100 100` 画连线（`stroke-width .9`）。
  - **SpeechFeed**：`justify-content:flex-end` 底部对齐、自动滚动；三种条目：系统行（居中 11.5px neutral-500）、GM 行（`[GM]` 等宽前缀，背景 `color-mix(neutral-800 55%)`）、发言卡（`grid 58px minmax(0,1fr)`，左列「N号」阵营色 + 名字，右列 tag 行 + 13.5px 正文；当前发言者卡片背景 `accent 9%` + 内描边；tags：自称 = `tint(god,20)`/金，警徽流 = neutral-800，发言中 = accent-800/100，遗言 = neutral-800/300）；「↓ 有 N 条新消息」胶囊固定底部居中；回放游标之后显示「— 之后 N 条事件在回放游标之后 —」。
  - **NightOverlay**：GM 视角 `rgba(10,12,24,.38)` + 中央卡「天黑请闭眼」+ 当前角色（角色色）；观众视角 `.7` 遮罩、无卡片背景。
  - **右栏**：NightSummary（GM：每行 8px 色点 + 角色·座位 + 文本；底部「结算于天亮 · 当前预计出局」）/ 观众夜间「夜晚进行中…」旋转圈 + 「夜间行动仅上帝视角可见」；PlayerStatusPanel（发言顺序列表：已发言 neutral-500 / 发言中 accent-900 底 / 待发言；公开警徽流 tag 列表；GM 备注行）；VotePanel（voter → target 列表 + 权重、实时计票条形 8px、等待 X 投票…；PK 变体：两张候选卡 + 结果卡「【计票】…」「【放逐】… · 身份翻牌」）；ElectionPanel（子阶段进度点列 上警报名 / 上警发言 / 退水确认 / 警下投票 / 公布结果；上警名单 tags（退水划线）；警下投票计票；当选卡 + 发言方向 `.seg` + 顺序；警徽流失卡）。
  - **终局横幅**：40px 行，金色渐变底「═══ 游戏结束：好人阵营胜（GOOD）═══ · 回放显示到 seq N」。
  - **ReplayBar**：52px；按钮组 ⏮ ◀ ▶/❚❚ ▶▶（30px `.btn-icon`）；轨道 6px：按轮次分段底色（夜 `#2b2741` / 天 `#3f424d`）+ accent 35% 进度 + 14px 圆点（回放中加发光）；`seq X/Y` 等宽；速度按钮「1× ▾」（0.5/1/2/4/8）；「回到直播」主按钮（不可用时 `.45`）；键盘提示「空格 播放/暂停 · ←/→ 步进」。
  - **错误 / 空态**：4404「对局不存在」+ 返回 Lobby；4409「等待开局 · 每 2 秒重试 · 第 N 次」旋转圈；重连中在顶栏显示 `#F5B041` 空心点「重连中 · 4s 后重试（第 3 次）」且内容保持可读；4401/4403「token 无效」。
  - **<900px**：座位环 240px 与图例并排在顶部条，发言流在下，ReplayBar 固定底部。
- **Lobby 三步**（1180 宽）：左列 220px 步骤指示（圆点：完成 neutral-600 / 进行中 accent + 3px accent-900 光圈 / 待办 neutral-800）+ 底部「汇总」卡（`agents` 映射预览、主按钮）；右侧标题 + `grid 300px 1fr`：档案库侧栏（搜索框 + AgentCard 精简版 + 「+ 新建 Agent」）与座位表（两列，每行 `34px 1fr`：座位号 + 下拉行——Agent 白字 surface 底、随机 bot neutral-500、填满(*) neutral-400；同 memory_id 冲突行下方 `#F5B041` 提示）；工具行三按钮；图例文案。步骤 1 preset 卡片：名称 + 胜利条件 tag + 角色圆点组（角色缩写、阵营色描边）+ `config_id` 等宽；选中态 `inset 0 0 0 1px var(--color-accent)`；seed 输入「随机」。
- **AgentLibrary**：网格 3 列 `.card.elev-sm`：名字 20px、模型等宽 11.5px、副行（发言/反思模型）、`T=` 右上、技能 tag ≤3 +n、性格摘要 neutral-300、`记忆 id` accent-300、`card-meta` 更新时间 + 编辑/复制/删除 ghost 按钮；末尾虚线「+ 新建 Agent」占位卡；空态图标圈 + 文案；删除确认 `.dialog`（删除按钮红描边）。
- **AgentEditor 抽屉**：右侧 620px，`grid-rows auto 1fr auto`，头部标题 + `a_xxxx` tag + ✕；四组小标题 `10px letter-spacing .1em uppercase accent`：1·基本（名字 + ✓ 唯一；`ModelSelect`：模型服务下拉（选项含副标题、末项兼容模式 neutral-400）+ 模型下拉（等宽）；发言 / 反思模型「同模型」占位；温度滑块 4px 轨道 accent + 14px 圆点；thinking 开关 34×20）；2·技能（标题右侧「全部（*）」开关；两列复选卡：选中 accent-900 底 + accent-700 描边）；3·人格（描述 textarea + 计数；15 个特质 chips 点选（选中 accent-900/200）+ 「+ 自定义」；每个选中特质一条滑块 `44px 1fr 28px`；预设 `.seg` 无预设 | MBTI | Big Five，MBTI 四组两项 `.seg`；说话风格 + 计数；右侧 200px 只读预览卡「预览 · render_personality」）；4·记忆（`memory_id` 等宽 + ✓ 唯一 + 「按名字生成」）；底部：护栏红字提示（左）+ 取消 / 保存。
- **Providers**：两列 `.card.elev-sm`：名字 18px + 类型 `.tag-accent` + 右侧连通点（`#34C38F` 连通 · 142 ms / `#E5484D` 失败 · 401 / neutral-600 未测试）；`72px 1fr` 键值网格（地址 / 密钥「已配置 ····ab12」或「未配置」/ 默认模型，等宽）；`card-meta`：引用文案 + 测试连接 / 编辑 / 删除（被引用时 `.45`）。**ProviderEditor** 抽屉 560px：名字 + ✓ 唯一；类型 chips 六项（Ollama / OpenAI / Anthropic / OpenAI 兼容 / Gemini / DeepSeek，选中 accent 描边）；API 地址（等宽，选类型自动填）+ 说明行；API 密钥（占位「保留现有密钥（留空即不改）」+ 「清除」）；默认模型（标签右侧「↻ 拉取模型列表」；下拉面板 `background: var(--color-bg)` + `shadow-md`，首行「GET /api/tags · N 个模型 · 可手输」，每项 模型名 / 大小 / ✓）；测试连接结果条（绿 10% 底「连通 · 142 ms」或红「失败 · 318 ms」+ 等宽错误原文块）；底部「被 N 个 Agent 引用」+ 取消 / 保存；空态；删除被引用 `.dialog`「无法删除「本地 Ollama」仍被 3 个 Agent 引用：…」。
- **示例数据**（设计稿脚本）里的名字（沐阳、子墨、婉清…）、技能名与文案可直接用于 Storybook/测试假数据；技能名以 `backend/skills/` 为准。

## 8. 开发 / 部署集成

- 开发：`make serve`（uvicorn 8000）+ `make fe-dev`（Vite 5173，`/api` 代理含 WS）。
- 部署：`app/main.py` 在 `frontend/dist` 存在时 `app.mount("/", StaticFiles(directory=..., html=True))`（在 API 路由之后注册，`/api/v1` 不受影响；不存在则不挂，测试用 `tmp_path` 两种情形）；`make fe-build`；不加 CORS。
- README「前端 / Frontend」小节（安装、开发、构建、金样更新流程、链接含 token 的安全提示）；PRD §7 补两句修正（实际帧字段、`gm_token`）；根 Makefile 顶部的「前端命令待 M3 补充」注释删除。

## 9. 测试

- 后端：§2 授权矩阵与 WS 全量；§3 CLI 结构 / 前缀相等 / 排序；§8 静态挂载两种情形；litellm 惰性守卫不变。
- 前端（Vitest，`npm run test`）：金样逐事件对拍 ×4；`reduce` 未知类型抛错；`normalizeState` 幂等；store：去重 / 缺口触发补发 / 检查点回放 `viewState(cursor)` 与 `reduceAll(prefix)` 相等 / 播放到末尾自动暂停；WS hook 用手写假 `WebSocket`（唯一允许的 fake）测缓冲批量、断线重连 `from_seq`、关闭码映射；组件冒烟：`SeatCircle` GM 显示角色牌 / 观众不显示、`SpeechFeed` 渲染发言与 GM 行、`ReplayBar` 拖动改 cursor。
- 前端（Provider）：`useProviders` 对假 fetch 的 CRUD；`ProviderEditor` 密钥「留空不改 / 清除」语义；`ModelSelect` 在 provider 为空时回退为文本输入。
- 前端（档案库）：`useAgentLibrary` 对假 fetch 的 CRUD 状态机；`SeatAssignment` 把选择装成 `agents` 映射（座位专属 / `*` / 随机 bot 不写）、同 `memory_id` 二次选择被禁用；`AgentEditor` 必填与长度校验、`PersonalityEditor` 输出与 `PersonalitySpec` 形状一致（含空对象不提交）。
- 手工验收：`make serve` + `make fe-dev`，Lobby 建一局全随机 bot（零 LLM），GM 链接实时看到夜间连线与发言到终局，拖回放；观众链接同页只见公开信息。
- 手工验收（档案库）：新建两个带不同人格 / 技能 / `memory_id` 的 Agent，分配到 0 号与 3 号，其余用第三个档案填满，开局后 GM 页顶栏 / 座位显示名字；`GET /meta` 记录的档案与 UI 一致。

## 10. 明确不在范围（M4 / M5）

玩家视角与真人操作面板（`ActionBar`、`your_turn`、`/actions`）；视角切换到某座位；夜间动画特效（本期遮罩 + 连线 + 文本）；多局列表 / 历史页；token 持久化与登录；档案库 / Provider 鉴权与多用户、密钥加密存储（本期本地 0600 明文）；档案评估（#60 bench）结果在 UI 展示；移动端深度适配；i18n。
