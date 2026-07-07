# 引擎 fail-loud：拒绝畸形事件与未知警长行动 — 设计文档

> 日期：2026-07-07 · 状态：已批准 · 关联：GitHub issue #4 · 上游：引擎「绝不静默继续」原则（`EngineInvariantError`）

## 1. 目标

消除两处「静默继续」：
1. `_reduce_dispatch` 的兜底 `return {}`：对「已知 EventType 但 payload 类型不匹配」的畸形事件只 bump `state_version` 不报错；4 个预留 EventType（`GAME_CREATED`/`GAME_STARTED`/`SHERIFF_WITHDREW`/`SHERIFF_BADGE_LOST`，M1 从不发射）被发射时也静默无操作。
2. `_apply_sheriff` 的隐式兜底：任何未枚举的 `SheriffActionType` 落入 `vote_sheriff` 分支（今日靠校验层兜底不可达，但枚举增长时会静默误分类）。

**交付判据**：畸形事件与预留事件在 `reduce` 处抛 `EngineInvariantError`；`_apply_sheriff` 兜底显式抛错；合法事件路径行为零变化（确定性测试字节级原样通过）；全部既有测试保持通过。

## 2. 事件↔payload 强制（events.py）

- 模块级映射 `EVENT_PAYLOAD_TYPES: dict[EventType, type[EventPayload]]`，**只含** 28 个已实现类型 → 其具体 payload 类（如 `PHASE_CHANGED → PhaseChangedPayload`）。4 个预留类型有意缺席——「未映射 = 未实现」，M2 实现时再补 payload + reduce 分支 + 映射。
- `reduce()` 顶部、分派之前：
  - `event.type not in EVENT_PAYLOAD_TYPES` → `EngineInvariantError`（未实现的事件类型）；
  - `not isinstance(event.payload, EVENT_PAYLOAD_TYPES[event.type])` → `EngineInvariantError`（payload 类型不匹配）。
- 分派内各分支的 `isinstance` 守卫保留（mypy 收窄用）；末尾 `return {}` 兜底对状态而言已不可达（映射保证必中某分支），保留并注释说明。合法事件路径零变化 → 确定性字节级不变。
- 单一执行点：不在 `Event` 模型加构造校验（映射只维护一处，写路径即执法点；重放/反序列化事件同样经 `reduce` 被覆盖）。

## 3. 异常归属：`EngineInvariantError` 移至 events.py

`EngineInvariantError` 现定义在 `engine.py`，而 `engine.py` import `events.py`。为让 `reduce` 抛该异常且不引入循环 import：把类定义**移到 `events.py`**（下层模块），`engine.py` 改为 `from app.engine.events import EngineInvariantError` 并保持名字可从 `engine` import（既有测试/调用方零改动）。

## 4. 警长行动兜底（engine.py）

`_apply_sheriff` 末尾的隐式 `# vote_sheriff` 兜底改为显式守卫：

```python
    if at != SheriffActionType.VOTE_SHERIFF:
        raise EngineInvariantError(f"未处理的警长行动类型：{at}")  # 校验层应已拦截
    # vote_sheriff 发射照旧
```

今日该分支不可达（6 个成员全部被上方分支或此守卫枚举）；守卫防止未来枚举增长时静默误分类为投票。

## 5. 测试

新增 `backend/tests/test_fail_loud.py`：
- payload 不匹配：构造 `type=PHASE_CHANGED` + `DeathAnnouncedPayload` 的事件，`reduce` 抛 `EngineInvariantError`。
- 预留类型：构造 `type=GAME_CREATED` 事件，`reduce` 抛 `EngineInvariantError`。
- 映射完整性：`set(EVENT_PAYLOAD_TYPES) == set(EventType) - {GAME_CREATED, GAME_STARTED, SHERIFF_WITHDREW, SHERIFF_BADGE_LOST}`（枚举新增成员时此测试强制作者决策：实现或列入预留）。
- 合法事件仍正常 reduce（抽查 PHASE_CHANGED 正例）。
- `_apply_sheriff` 守卫：以 `VOTE_SHERIFF` 正例直测通过；抛错分支在当前枚举下不可达，作为防御性代码不单测（注释说明），由映射完整性测试的同类机制护栏。
- 回归：全量套件、确定性（字节级不变）、500 局扫描、mypy strict + ruff 全绿。

## 6. 明确不在范围

- `Event` 构造期校验（双执行点，YAGNI）。
- 预留类型的实际实现（M2 runtime）。
- reduce 分派结构重构（如 dict-of-handlers）——只加前置校验，不动分派。
