# 警徽流（badge_flow）结构校验、记录与暴露 — 设计文档

> 日期：2026-07-07 · 状态：已批准 · 关联：GitHub issue #7 · 上游：`docs/specs/requirements.md` §2（警徽流=预言家公布未来两夜验人计划）、§3 line 88、§4.1（speak 工具 schema）、`SheriffRule.badge_flow_enabled`（现为死配置）

## 1. 目标

把 `badge_flow` 从纯透传升级为：结构校验（含激活死配置 `badge_flow_enabled`）、事实记录、observation 公开暴露。**引擎只校验结构、绝不校验真实性或真实角色**——悍跳狼报警徽流是合法伪装（规格 §4.4.2）。

**交付判据**：
- 仅竞选语境的发言可携带非空 `badge_flow`（M1 = `SHERIFF_PK` 发言回合；M2 竞选发言落地后自然扩展）；其他语境携带非空警徽流 → 拒绝；
- 结构非法（配置关闭 / 超长 / 座位不存在 / 座位已死 / 重复座位）→ 整条发言被拒（新 `RejectedReason.BADGE_FLOW_INVALID`）；
- 最新声明记录为事实 `badge_flow_claims` 并在 observation 公开；
- `badge_flow=()` 默认路径零行为变化；全部既有测试、确定性、500 局扫描保持通过。

## 2. 配置

`SheriffRule` 新增 `badge_flow_max_length: int = 2`（「一般留两夜」是约定非法律，可配置——无规则硬编码）。`badge_flow_enabled: bool = True` 由死配置转为受检项。

## 3. 校验（engine.py `_validate` 的 Speak 门内）

在既有 Speak 门（阶段/PK 发言期/BIDDING 检查）通过后，若 `action.badge_flow` 非空，追加：
1. 语境：当前必须是 `SHERIFF_PK` 的发言回合（`pk_speaking` 且 `phase == SHERIFF_PK`）——白天发言/遗言/放逐 PK（`VOTE_PK`）携带非空警徽流均拒绝；
2. `config.sheriff.badge_flow_enabled` 为 True；
3. `len(badge_flow) <= config.sheriff.badge_flow_max_length`；
4. 每个座位存在且存活；
5. 无重复座位。
任一不满足 → `RejectedReason.BADGE_FLOW_INVALID`（新枚举成员）。角色不参与判定（悍跳合法）。

## 4. 记录（事实，零新事件）

`GameState.badge_flow_claims: dict[int, tuple[int, ...]] = {}`（speaker → 最新声明）。由既有 `PLAYER_SPOKE` reduce 扩展：payload 的 `badge_flow` 非空时写入 `{actor: badge_flow}`（覆盖旧声明）。校验在发射前完成，故到达 reduce 的声明均已合法；reduce 无条件按 payload 记录（重放一致）。`reduce==live` 结构性成立。

## 5. 暴露（observation.py）

`PlayerObservation` 新增公开字段 `badge_flow_claims: dict[int, tuple[int, ...]]`（发言本为公开内容，所有座位与观众可见）。无其他隔离改动。

## 6. Bot

`RandomBot` 在 `SHERIFF_PK` 发言回合以 1/4 seeded 概率附带合法声明（1–2 个存活非己座位，经 `derive_int` 派生），使扫描真实覆盖校验与记录路径。

## 7. 测试

新增 `backend/tests/test_badge_flow.py`：
- 接受：SHERIFF_PK 发言回合携带合法声明 → 通过、`badge_flow_claims` 记录、observation 可见。
- 语境拒绝：DAY_SPEECH / VOTE_PK 发言回合携带非空声明 → `BADGE_FLOW_INVALID`。
- 结构拒绝矩阵：配置关闭、超长（>max_length）、座位越界、座位已死、重复座位。
- 覆盖声明：同一 speaker 二次声明覆盖旧值。
- 空声明零变化：普通发言照旧。
- 回归：全量套件、确定性、500 局扫描（bot 现在偶发报警徽流）、mypy strict + ruff 全绿。

## 8. 明确不在范围

- 真实性/角色校验（永不做——伪装是游戏机制）。
- 警徽流的语义利用（如警长死亡时向继任者传递验人信息的自动化）——M2 agent 层消费。
- M2 竞选发言阶段本身。
