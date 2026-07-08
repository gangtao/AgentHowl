# 竞选期自爆「立即天黑」精确化 — 设计文档

> 日期：2026-07-07 · 状态：已批准 · 关联：GitHub issue #8（主）+ issue #15（bot 覆盖并入）· 上游：`docs/specs/requirements.md` §2（自爆=狼人白天翻牌，立即天黑）

## 1. 目标

消除 M1 已知近似：竞选期自爆后补公布首夜死讯时，若经 `HUNTER_SHOOT`/`LAST_WORDS` 绕行（等待玩家输入后经 resume token 续接），流程会落入正常 `DAY_SPEECH` 而非跳过当天。修复后：**无论是否绕行，处理完猎人开枪与遗言后严格跳过当天发言/投票直接入夜**。同时并入 issue #15 的 bot 覆盖：竞选/警上 PK 阶段低概率自爆，使 500 局扫描真实触达该路径。

**语义边界（不变）**：自爆跳过的是当天的讨论与投票；死亡结算权利（猎人开枪、遗言）照常处理——「立即天黑」不剥夺枪与遗言。

**交付判据**：
- 竞选期自爆 + 死讯绕行（猎人开枪/遗言）后，流程进入下一夜，全程不出现 `DAY_SPEECH`；
- 同步无绕行路径行为不变（原 hack 的语义保留）；白天自爆路径不变；
- bot 在 `SHERIFF_ELECTION`（candidacy/withdraw/vote）与 `SHERIFF_PK` 低概率自爆；扫描/确定性全绿。

## 2. 缺陷机理（现状）

`_after_self_destruct` 竞选分支调用 `_announce_and_continue_night` 后，用 `if state.phase == DAY_SPEECH` 强制收day——只覆盖**同步**落入白天的情形。若公布死讯触发 `HUNTER_SHOOT`（`resume_token="night_after_hunter"`）或 `LAST_WORDS`（`"day_speech"`），函数在等待输入处返回；后续 resume 经 `_finish_night_deaths` → `_enter_day_speech` 进入正常白天——跳过失效。

**结构事实**：`_enter_day_speech` 只有两个调用点（`_system_transition` 的 LAST_WORDS `"day_speech"` 续接、`_finish_night_deaths` 无遗言路径），所有直达/绕行路径都经此漏斗。

## 3. 机制：skip_day 游标 + 漏斗消费

- `GameState.skip_day: bool = False` —— 流程游标（`model_copy`，与 `resume_token` 同类、同文档化例外；不参与 `reduce==live` 事实断言）。
- **置位**：`_after_self_destruct` 竞选分支在调用 `_announce_and_continue_night` 前，与清 `election_stage` 一并置 `skip_day=True`。
- **消费**：`_enter_day_speech` 首行——`skip_day` 为真则清零并直接 `return _after_day_death(state)`（其内已含胜负判定、`max_rounds` 平局与入夜，无需重复）。
- **删除**：`_after_self_destruct` 尾部的 `if state.phase == DAY_SPEECH` 强制收day块（含其 win check）——被漏斗完全取代（同步路径同样经 `_enter_day_speech`）。
- 白天自爆分支（直接判胜/入夜）不变；`skip_day` 在该路径永不置位。

## 4. Bot（并入 issue #15）

`RandomBot.choose_action`：存活狼人在 `SHERIFF_ELECTION`（candidacy/withdraw/vote 任一子阶段轮到自己行动时）与 `SHERIFF_PK`（发言或投票回合）以 1/24 seeded 概率（`derive_int(..., modulo=24) == 0`，低于白天的 1/20，因竞选人人有行动点）返回 `SelfDestruct`，否则走原分支。生成处需先判 `pl.faction == Faction.WOLF and pl.alive`。

## 5. 测试

新增 `backend/tests/test_self_destruct_skip.py`：
- **绕行路径（核心）**：构造竞选期状态——`night_deaths` 含一名可开枪猎人（夜刀死、`hunter_can_shoot=True`），狼人自爆 → 断言吞警徽、死讯公布、进入 `HUNTER_SHOOT`；猎人开枪 → 遗言（首夜死者）逐个发言 → 断言直接进入第 2 夜（`round==2` 的夜间阶段），事件流中**无** `PHASE_CHANGED(to=DAY_SPEECH)`。
- **同步路径回归**：竞选期自爆 + 空死讯（平安夜，`night_deaths=()`——竞选恒在首夜后，非空死讯在 `FIRST_NIGHT_ONLY` 下必有遗言绕行，故同步路径即平安夜）→ 无绕行直接入夜（原 hack 语义保留）。
- **白天自爆不变**：`DAY_SPEECH` 自爆 → 入夜（既有 test_sheriff 用例保持，另加 skip_day 恒 False 断言）。
- **bot 覆盖**：多 seed 完整对局断言终局，且事件流中出现竞选期 `WOLF_SELF_DESTRUCT`（seed 数量可调以命中概率）。
- 回归：全量套件、确定性、500 局扫描、mypy strict + ruff 全绿。

## 6. 明确不在范围

- 自爆是否压缩遗言/枪（村规变体）——维持「结算权利照常」，如需变体另开配置 issue。
- issue #15 的另一半（`expected_actors(direction)` 忽略残留 speech_order 的锁定测试）——顺手加入本次测试文件（一行级），在两个 issue 里都注明。
