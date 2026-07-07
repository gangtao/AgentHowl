# 退水（竞选中途退出并失去警长投票权）— 设计文档

> 日期：2026-07-07 · 状态：已批准 · 关联：GitHub issue #6 · 上游：`docs/specs/requirements.md` §2（退水=放弃竞选，失去警长投票权）、§3 line 86（上警→发言→可退水→警下投票）、§6.4（预留事件 `SHERIFF_WITHDREW(PUBLIC)`）

## 1. 目标

建模真正的「退水」：已上警的候选人在投票前退出竞选，并失去**本场警长选举**（含 PK 重投）的投票权；白天放逐投票权不受影响。现状：candidacy 阶段的 `WITHDRAW` 只是「不上警」（保留一切投票权），无中途退水。

**交付判据**：
- 候选人在专用确认子阶段可退水或坚持；退水者退出候选集、整场竞选（含 SHERIFF_PK 重投）不能投票、白天投票不受影响；
- 全员退水 → 警徽流失（与今日「无人上警」同路径）；余 ≥1 人 → 警下投票照常；
- 实现预留事件 `SHERIFF_WITHDREW`（issue #4 的映射完整性 tripwire 按设计触发并更新）；
- 全部既有测试、确定性、500 局扫描保持通过。

## 2. 流程：candidacy 与 vote 之间的 `withdraw` 确认子阶段

`election_stage` 取值扩展为 `""/"candidacy"/"withdraw"/"vote"/"direction"/"announce"`：

1. candidacy 全员声明完毕：候选集为空 → 警徽流失（照旧）；非空 → `election_stage="withdraw"`（原直接进 `"vote"`）。
2. `withdraw` 子阶段：每位候选人确认一次——
   - `RUN_FOR_SHERIFF` = 坚持竞选：发 `SHERIFF_CANDIDACY(seat, running=True)`（PUBLIC 再确认；其 reduce 对已在集内的座位是安全无操作）；
   - `WITHDRAW` = 退水：发 `SHERIFF_WITHDREW(seat)`（PUBLIC）。
   两者都把座位加入确认游标 `sheriff_confirmed`（cursor，`model_copy`，与 `election_stage` 同类）。
3. `expected_actors(SHERIFF_ELECTION, stage=="withdraw")` = `sheriff_candidates − sheriff_confirmed`（退水者已被事件从候选集移除，天然不再被期待）。
4. 全员确认后 `_advance_election`：候选集空 → `_finish_election(None)`（警徽流失）；否则 `election_stage="vote"` 并重置 `sheriff_votes`（照旧）。

## 3. 数据模型

- **事实**（经事件写入）：`GameState.sheriff_withdrawn: frozenset[int] = frozenset()`。
- **事件**：实现预留的 `EventType.SHERIFF_WITHDREW`（PUBLIC）+ `SheriffWithdrewPayload(seat: int)`；reduce：`sheriff_candidates` 移除该座、`sheriff_withdrawn` 加入该座。
- **映射**：`EVENT_PAYLOAD_TYPES` 加 `SHERIFF_WITHDREW → SheriffWithdrewPayload`；`test_fail_loud.py` 的映射完整性测试 reserved 集合移除 `SHERIFF_WITHDREW`（issue #4 设计的 tripwire 正常触发，非回归）。
- **游标**（`model_copy`）：`GameState.sheriff_confirmed: frozenset[int] = frozenset()`（withdraw 子阶段的确认进度；不参与 reduce==live 事实断言，与 `election_stage` 同列文档化例外）。

## 4. 投票权剥夺

- `expected_actors` 的竞选 `vote` 分支与 `SHERIFF_PK` 投票人集合追加条件 `p.seat not in state.sheriff_withdrawn`。
- `_validate_sheriff` 的 `VOTE_SHERIFF` 分支显式拒绝退水者（`CANNOT_VOTE`，纵深防御）。
- 作用域：整场竞选（首轮 + PK 重投）。白天放逐投票（`DayVote`/`can_vote`）不受影响。

## 5. 已核对的交互

- **withdraw 子阶段自爆**：phase 仍为 `SHERIFF_ELECTION`，`_validate_self_destruct` 本就允许；吞警徽路径不变。
- **PK 发言队列**：tie 成员恒为在场候选人（退水者已出候选集），不受影响。
- **方向决策子阶段（issue #2）**：在 `_finish_election` 之后，与 withdraw 子阶段互不相交。
- **信息隔离**：退水公开（PUBLIC 事件），observation 无需改动。
- **确定性**：带警长对局的事件日志形态改变（多一个子阶段），determinism 比较同代码两次运行——不受影响；扫描重验。

## 6. Bot

`RandomBot.choose_action` 在 `election_stage == "withdraw"` 分支：按 `(seed, seat, state_version)` 派生 1/8 概率退水（`derive_int(..., modulo=8) == 0`），否则坚持（`RUN_FOR_SHERIFF`）——扫描可自然触达全员退水与正常路径。

## 7. 测试

新增 `backend/tests/test_withdraw.py`：
- 子阶段流转：candidacy 完毕 → `withdraw` 期待全体候选人 → 确认/退水 → `vote`。
- 退水效果：退水者不在竞选 `vote` 与 `SHERIFF_PK` 投票人集合；显式投票被拒（`CANNOT_VOTE`）；白天 `VOTE` 仍可投。
- 全员退水 → `SHERIFF_ELECTED(None)`（警徽流失）后正常续接死讯公布。
- reduce 层：`SHERIFF_WITHDREW` 从候选集移除并写入 `sheriff_withdrawn`。
- 更新 `test_fail_loud.py` 映射完整性（reserved 集合 −1）。
- 回归：全量套件、确定性、500 局扫描、mypy strict + ruff 全绿。

## 8. 明确不在范围

- 竞选发言阶段本身（M2；届时退水窗口可并入发言轮，本子阶段语义不变）。
- `GAME_CREATED`/`GAME_STARTED`/`SHERIFF_BADGE_LOST` 其余预留事件的实现。
- 全员上警零投票人边角（issue #9）。
