# 竞选子阶段游标事件化：ELECTION_STAGE_CHANGED — 设计文档

> 日期：2026-07-08 · 状态：已批准 · 关联：GitHub issue #17 · 来源：PR #16 终审建议

## 1. 缺陷与目标

`election_stage`（`""/"candidacy"/"withdraw"/"vote"/"direction"/"announce"`）是流程游标，只经 `model_copy` 写入、从不进入事件日志；且退水期再确认 `SHERIFF_CANDIDACY(running=True)` 与初次上警在日志中字节同形。引擎侧 `reduce` 重建状态无歧义，但纯 `reduce(events)` 的前端/回放无法重建**子阶段时间线**。目标：子阶段边界成为事件流的一部分，`election_stage` 从「游标例外」升格为事件推导事实。

## 2. 机制：游标事件化（用户选定，优于纯标记/专用再确认事件）

- **`ElectionStage(StrEnum)`** 定义在 `phases.py`（与 `Phase` 同居）：`NONE=""`、`CANDIDACY="candidacy"`、`WITHDRAW="withdraw"`、`VOTE="vote"`、`DIRECTION="direction"`、`ANNOUNCE="announce"`。`NONE` 是竞选机器结束/未启动的显式值——收尾也发标记，时间线有明确闭合。
- **新事件 `EventType.ELECTION_STAGE_CHANGED`（PUBLIC）**，`ElectionStageChangedPayload(stage: ElectionStage)`——枚举直接作 payload 字段类型（Pydantic 校验成员、StrEnum 序列化为 str，与 `RolesAssignedPayload` 的 `RoleType` 同风格）；入 `EVENT_PAYLOAD_TYPES`。
- **reduce 据此写字段**：`ELECTION_STAGE_CHANGED` 的 reduce 返回 `{"election_stage": p.stage}`（存 str 值，state 字段类型不变）。
- **发射方**：`engine.py` 全部 10 处对 `election_stage` 的 `model_copy` 写入改为 `_emit(ELECTION_STAGE_CHANGED, …, PUBLIC)`（含清空为 `""` 的收尾处：`_finish_election`、`_lose_badge`、announce 消费、自爆路径）。同一 `model_copy` 里的**其他**游标字段（`sheriff_confirmed` 重置、`sheriff_votes` 清空、`night_deaths`、`skip_day`）保持 model_copy 不变——本 issue 只事件化 `election_stage`。发射位置与原 model_copy 位置一致，保证任何后续读该字段的逻辑（`expected_actors`、`_advance_election` 分支）见到相同的值序列。
- **文档同步**：`state.py` 中 `election_stage` 的注释更新为「事实：经 `ELECTION_STAGE_CHANGED` 事件写入」；PRD `docs/specs/requirements.md` §6.4 事件表补 `ELECTION_STAGE_CHANGED(PUBLIC)` 一行。

## 3. 再确认歧义（顺带消除）

退水期的 `SHERIFF_CANDIDACY(running=True)` 再确认在日志中必然位于 `ELECTION_STAGE_CHANGED(WITHDRAW)` 标记之后、下一个子阶段标记之前——时间线消费者按前置标记区分语义，无需 `SHERIFF_REAFFIRMED` 专用事件。

## 4. 行为影响

事件流插入新事件 → `state_version` 序列位移 → 同 seed 抽取结果相对旧代码改变（确定性测试比较同代码两次运行，不受影响）；500 局扫描重验终止性。对外可见性：子阶段切换本就有公开语义（谁该行动），PUBLIC 无信息泄露。

## 5. 测试

新增 `backend/tests/test_election_timeline.py`：

- **逐步重放等价**：手动驱动一局（含竞选），每步后断言 `reduce_all(blank, events_so_far).election_stage == live.election_stage`——中局强等价，不只终局；
- **时间线重建**：完整对局事件流中标记序列符合 `candidacy → withdraw → vote → [direction] → announce → ""`（有人当选路径），另覆盖流失路径（`SHERIFF_BADGE_LOST` 前后标记正确闭合到 `""`）；
- **再确认消歧**：退水期 re-affirm 的 `SHERIFF_CANDIDACY` 事件之前存在 `ELECTION_STAGE_CHANGED(WITHDRAW)`；
- **reduce 单元**：`ELECTION_STAGE_CHANGED` 写 `election_stage`。

既有迁移：`test_determinism.py::test_reduce_events_equals_live_state` 增加 `replayed.election_stage == final.election_stage` 断言；受事件插入影响的既有断言（如对某次 `advance` 返回事件列表的精确长度/顺序断言）执行时按新日志更新。全量套件、mypy strict + ruff 全绿。

## 6. 不在范围

- 其余游标字段（`resume_token`、`skip_day`、`sheriff_confirmed`、`sheriff_votes`、`night_deaths`、`pending_hunter`）的事件化——仍是文档化例外；
- `DAY_SKIPPED` 标记事件（如需另开 issue）；
- M3 前端 TS reducer 本体。
