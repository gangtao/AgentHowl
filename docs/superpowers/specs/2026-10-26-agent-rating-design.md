# Agent 积分与战绩 设计（issue #123）

状态：已评审通过（2026-10-26）。实现计划见 `docs/superpowers/plans/`。

## 1. 目标与范围

每局 `GAME_OVER` 后，按胜负给参局的**库内 Agent 档案**累计战绩与积分，在 Agent 库里展示并可按积分排序，让「这个 Agent 打得怎么样」在产品里可比较。`app/eval` + `app.cli.bench`（issue #60）继续作为离线深度分析工具，本期是产品内的轻量累计。

本期做：

- 归因：对局记下每个 Agent 座位对应库里的哪条档案（`agent_ids`）。
- 计分：Elo 风格阵营评分 + 胜/负/平战绩（按阵营分项），纯函数。
- 推导：积分完全由已结束对局的事件日志推导，不落盘，进程内缓存。
- API：`/agents` 带积分摘要；`/agents/{id}/rating` 返回完整对象。
- 前端：Agent 卡片显示积分 / 场次 / 胜率；Agent 库可按积分排序；Lobby 补发 `agent_ids`。
- CLI：`python -m app.cli.rating` 打印积分表用于核对。

本期不做（已定后续）：历史页每局座位显示 Δ；详情页积分曲线；角色修正（如狼胜且本狼存活加分）；#122 共享档案的积分展示；#115 组队对战的用户队伍 Elo。

成功判据（验收）：

- 跑一局随机 bot + 2 条库内档案的对局到终局，两条档案 `games=1`，胜方 `wins=1`、`rating>1000`，败方相反；平局两边 `draws=1`，两队同分时积分不变。
- 同一对局无论读多少次、进程重启多少次，结果一致；`app.cli.rating` 打印结果与 API 一致。
- `GameMeta.agent_ids` 不经 `visible_events` 暴露给任何视角，`GET /games/{id}/meta` 也不回传；引擎目录零 diff；`test_importing_registry_does_not_load_litellm` 仍通过。
- 普通用户只能看到自己档案的积分；admin 可看全部。

## 2. 现状与约束

- 建局时 Lobby 把库里选中的档案**内联**成 `agents: {"0": AgentProfile, "*": AgentProfile}` 发给 `POST /games`；`agent_id` 没有传到后端，`GameMeta.agents` 只存 profile（issue #64）。回放时无法把座位对应回库里的某条档案，人格 / 模型改过之后指纹也变了。
- 终局后已有一个运行时钩子 `GameRegistry._schedule_postgame`（跨局记忆复盘，issue #59），只对有 `memory_id` 的座位触发。本设计**不**依赖终局钩子（见 §3.3）。
- `GameOverPayload.winner ∈ {"GOOD", "WOLF", None}`，`None` 为平局。座位阵营由 `ROLES_ASSIGNED`（GM_ONLY）事件得到，运行时侧对事件日志 reduce 出 final state 即可，不经 observation。
- 档案库是单目录 `data/agents/<agent_id>.json`，`owner_id` 是档案字段，`agent_id` 全局唯一；`/agents` 的可见性规则：admin 全部，普通用户仅自己的（`can_access`）。
- `GET /games/{id}/meta` 现在是 `meta.model_dump()` 直出，分享链接（匿名）可读。
- 硬约束（CLAUDE.md）：引擎零 IO、零改动；信息隔离在服务端；`app/runtime` `app/api` `app/cli` 不在模块级 import litellm；`state = reduce(events)`——积分同样是事件日志的派生物，不另立事实源。

## 3. 后端

### 3.1 归因：建局请求与 GameMeta

- `CreateGameRequest` 新增 `agent_ids: dict[str, str] = {}`。键与 `agents` 同形（座位号字符串或 `"*"`），值为 `StoredAgent.agent_id`。
- 校验（`create_game` 端点，失败 400，错误信息列出首个非法键）：
  - 每个键必须同时出现在 `agents` 里（有 id 必有档案）；反之不要求（内联档案可以没有 id）。
  - 每个 id 必须是当前用户可见的档案（`can_access(user, stored.owner_id)`；admin 可见全部）；不存在与无权一律报「档案不存在」。
  - 不校验内联 profile 内容与库里是否一致：归因记录的是「选了谁」。
- `GameHandle` 新增 `agent_ids: dict[str, str]`（原样保存请求值）。
- `registry.start` 展开 `effective` 档案时同步展开 id：对每个实际建成 Agent 端口的座位 `seat`，`effective_ids[str(seat)] = agent_ids.get(str(seat)) or agent_ids.get("*")`，取不到则不记。真人占座、随机 bot、内联无 id 的座位不记。
- `GameMeta` 新增 `agent_ids: dict[str, str] = {}`（键为座位号字符串，已展开；旧文件缺省 `{}` → 不计分）。`GameRunner` 把它随 `agents` 一起写进 JSONL 首行。
- 不变量：`agent_ids` 只在 meta 里，不进任何 Event，因此 `visible_events` 天然不含它；`meta_endpoint` 返回前剔除 `agent_ids`（分享链接匿名可见，不泄露档案 id；`agents` 的处理不变）。

### 3.2 计分纯函数 `app/runtime/rating.py`

零 IO、零 litellm、不依赖 FastAPI；只 import pydantic 与 `app.engine.config.Faction`。

输入：

```python
class FinishedGame(BaseModel):
    game_id: str
    ended_at: str                 # GAME_OVER 事件的 meta.wall_ts（ISO 8601）
    winner: str | None            # "GOOD" | "WOLF" | None(平局)
    seat_factions: dict[int, Faction]
    agent_ids: dict[int, str]     # 已展开：座位 → agent_id（只含库内档案座位）
```

输出：

```python
class CampRecord(BaseModel):
    games: int = 0; wins: int = 0; losses: int = 0; draws: int = 0

class RatingEntry(BaseModel):
    game_id: str; ended_at: str; camp: Faction
    result: Literal["WIN", "LOSS", "DRAW"]; delta: float

class AgentRating(BaseModel):
    rating: float = 1000.0
    games: int = 0; wins: int = 0; losses: int = 0; draws: int = 0
    by_camp: dict[Faction, CampRecord]     # 两个阵营都有键，缺省全 0
    history: list[RatingEntry] = []        # 时间顺序，全量

INITIAL_RATING = 1000.0
K_FACTOR = 32.0
HISTORY_LIMIT = 200                        # API 输出截取最近 N 条；内存里全量

def compute_ratings(games: Iterable[FinishedGame]) -> dict[str, AgentRating]: ...
def settle_game(ratings: dict[str, AgentRating], game: FinishedGame) -> dict[str, AgentRating]: ...
```

规则：

- `compute_ratings` 先按 `(ended_at, game_id)` 升序排序再逐局 `settle_game` fold；输入顺序不影响结果。没有 `agent_ids` 的对局直接跳过。
- 队伍均分按**座位**计算：狼队 `Rw = mean(rating(seat) for seat in wolves)`，好人 `Rg` 同理；有 id 的座位取该档案当前积分，没有 id 的座位按 `INITIAL_RATING` 代入（真人 / 随机 bot / 内联档案参与均值但不落账）。
- 期望胜率 `E_w = 1 / (1 + 10 ** ((Rg - Rw) / 400))`；狼胜 `S_w = 1`，狼负 `0`，平局 `0.5`；`Δw = K * (S_w - E_w)`，`Δg = -Δw`。同一阵营内每条档案拿同样的 Δ。
- 记账粒度是「档案 × 阵营 × 对局」：同一档案在一局里占多个**同阵营**座位只记一条（`games` 不虚涨，Δ 只加一次）；若两个阵营都有它，记两条（一胜一负，Δ 相抵）。注意均分仍按座位算，所以占 3 个狼座的档案在 `Rw` 里权重是 3。
- 结果：`WIN` 时 `wins+1`，`LOSS` 时 `losses+1`，`DRAW` 时 `draws+1`，`games+1`；`rating += Δ`（平局 Δ 不一定为 0——Elo 平局对强队是负增量，这是刻意的，与「积分不变」的验收描述以「两队初始同分」为前提）。`by_camp[camp]` 同步累加；`history` 追加一条 `RatingEntry`。
- 数值：`rating`、`delta` 保留 float，不四舍五入；展示层取整。
- 幂等由调用方保证（同一 `game_id` 只喂一次）；`settle_game` 本身是纯函数，返回新 dict 不改入参。

### 3.3 推导与缓存 `app/runtime/rating_index.py`

IO 层，持有 `EventStore`；不需要终局钩子，也不需要失效逻辑。

```python
class RatingIndex:
    def __init__(self, store: EventStore) -> None: ...
    def snapshot(self) -> dict[str, AgentRating]: ...
    def extract_finished(self, game_id: str) -> FinishedGame | None: ...   # 可单测
```

- `snapshot()`：遍历 `store.list_games()`，对每个 `game_id` 取 `FinishedGame`：
  - 已缓存 → 直接用（已结束对局不可变，只读一次）。
  - 未缓存 → `load_meta` + `load_events`；`meta.agent_ids` 为空、或末事件不是 `GAME_OVER` → 返回 `None` 且**不缓存**（未结束的对局下次再查；无 `agent_ids` 的对局永远跳过，但也不缓存，代价是每次多读一次——数量少，可接受；若将来成为瓶颈，再缓存「已结束但无 id」的否定结果）。
  - 已结束且有 id → 与 `app/eval/metrics.py` 同一条路径用 `app.engine.events.reduce_all` 对事件 reduce 出 final state 取 `seat_factions`（`player.faction`），`winner` 取 `GAME_OVER` payload，`ended_at` 取该事件 `meta["wall_ts"]`（缺失时退回 `ts`），`agent_ids` 键转 int；写入缓存。
  - 坏文件（`StoreError` / `ValidationError`）跳过并 `logger.warning`，与 `list_history` 一致。
  - 聚合：`compute_ratings(cached + fresh)`，每次重算（纯函数、线性）。
- 并发：`snapshot()` 是同步函数，由 Starlette 线程池执行（agents 端点为同步 def），可能与事件循环及自身并发；缓存值不可变、重复计算结果相同，并发只多做一次计算，不影响正确性。
- 装配：`app.main` 建 `RatingIndex(store)` 挂 `app.state.rating_index`，`api/deps.py` 提供 `get_rating_index`。测试用 `InMemoryEventStore` 即可。

### 3.4 API

- `GET /agents`、`GET /agents/{id}`：响应模型由 `StoredAgent` 改为 `StoredAgentWithRating = StoredAgent + rating: RatingSummary`，其中 `RatingSummary{rating: float, games, wins, losses, draws}`；档案没打过为 `1000.0 / 0 / 0 / 0 / 0`。实现：`list_agents` 调一次 `snapshot()`，逐条合并。`POST` / `PUT` 的响应保持 `StoredAgent`（不带积分，前端创建/更新后重新拉列表）。
- `GET /agents/{id}/rating` → `AgentRating`，`history` 截取最近 `HISTORY_LIMIT` 条。可见性沿用 `_get_owned_agent`：不存在或无权一律 404。
- `GET /games/{id}/meta`：返回 `meta.model_dump()` 去掉 `agent_ids`。
- `POST /games` 的 400 文案：`agent_ids 非法：座位 X 没有对应的 agents 档案` / `agent_ids 非法：档案不存在：<id>`。

### 3.5 CLI `app/cli/rating.py`

`python -m app.cli.rating [--data-dir backend/data]`：用 `JsonFileEventStore` + `JsonFileAgentLibrary` 建 `RatingIndex`，打印一张表（档案名、agent_id 前 8 位、积分（取整）、场次、胜/负/平、狼：场次/胜、好人：场次/胜），按积分降序。只读、不落盘；模块级不 import litellm。库里已删除但历史对局仍有 id 的档案照样打印（名字显示 `(已删除)`）。

## 4. 前端

### 4.1 类型与 API

- `api/agents.ts`：`StoredAgent` 增加 `rating: RatingSummary`，新增 `RatingSummary` 类型。本期页面不调用 `/agents/{id}/rating`，不加对应客户端函数（曲线做时再加）。
- `api/rest.ts`：`CreateGameRequest` 增加 `agent_ids?: Record<string, string>`。

### 4.2 AgentCard

- 紧凑与完整两种卡片底部各加一行战绩：`1024 分 · 12 局 · 胜率 58%`；`games === 0` 时显示 `尚无战绩`。积分取整显示，胜率 `Math.round(wins / games * 100)`。
- 零裁决：只渲染服务端给的数字，不在前端算 Elo。

### 4.3 Agent 库排序

- 页头加排序切换（两个按钮或一个 select）：「最近更新」（默认，现状）/「积分」。积分排序：`rating` 降序，同分按 `games` 降序，再按名字。
- 排序状态只在页面内存里，不持久化。

### 4.4 Lobby 补发 agent_ids

- Lobby 已按座位记录「选了哪条档案」（`items.find(a => a.agent_id === …)`）：组请求体时，凡座位档案来自库里的，写 `agent_ids[seat] = agent_id`；「空位统一用某档案」写 `agent_ids["*"]`；内联新建 / 编辑后未保存回库的档案不写。
- 请求回显区（显示 `agents: {...}` 键）同样列出 `agent_ids` 键，便于核对。

## 5. 错误处理与边界

- 建局 `agent_ids` 校验失败 → 400，不建局。
- 终局前（含 `aborted` 对局：有事件但末事件非 `GAME_OVER`）不计分，也不缓存。
- 档案被删除：积分仍由历史对局推导得出（`snapshot()` 里仍有该 id），但 `/agents` 列表不再有它，自然不展示；CLI 打印为 `(已删除)`。不需要删除联动。
- 同一档案被两个用户的对局使用（admin 用了别人的档案）：计分按 `agent_id` 累计，不分对局归属；可见性只看档案归属。
- `ended_at` 缺失（极旧文件无 `wall_ts`）：退回事件 `ts`；两者都缺的文件按 `game_id` 排序垫底。
- 坏 JSONL / 坏 meta：跳过 + warning，不影响其它对局与 `/agents` 可用性。

## 6. 测试

- `tests/test_rating.py`（纯函数）：狼胜 / 好人胜 / 平局三种 Δ 的数值（含手算期望值）；同队同增量、`Δg = -Δw`；无 id 座位按 1000 代入；同档案同阵营多座位只记一条；跨阵营记两条且 Δ 相抵；输入乱序结果与有序一致；`settle_game` 不改入参；`history` 时间顺序。
- `tests/test_rating_index.py`：`InMemoryEventStore` 跑两局随机 bot 局（一局 meta 带 `agent_ids`、一局不带）+ 一局手工截断成未结束；断言只有带 id 的计分、未结束不计、重复 `snapshot()` 结果相同且已结束对局的 `load_events` 只调一次（包装 store 计数）；坏文件跳过。
- `tests/test_api_agents.py` 增补：建局带 `agent_ids` → start（随机 bot，速度快）→ 等终局 → `/agents` 两条档案 `games=1`，胜负与 `winner` 一致；`/agents/{id}/rating` 的 `history` 一条；无权用户 404；`agent_ids` 键不在 `agents` 里 → 400；id 不可见 → 400；`/meta` 响应无 `agent_ids`。
- `tests/test_api_host_plays.py` / `test_api_ws.py` 增补一条：任何视角的 `game_event` 与 `/events` `/replay` 里不出现 `agent_ids` 字段。
- 守卫：引擎零 diff（`git diff --stat main -- backend/app/engine frontend/src/engine/__fixtures__` 为空）；`test_importing_registry_does_not_load_litellm`；`app.cli.rating` 模块级不加载 litellm（加进同一守卫测试的参数化）。
- 前端：`AgentCard.test.tsx` 战绩行两种状态；`AgentLibrary.test.tsx` 排序切换；`Lobby.test.tsx` 请求体含 `agent_ids`（座位与 `"*"` 两种）。

## 7. 与后续工作的衔接

- 历史页每局座位 Δ：`RatingIndex` 的 `history` 已按 `game_id` 可查，补一个 `GET /games/{id}/rating-deltas` 即可。
- 详情页曲线：`GET /agents/{id}/rating` 的 `history` 已够画。
- 对局数上千后：给「已结束但无 `agent_ids`」的对局也缓存否定结果，或把每局的 `FinishedGame` 摘要落到 `data/rating_cache/`——接口不变。
- #122 共享档案：复制出的副本是新 `agent_id`，积分从 1000 / 0 开始，无需特殊处理。
