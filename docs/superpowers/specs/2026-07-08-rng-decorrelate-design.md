# 随机抽取去相关：seq = state_version，删除 rng_state — 设计文档

> 日期：2026-07-08 · 状态：已批准 · 关联：GitHub issue #12 · 根因：`rng_state` 仅在 `ROLES_ASSIGNED` 写入一次（恒 =1），整局所有引擎随机抽取共用同一 seq

## 1. 缺陷与目标

引擎两处随机抽取（`_wolf_consensus` 的 `RANDOM_PROPOSAL`、`_tally_and_continue` 的 `PK_THEN_RANDOM`）以 `seq=state.rng_state` 派生——整局恒定，同 purpose 下若两次抽取候选池长度与排序相同则必中同一下标（确定但统计退化）。目标：每次抽取的 seq 唯一（去相关），且完全可重放。

## 2. 机制：seq = state_version；删除 rng_state

- **两处抽取** 改为 `seq=state.state_version`：事件推导、单调递增、每个抽取点唯一、重放恒同——即 bot 既有的成熟模式（`bot.py` 全部抽取已用 state_version）。
- **删除死机制**：`GameState.rng_state` 字段、`RolesAssignedPayload.new_rng_state` 字段、`ROLES_ASSIGNED` reduce 的 `"rng_state": ...` 写入、`create_game` 的对应实参——切换后无任何读者，按 fail-loud/无死代码风格移除（M2 前契约变更成本最低）。
- **文档同步**：`rng.py` 模块 docstring（「rng_state 只是一个递增计数器」→ 指明 `state_version` 为 seq 来源）与 `events.py` 头部 docstring（「rng_state 由使用随机的事件在 payload 里带出新值」行删除/改写）。
- **不动项**：发牌 `rng.shuffle(seed, "deal", ...)`（一次性、purpose 区分、无需 seq）；bot 抽取（已用 state_version）。

## 3. 行为影响

抽取结果相对现状改变（seq 不同）——确定性测试比较同代码两次运行，不受影响；500 局扫描重验终止性。同局内两次同 purpose 抽取（不同 state_version）从此可得不同结果——这正是本 issue 要恢复的性质。

## 4. 测试

- **契约迁移**：`test_wolf_kill_rule.py::test_random_proposal_weighted_and_deterministic`（唯一引用点，81 行）的独立公式改为 `seq=st.state_version`——继续钉死派生契约（purpose/seq 来源/排序池/modulo）。
- **新增去相关演示**（`test_rng_decorrelation.py` 或并入 test_wolf_kill_rule）：
  - 相同提案池、仅 `state_version` 不同的两个状态，`RANDOM_PROPOSAL` 抽中不同座位（选定 seed 使两 idx 确实不同，测试内用 `derive_int` 预算证明非巧合）；
  - `PK_THEN_RANDOM` 同法一例。
- 回归：全量套件、确定性、500 局扫描、mypy strict + ruff 全绿；`grep -rn "rng_state" backend/app backend/tests` 零残留（docstring 提及除外，亦应清理为零）。

## 5. 不在范围

- 发牌洗牌机制；bot 抽取；`derive_int`/`shuffle` 本体。
