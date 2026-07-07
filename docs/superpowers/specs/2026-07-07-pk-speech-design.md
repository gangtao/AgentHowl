# PK 发言轮（平票者再发言）— 设计文档

> 日期：2026-07-07 · 状态：已批准 · 关联：GitHub issue #5 · 上游：`docs/specs/requirements.md` §3（放逐平票 line 91、警长竞选平票 line 86）

## 1. 目标

补齐 M1 简化：平票后，平票者先在 PK 台依次发言，随后才由未平票者重投。覆盖**两处** PK：白天放逐的 `VOTE_PK` 与警长竞选的 `SHERIFF_PK`。

**交付判据**：
- 放逐平票：平票者按座号升序依次发言（`PLAYER_SPOKE`），发言未完时投票不开放；发言完毕后仅未平票者投票，余下裁决（再平票按 `TieRule`）不变。
- 警长竞选平票：同机制（平票候选人发言 → 警下重投 → 再平票警徽流失不变）。
- 越权/越序/发言完毕后的 `Speak` 被拒绝；全部既有测试、确定性、500 局扫描保持通过。

## 2. 机制：复用发言队列，零新状态、零新事件

- **入 PK 携带发言队列**：`_tally_and_continue` 的平票分支改为 `PHASE_CHANGED(to=VOTE_PK, speech_order=tie)`（`tie` 来自 `count_votes`，已是升序 tuple）；`_advance_election` 的 PK 分支同样改为 `PHASE_CHANGED(to=SHERIFF_PK, speech_order=tie)`。既有 reduce 已处理 `speech_order` 载荷（置队列、`speech_idx=0`）。入口处的 `VOTE_STARTED`（放逐）/ `sheriff_votes={}` 重置（竞选）照旧。
- **发言先行的 expected_actors**：`VOTE_PK` 与 `SHERIFF_PK` 分支改为——`speech_idx < len(speech_order)` 时返回 `{speech_order[speech_idx]}`（当前平票发言者）；队列耗尽后返回既有投票人集合（存活、can_vote、非平票者、未投）。投票在结构上不可能先于发言。
- **PK 发言即普通公开发言**：`PLAYER_SPOKE`（PUBLIC），其既有 reduce 推进 `speech_idx` —— `reduce==live` 零新管道。

## 3. 校验（engine.py `_validate` 的 Speak 门）

`Speak` 合法阶段从 `{DAY_SPEECH, LAST_WORDS}` 扩展为：`VOTE_PK`/`SHERIFF_PK` **仅当 PK 发言队列未耗尽**（`speech_idx < len(speech_order)`）时合法；队列耗尽后 `WRONG_PHASE`（保持 fail-loud 姿态，不重开 Task-12 修过的越权口子）。行动者身份仍由 `expected_actors` 门（`NOT_YOUR_TURN`）约束。BIDDING 拒绝镜像到 PK 发言（`DAY_SPEECH` 或 PK 发言 + `speech_order_rule==BIDDING` → `BIDDING_NOT_IMPLEMENTED`），保持一致性。

## 4. Bot

`RandomBot.choose_action`：在既有 `VOTE/VOTE_PK` 投票分支与 `SHERIFF_PK` 投票分支**之前**加一个分支——`ph in (VOTE_PK, SHERIFF_PK)` 且 `speech_idx < len(speech_order)` → `Speak(content="(bot-pk)")`。（该分支只会在轮到自己发言时被调用，因 run_game 只驱动 expected actor。）

## 5. 已核对的交互

- **自爆**：`SHERIFF_PK` 期间自爆本就合法（`_validate_self_destruct` 允许），流程（吞警徽/入夜）不变；PK 发言阶段自爆同样走该路径。
- **零投票人边角**（全员上警，issue #9）：发言照常进行，队列耗尽后无合法投票人 → 空票裁决与今日一致（终止性不变），语义仍由 issue #9 另行处理。
- **确定性**：测试比较同代码两次运行，事件日志变长（多了 PK 发言）不影响；`reduce==live` 因全部经既有事件而结构性成立。

## 6. 测试

新增 `backend/tests/test_pk_speech.py`：
- 放逐 PK 全流程：构造 2-2 平票 → 进入 `VOTE_PK` 时 `speech_order==tie`（升序）→ `expected_actors` 依次为各平票者 → 平票者逐个发言（事件为 `PLAYER_SPOKE`）→ 队列耗尽后 `expected_actors` 变为未平票投票人 → 投票出结果。
- 拒绝矩阵：非当前发言者 `Speak` → `NOT_YOUR_TURN`；投票人在发言期投票 → `NOT_YOUR_TURN`（不在 expected）；队列耗尽后再 `Speak` → `WRONG_PHASE`。
- 警长 PK 全流程：构造竞选平票 → `SHERIFF_PK` 带发言队列 → 发言 → 警下重投 → 当选或再平票警徽流失。
- 回归：全量套件、确定性、500 局扫描（bot 现在真实走 PK 发言路径）、mypy strict + ruff 全绿。

## 7. 明确不在范围

- PK 发言顺序的可配置化（固定座号升序）。
- 竞选上警阶段的竞选发言（M1 简化项，独立于 PK；另行处理）。
- 全员上警零投票人语义（issue #9）。
