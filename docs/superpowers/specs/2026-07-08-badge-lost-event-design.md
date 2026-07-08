# 全员上警裁决 + SHERIFF_BADGE_LOST 事件 — 设计文档

> 日期：2026-07-08 · 状态：已批准 · 关联：GitHub issue #9 · 上游：`docs/specs/requirements.md` §3 line 86（警长竞选）、§6.4（预留事件 `SHERIFF_BADGE_LOST(PUBLIC)`）

## 1. 目标

1. **裁决全员上警边角**：退水确认后若无合法警下投票人（全体存活者皆为候选人），警徽立即流失且**不进入空投票阶段**——消除「零投票人静默跳 PK」的语义歧义。
2. **实现最后一个引擎侧预留事件 `SHERIFF_BADGE_LOST(reason)`**，替换所有 `SHERIFF_ELECTED(seat=None)` 的「流失」用法——事件日志从此可区分流失原因；`SHERIFF_ELECTED` 收紧为恒携带真实座位。

**交付判据**：
- 全员上警（退水后候选=全体存活）→ `SHERIFF_BADGE_LOST(NO_VOTERS)`，`election_stage` 全程不进入 `"vote"`；
- 五条流失路径各发对应 reason；`SHERIFF_ELECTED.seat` 收紧为 `int`，完整对局事件流中不再出现 None；
- fail-loud 映射的预留集合缩至 `{GAME_CREATED, GAME_STARTED}`（仅 M2 runtime）；
- 全部既有测试（更新断言后）、确定性、500 局扫描保持通过。

## 2. 裁决（engine.py `_advance_election` withdraw→vote 转移处）

进入 `"vote"` 前计算合法警下：`存活 ∧ can_vote ∧ ∉ sheriff_candidates ∧ ∉ sheriff_withdrawn`。为空 → `_lose_badge(state, BadgeLostReason.NO_VOTERS, events)`，不进入投票阶段。

## 3. 事件契约

- `BadgeLostReason(StrEnum)`：`NO_CANDIDATES`（无人上警）/ `ALL_WITHDREW`（全员退水）/ `NO_VOTERS`（无警下投票人，新裁决）/ `TIE_AGAIN`（PK 再平票）/ `SELF_DESTRUCT`（竞选期自爆吞警徽）。定义在 `events.py`（payload 旁）。
- `SheriffBadgeLostPayload(reason: str)`（存 `.value`，与 `sheriff_speech_direction` 同风格）；`EventType.SHERIFF_BADGE_LOST`（已在枚举）入 `EVENT_PAYLOAD_TYPES`。
- **reduce**（继承 issue #19 的全化语义）：剥离在任者 `is_sheriff`（若有）+ `sheriff_seat=None`。
- **`SHERIFF_ELECTED` 收紧**：`SheriffElectedPayload.seat: int`（不再 Optional）；其 reduce 保留 strip-then-grant 不变量防御。趁 M2 前端未建，契约变更成本最低。
- `test_fail_loud.py` 预留集合更新为 `{GAME_CREATED, GAME_STARTED}`（tripwire 按设计触发）。

## 4. 发射方重构（engine.py）

- 新 helper `_lose_badge(state, reason, events)`：发 `SHERIFF_BADGE_LOST(reason)`、清 `election_stage`、走与原 `_finish_election(None)` 相同的续接（`_announce_and_continue_night`）。
- `_finish_election(state, elected: int, events)` 只保留真实当选路径（`SHERIFF_ELECTED(seat)` + 方向子阶段/announce）。
- 五个流失点改接 `_lose_badge`：candidacy 空 → `NO_CANDIDATES`；withdraw 后候选空 → `ALL_WITHDREW`；withdraw 后警下空 → `NO_VOTERS`（新增）；PK 再平票 → `TIE_AGAIN`；自爆吞警徽（`_apply_self_destruct`，原地替换其 `SHERIFF_ELECTED(None)` 发射，保留其自身流程）→ `SELF_DESTRUCT`。

## 5. 测试

- 既有断言迁移：`test_withdraw.py::test_all_withdraw_badge_lost`、`test_self_destruct_skip.py` 的 #19 端到端/单元（改断 `SHERIFF_BADGE_LOST` + strip 语义移植）、其余任何 `SheriffElectedPayload(seat=None)`/`payload.seat is None` 断言（执行时 grep 定位）。
- 新增 `backend/tests/test_badge_lost.py`：
  - 全员上警零警下 → `SHERIFF_BADGE_LOST(NO_VOTERS)`、`election_stage` 从未进入 `"vote"`、流程续接死讯公布；
  - 各 reason 路径一例（NO_CANDIDATES / ALL_WITHDREW / TIE_AGAIN / SELF_DESTRUCT）；
  - reduce 单元：`SHERIFF_BADGE_LOST` 剥离在任者（移植 #19 单元）；
  - 收紧回归：完整对局（多 seed）事件流中所有 `SHERIFF_ELECTED` 均携带 `int` 座位。
- 全量套件、确定性、500 局扫描、mypy strict + ruff 全绿。

## 6. 明确不在范围

- `GAME_CREATED`/`GAME_STARTED`（M2 runtime）。
- 全员互投村规变体（如需另配 GameConfig 开关，另开 issue）。
- 子阶段时间线标记（issue #17）。
