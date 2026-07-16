# runtime 层设计 —— GameRunner 编排（issue #29，M2.2）

日期：2026-07-13
关联：issue #29（父 issue #25，PRD §4.3/§5.5/§6.3）
前置：issue #28 EventStore（PR #33，本分支叠于其上）

## 目标

实现 `backend/app/runtime/`：有 IO 的编排层。GameRunner 驱动纯引擎跑完整局，
玩家经 `PlayerPort` 接入（M2.3 真人/WS、M2.4 LLM Agent 复用同一接口），
超时代打保证对局不卡死，事件同源同序落 EventStore 并按视角广播。
补齐引擎侧预留事件 `GAME_CREATED`/`GAME_STARTED`（fail-loud 预留集合清空）。

## 决策摘要

| 决策点 | 结论 |
|---|---|
| 夜间开窗 | 串行开窗，严格跟随引擎阶段序（并行开窗留作后续延迟优化，不改引擎） |
| 大厅与预留事件 | 大厅在 runtime；引擎 `create_game` 增可选 roster 参数并发射两事件 |
| 玩家接入 | 异步 `PlayerPort` Protocol（pull 模型），runner 持有超时 |
| 超时实现 | 真 `asyncio.wait_for` + GameConfig 现有超时字段；测试用极小超时值，不 mock 时钟 |

## 模块划分（backend/app/runtime/）

### player_port.py
```python
class PlayerPort(Protocol):
    async def act(self, observation: PlayerObservation, deadline_ts: float) -> Action: ...
```
- `BotPlayerPort`：包装现有 `RandomBot.choose_action(state, seat)`。注意 RandomBot
  需要 state 而 observation 是脱敏视图 —— BotPlayerPort 由 runner 以全知身份构造
  （测试/填充 bot 属服务端内置，不越信息隔离边界；真人/Agent port 只见 observation）。
  为此 `act` 的 Bot 实现从 runner 注入的 state 提供器取当前状态。
- 端口异常（抛错/超时）一律由 runner 兜底为默认行动，对局永不因玩家挂起。

### defaults.py
- `default_action(state, seat) -> Action`：PRD §5.5 默认行动表的纯函数实现——
  发言/遗言=空发言跳过；投票=弃票；狼刀=空刀（若 config 允许）否则确定性
  选目标（走引擎 seeded RNG 口径，保持可复现）；女巫=skip；预言家=按 config
  （默认确定性选未验存活者）；守卫=空守；猎人=不开枪；竞选=不上警；
  方向/确认类=确定性默认分支。
- 纯函数、零 IO、无 asyncio，独立单测覆盖每个阶段行。

### connection.py
- `ConnectionManager`：`subscribe(viewer, callback)` / `unsubscribe` /
  `async broadcast(events)`。viewer 复用引擎 `observation.Viewer`；
  过滤复用引擎 `visible_events` / `make_visibility_filter` —— runtime 不自造
  过滤逻辑（信息隔离单一实现点）。
- M2.2 只到回调骨架（进程内订阅者，如测试收集器）；WS 端点属 M2.3。

### game_runner.py
- `GameLobby`：座位表（display_name、player_type、PlayerPort），join 规则
  （座位唯一、人满/AI 填充）、start 前置校验；start 时构造 `GameMeta` →
  `store.create_game(meta)` → 引擎 `create_game(config, game_id, roster)`。
- `GameRunner.run()` 主循环（串行窗口）：
  1. `expected_actors(state)`，空集且未终局=引擎自动推进阶段（现状引擎在 step
     内推进，空集仅出现于终局——以集成测试锁定该假设）；
  2. 对 actors 升序逐个：`build_observation(state, seat)`、按阶段取超时
     （发言/遗言用 `speech_timeout_sec`，其余用 `action_timeout_sec`）、
     `asyncio.wait_for(port.act(obs, deadline_ts), timeout)`；
  3. 超时或端口异常 → `default_action`；`step` 返回 rejection → 允许端口在
     截止前重试，截止后落默认行动（bot 永不被拒；这是 M2.3 真人重试路径）；
  4. `step(state, action)` 产出的每个事件：runtime 元数据充实（见下）→
     `store.append` → `connection.broadcast`，同序不可乱。
- 终局后 runner 返回终态；对局全程任何存储/广播异常 fail-loud 上抛。

## meta 充实（runtime 的合法写点）

引擎 `Event.ts` 为逻辑 tick，墙钟归 runtime（`events.py` 字段注释已约定）。
runner 在落库/广播前 `model_copy(update={"meta": ...})` 注入：
- `wall_ts`：ISO8601 墙钟；
- `timeout: "true"`：仅默认行动产生的事件。
payload/seq/type/visibility 不动 —— reduce 语义与引擎字节级确定性测试不受影响。
store 契约与 meta 无关，回放照常。

## 引擎侧改动（小而加法）

- `RosterEntry`（engine 内定义，勿依赖 store）：`seat/display_name/player_type`；
  `create_game(config, game_id, roster: Sequence[RosterEntry] | None = None)`，
  缺省行为与今日一致（`P{seat}`、AGENT）。roster 与 config.num_players 不符 → 拒绝。
- 发射序列头部追加：`GAME_CREATED`（payload：num_players 等最小事实）→
  `GAME_STARTED`（payload：空标记类）→ 既有 `ROLES_ASSIGNED` → …；均 PUBLIC。
- `EVENT_PAYLOAD_TYPES` 补两项，reduce 显式分支（no-op 返回 `{}`，非静默缺失）；
  `test_fail_loud.py` 预留集合清空。
- 既有测试的事件序列断言随 seq 偏移 +2 同步更新（一次原子迁移）。

## 分层约束

- runtime 可 import engine 与 store；engine/store 禁止 import runtime。
- runner 只转发 intent，裁决全在引擎；广播必须经引擎可见性过滤，前端零过滤。
- 新增 dev 依赖：`pytest-asyncio`（仅测试）。生产代码依赖仍为 stdlib+pydantic。

## 测试策略

1. **defaults 单测**：§5.5 表逐行（各阶段、各 config 变体的默认行动合法且被 step 接受）。
2. **ConnectionManager 单测**：各 Visibility × viewer 组合的过滤与广播顺序（复用
   test_isolation 口径）。
3. **Lobby 单测**：重复座位、满员、start 前置、roster 与 GameMeta 一致。
4. **集成（pytest-asyncio）**：12 bot 全自动经 GameRunner + InMemoryEventStore
   跑至 GAME_OVER；store 回放 == 实时终态；事件含 GAME_CREATED/GAME_STARTED 头。
5. **超时**：挂起 port（永不返回）+ 0.05s 超时 → 默认行动顶替、事件带
   `meta.timeout="true"`、对局照常终局。
6. **拒绝重试**：先提交非法 intent 的 port → 重试成功；截止后仍非法 → 默认行动。
7. **JSONL 变体**：同一集成局落 JsonFileEventStore，冷装载回放一致。
8. 质量门：`uv run pytest`、`uv run mypy app`（strict）、`uv run ruff check .`。

## 明确不做（YAGNI）

- 并行开窗与提前提交缓冲（后续延迟优化）；WS 端点与认证（M2.3）；
  LLM Agent（M2.4）；AFK 接管；断线重连补发（M2.3，store 已备 from_seq）；
  Redis/多进程广播；PLAYER_JOINED 事件化（大厅事实暂不入流，M2.3+ 再议）。
