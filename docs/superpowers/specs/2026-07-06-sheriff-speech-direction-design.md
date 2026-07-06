# 警长发言方向（SHERIFF_DECIDES + set_speech_direction）— 设计文档

> 日期：2026-07-06 · 状态：已批准 · 关联：GitHub issue #2 · 上游：`docs/specs/requirements.md` §3（发言顺序/警长权利）、§4.1（sheriff_action schema）

## 1. 目标

实现规格中「有警长时由警长决定发言方向（警左/警右），第二天起换手」。当前 `Direction`/`SET_SPEECH_DIRECTION`/`SheriffAction.direction` 为规格预留但无引擎消费方；`_speech_order` 的 `SHERIFF_DECIDES` 分支固定从警长下家顺时针，既不接受警长选择，也不换手。

**交付判据**：
- `speech_order_rule=SHERIFF_DECIDES` 下，当选警长在首日选定 `LEFT`/`RIGHT`，当天发言顺序据此排序；
- 第二天起方向自动换手（上一天警左则下一天警右）；
- 无存活警长（警徽流失/警长已死）时退回「死者下家 + 顺时针」（death-next）；
- 全部既有测试、确定性（`reduce==live`）、四 preset 完整对局与 500 局扫描保持通过。

## 2. 数据模型

- 新增 `GameState.sheriff_speech_direction: str | None = None` —— 警长在首日选定的**基准**方向（`"LEFT"`/`"RIGHT"`）。这是游戏事实，只经事件写入。
- 新增事件类型 `SHERIFF_DIRECTION_SET`（`PUBLIC`）与 payload `SheriffDirectionSetPayload(direction: str)`；其 reduce 分支设置 `sheriff_speech_direction = p.direction`。
- 方向以字符串（`Direction` 枚举的 `.value`）存储，避免 `state.py` 反向依赖 `actions.py`（分层：state 只 import config/phases）。

## 3. 流程：竞选后的方向决策点

复用 `SHERIFF_ELECTION` 阶段与 `election_stage` 游标，新增一个 `"direction"` 子阶段：

1. `_finish_election(elected)`：发 `SHERIFF_ELECTED(elected)` 后——
   - 若 `elected is not None` **且** `config.speech_order_rule == SHERIFF_DECIDES`：置 `election_stage="direction"`，**停留在 `SHERIFF_ELECTION`**（不立即公布死讯），返回，等待警长输入；
   - 否则（警徽流失，或非 SHERIFF_DECIDES 规则）：置 `election_stage=""`，照旧 `_announce_and_continue_night(state, night_deaths, events)`。
2. `expected_actors(SHERIFF_ELECTION)` 增加分支：`election_stage=="direction"` → `{sheriff_seat}`。
3. `_apply_sheriff` 处理 `SET_SPEECH_DIRECTION`：发 `SHERIFF_DIRECTION_SET(direction)`，随后把游标推进到独立标记 `election_stage="announce"`（cursor，允许 model_copy），使 `expected_actors` 不再返回警长（不重复询问）。
4. `_advance_election`：当 `election_stage=="announce"` → 清空 `election_stage=""` 并 `_announce_and_continue_night(state, state.night_deaths, events)` 续接被推迟的死讯公布。用独立标记 `"announce"`（而非空串）避免与竞选入场前的初始 `""` 混淆。`expected_actors` 对 `"announce"` 返回空集（落入 SHERIFF_ELECTION 分支的默认空集）。

> 时序保证：竞选在首夜结算后、公布死讯前（round==1）。因此方向在首日选定，首日 `DAY_SPEECH` 即用之；第二天起自动换手。当选警长首日必存活，故方向决策点总有合法行动者。

## 4. 顺序计算（`_speech_order` 的 SHERIFF_DECIDES 分支）

```
if rule == SHERIFF_DECIDES:
    if sheriff_seat is not None and sheriff_speech_direction is not None:
        base = sheriff_speech_direction            # "LEFT" / "RIGHT"
        effective = base if round % 2 == 1 else opposite(base)   # 竞选在 round 1；换手
        if effective == "RIGHT":
            return _clockwise_from((sheriff_seat + 1) % n)        # 警右=顺时针
        return _counterclockwise_from((sheriff_seat - 1) % n)     # 警左=逆时针
    return _death_next_order(state)                # 无警长/未定向 -> death-next 退回
```

- 新增 `_counterclockwise_from(start)` helper：从 `start` 逆时针（座号递减 mod n）过滤存活者。
- 把现有 `DEATH_NEXT` 分支逻辑抽成 `_death_next_order(state)`，供 `DEATH_NEXT` 与 `SHERIFF_DECIDES` 退回共用（DRY）。
- `opposite("LEFT")=="RIGHT"`，反之亦然。

## 5. 校验与 Bot

- `_validate_sheriff`：新增 `election_stage=="direction"` 分支——仅接受 `SET_SPEECH_DIRECTION`，`direction` 必须非 None，且 `actor_seat == sheriff_seat`（`expected_actors` 已限定，但显式校验更稳）。其余行动类型在此子阶段返回 `WRONG_PHASE`。
- RandomBot：在 `SHERIFF_ELECTION` 且 `election_stage=="direction"` 时，按 `(seed, seat, state_version)` 派生选 `LEFT`/`RIGHT`（确定性），返回 `SheriffAction(set_speech_direction, direction=...)`。

## 6. 测试

新增 `backend/tests/test_speech_direction.py`（或并入 `test_sheriff.py`）：
- 警长选 `RIGHT` → 顺序为从 `sheriff+1` 顺时针的存活序；选 `LEFT` → 从 `sheriff-1` 逆时针的存活序。
- 换手：同一 base 下，round 1 与 round 2 的有效方向相反（构造 round=2 态断言逆序）。
- 无警长（`sheriff_seat=None`）+ SHERIFF_DECIDES → death-next 顺序（死者下家开始）。
- 方向决策点：竞选选出警长后进入 `election_stage=="direction"`，`expected_actors=={sheriff}`；提交 `set_speech_direction` 后恢复公布死讯并进入白天。
- 回归：`reduce==live`（`SHERIFF_DIRECTION_SET` 为事件、`sheriff_speech_direction` 经 reduce 写入）、四 preset 完整对局、500 局扫描、mypy strict + ruff（check+format）全绿。

## 7. 明确不在范围

- 「死左/死右」（以死者为基准的方向）—— 规格 §3 提及但作为后续可选；本次只做「警左/警右」。
- 归票（vote-herding）与发言超时——非本 issue。
