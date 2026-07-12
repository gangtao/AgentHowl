# EventStore 设计 —— append-only 事件持久化（issue #28，M2.1）

日期：2026-07-12
关联：issue #28（父 issue #25，PRD §6.2/§6.4）

## 目标

实现 `backend/app/store/event_store.py`：对局事件的 append-only 持久化层。
装载 = `reduce(load_events)`。MVP 提供内存与 JSON 文件两种实现，为 M2.2
runtime（事件落盘 + 广播同源）、M2.3 REST `GET /events?from_seq=` 与断线重连
补发打底。

## 决策摘要

| 决策点 | 结论 |
|---|---|
| 冷装载的初始状态来源 | JSONL 首行 `GameMeta` 头记录（自包含单文件） |
| 接口同步性 | 同步接口；异步化留给未来 Postgres/包装层 |
| 损坏处理 | 仅容忍"残尾行"（崩溃中断的 append），其余一律 fail-loud |
| 双实现组织 | `EventStore` Protocol + 两个对等实现，共享校验核心 |

## 接口

新模块 `backend/app/store/event_store.py`（含 `store/__init__.py`）。
`EventStore` 为 `typing.Protocol`（与 PRD §4.4.3 `LLMClient` 同一模式），全同步：

```python
class EventStore(Protocol):
    def create_game(self, meta: GameMeta) -> None: ...   # 已存在 → GameExistsError
    def append(self, game_id: str, event: Event) -> None: ...
    def load_meta(self, game_id: str) -> GameMeta: ...
    def load_events(self, game_id: str, from_seq: int = 0) -> list[Event]: ...
    def list_games(self) -> list[str]: ...
```

- `from_seq` 为**闭区间下界**：返回 `seq >= from_seq` 的事件，默认 0 即全量。
  该语义直接成为 M2.3 REST `?from_seq=` 与重连补发的口径。
- 实现：`InMemoryEventStore`（测试/单进程 MVP）与 `JsonFileEventStore(data_dir)`
  （进程重启可恢复）。两者共享同一校验核心函数，防止不变量口径漂移。
- 生产 Postgres 实现（PRD §6.1）未来作为第三个实现接入，本期不做。

## 冷启动引导：GameMeta 头记录

`reduce(load_events)` 需要一个空白初始 `GameState`（game_id、GameConfig、座位
名册）。今日 CLI 回放（`simulate._blank`）从内存中的终局状态反推，冷装载做不到。

- 新增 frozen Pydantic 模型：
  `GameMeta { game_id: str, config: GameConfig, roster: tuple[SeatName, ...] }`，
  其中 `SeatName { seat: int, display_name: str }`。
- 模块级 `initial_state(meta) -> GameState`：构造发牌前空白状态
  （玩家占位 `VILLAGER/GOOD`、`phase=LOBBY`、`round=0`，形状与
  `simulate._blank` 一致；真实角色由事件流中的 `ROLES_ASSIGNED` 写入）。
- 模块级便利函数（非 Protocol 方法，只写一份）：
  `load_state(store, game_id) -> GameState`
  = `reduce_all(initial_state(load_meta(...)), load_events(...))`。
- `simulate.py` 本期不动（后续可选改为经 store 回放）。

## 文件格式（JsonFileEventStore）

- 一局一文件：`<data_dir>/<game_id>.jsonl`，逐行追加。
- 每行一个信封：`{"kind": "meta" | "event", "data": {...}}`；
  第 0 行必须是唯一一条 `meta` 记录，事件从第 1 行起。
  显式 `kind` 判别符为未来记录类型（如快照）留扩展位，不破坏格式。
- 事件编解码放在 store 侧（引擎不增加任何序列化代码）：
  编码 `event.model_dump(mode="json")`；解码经
  `EVENT_PAYLOAD_TYPES[EventType(d["type"])]` 还原具体 payload 类后重建 `Event`。
- `game_id` 触盘前校验 `^[A-Za-z0-9_-]+$`（路径穿越防护），不合法 → `StoreError`。
- append 采用"打开-写入-flush-关闭"每事件一次（一局 < 2000 事件，性能足够）；
  句柄缓存留作未来优化点，本期不做。不做 fsync（MVP 单机可接受，注释注明）。

## 不变量与错误（fail-loud，仅一处豁免）

- `append` 前置校验：`event.game_id == game_id`；`event.seq == last_seq + 1`
  （引擎 `_emit` 保证 `seq = state_version + 1`，空白态 `state_version=0`，
  故首事件 `seq=1`，序列稠密无洞）。
- 错误类型：`StoreError(Exception)` 基类，子类
  `GameExistsError` / `GameNotFoundError` / `SeqConflictError` / `StoreCorruptionError`。
- **唯一豁免——残尾行**：进程在 append 中途崩溃可能留下不完整的最后一行。
  首次打开某局文件时执行"开箱修复"：截断到最后一条完整行，随后正常追加
  （标准 WAL 实践）。
- 其余一律 fail-loud 抛 `StoreCorruptionError`：中间任何一行不可解析、
  `meta` 记录缺失/重复/不在首行、装载出的事件流存在 seq 洞或重复。

## 分层约束

- store 只 import engine（`Event`、`EVENT_PAYLOAD_TYPES`、`reduce_all`、
  `GameState`、`GameConfig` 等）；engine 保持零 IO，禁止反向依赖。
- store 不含任何裁决/业务逻辑，只做持久化与不变量守卫。

## 测试策略

1. **契约测试**（参数化跑两个实现）：create→append→load 往返一致；
   seq 洞/重复 append 被拒；跨 game_id append 被拒；`from_seq` 过滤口径；
   `list_games`；未知 game_id → `GameNotFoundError`；重复 create → `GameExistsError`。
2. **集成回放**：用现有 `run_game` 跑完整 bot 对局，meta+事件全部入 store，
   `load_state` 与实时终局状态相等（比较口径与 `test_determinism` 一致，
   排除 cursor 字段）。
3. **文件实现专项**：同一 `data_dir` 新建实例重新装载（模拟进程重启）；
   手工构造残尾行 → 开箱修复后可继续 append；构造中间坏行/双 meta/seq 洞
   → `StoreCorruptionError`。
4. 质量门：`uv run pytest`、`uv run mypy app`（strict）、`uv run ruff check .`。

## 明确不做（YAGNI）

- 异步接口、fsync、句柄缓存、快照记录、Postgres 实现、Redis、
  按 visibility 过滤（属 runtime/api 层职责）、`simulate.py` 改造。
