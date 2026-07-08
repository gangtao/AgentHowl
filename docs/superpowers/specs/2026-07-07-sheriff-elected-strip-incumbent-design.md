# SHERIFF_ELECTED reduce 剥离在任者 — 设计文档（bugfix）

> 日期：2026-07-07 · 状态：已批准 · 关联：GitHub issue #19（bug）· 根因已由 PR #20 终审机械定位

## 1. 缺陷与根因

警长狼在方向决策子阶段自爆且 `wolf_selfdestruct_eats_badge=True` 时：`_apply_self_destruct` 发 `SHERIFF_ELECTED(seat=None)`；其 reduce（events.py）在 `seat is None` 分支**只置空 `sheriff_seat`、不清除在任者的 `is_sheriff`**；`_auto_badge_if_orphaned` 因 `sheriff_seat` 已空而 no-op。结果：死者 `is_sheriff=True` 而 `sheriff_seat=None`。当前惰性（is_sheriff 仅对存活者读取），但属事实层不一致，前端/回放会显示死者持徽。

## 2. 修复：reduce 全化（方案 A）

`SHERIFF_ELECTED` reduce 改为**全化**语义——任何一次当选/流失事件都先剥离在任者、再授予新任者：

```python
    if t == EventType.SHERIFF_ELECTED and isinstance(p, SheriffElectedPayload):
        players = state.players
        if state.sheriff_seat is not None:
            players = _replace_player(players, state.sheriff_seat, is_sheriff=False)
        if p.seat is not None:
            players = _replace_player(players, p.seat, is_sheriff=True)
        return {"sheriff_seat": p.seat, "players": players}
```

- 恢复不变量：`sheriff_seat` 与 `is_sheriff` 不再可能经此事件分叉——对今日的方向阶段自爆路径与任何未来发射方一律成立。
- 正常竞选路径零影响（当选时无在任者，剥离为 no-op）。
- 发射方（engine.py）不改；事件日志不变，仅先前错误路径的 reduce 结果被修正——确定性（同代码两次运行）不受影响。
- 不选方案 B（吞警徽改发 `BADGE_PASSED`）：会把吞警徽分裂为两种事件形态，且 `SHERIFF_ELECTED(None)` 带在任者的陷阱对未来发射方仍然存在。

## 3. 测试

追加到 `backend/tests/test_self_destruct_skip.py`：
- **端到端复现**：方向决策子阶段（`election_stage="direction"`、`sheriff_seat=狼座`、该狼 `is_sheriff=True`）自爆 → 断言 `sheriff_seat is None` 且**无任何死者 `is_sheriff=True`**（修复前此断言失败）。
- **reduce 单元**：`SHERIFF_ELECTED(None)` 作用于带在任者的状态 → 在任者 `is_sheriff` 被清除。
- **回归**：正常当选仍正确设置 `is_sheriff`（既有 test_sheriff 覆盖 + 一条显式断言）。
- 全量套件、确定性、500 局扫描、mypy strict + ruff 全绿。

## 4. 不在范围

- `BADGE_PASSED` 语义细化 / DAY_SKIPPED 标记（issue #17 主题）。
