# 狼刀决策规则 GameConfig 开关 — 设计文档

> 日期：2026-07-06 · 状态：已批准 · 关联：GitHub issue #3 · 上游：`docs/specs/requirements.md` §3.1（狼人刀法）、§1.3（无规则硬编码）

## 1. 目标

`_wolf_consensus`（engine.py）硬编码「全员一致→刀，否则空刀」，是引擎中最后一条未走 `GameConfig` 开关的规则。本设计将其参数化为 `wolf_kill_rule`，默认保持现有语义（规格默认「意见不统一视为空刀」），零行为变化。

**交付判据**：
- 三种规则可配置且各自语义正确（见 §3）；
- 默认值下所有既有行为逐字节不变（确定性测试即证明）；
- 全部既有测试、四 preset 完整对局、500 局扫描保持通过。

## 2. 配置

`config.py` 新增：

```python
class WolfKillRule(StrEnum):
    UNANIMOUS_OR_NO_KILL = "UNANIMOUS_OR_NO_KILL"  # 全员一致才刀，否则空刀（默认，现行为）
    MAJORITY = "MAJORITY"                          # 简单多数；平票→空刀
    RANDOM_PROPOSAL = "RANDOM_PROPOSAL"            # 在提案池中按权重随机
```

`GameConfig.wolf_kill_rule: WolfKillRule = WolfKillRule.UNANIMOUS_OR_NO_KILL`。四个 preset 不显式设置（继承默认），保证既有对局字节级不变。

## 3. 决策语义（`_wolf_consensus` 按规则分派）

输入：`state.wolf_proposals: dict[int, int | None]`（每只存活狼一票；`None`=空刀提案）。输出：`int | None`（刀口或空刀）。

- **UNANIMOUS_OR_NO_KILL**：现逻辑原样 —— 所有提案相同且非 None → 该目标；否则 None。
- **MAJORITY**：每票（含 None=「空刀票」）计数，**相对多数**（唯一最高票）者胜——无需过半；最高票并列（含与空刀票并列）→ None（与规格「意见不统一视为空刀」哲学一致）。纯计数、无随机；计数迭代按排序键保证确定性。
- **RANDOM_PROPOSAL**：池 = 非 None 提案的**多重集**（2 狼提同一目标 → 权重 ×2），排序后经既有模式 `rng.derive_int(seed, purpose="wolf_kill", seq=state.rng_state, modulo=len(pool))` 抽取；全 None → None。

决策仍经既有 `WOLF_KILL_DECIDED` 事件流出——事件 schema 与 reduce 零改动，`reduce==live` 结构性不受影响。

## 4. 与既有开关的交互

- `allow_wolf_empty_knife=False`：校验层已拒绝 skip 提案；MAJORITY/RANDOM 下决策仍可能为 None（平票/理论上的全 skip）——与今日「意见不统一→空刀」同性质，属预期行为，注释注明。
- `allow_wolf_self_knife`：作用于提案校验层，与决策规则正交，不变。

## 5. 测试

新增 `backend/tests/test_wolf_kill_rule.py`：
- UNANIMOUS：一致→刀；分歧→None；任一 skip→None（回归现语义）。
- MAJORITY：3-1→多数目标；2-2→None；空刀票占多→None；2-1-1→多数目标。
- RANDOM_PROPOSAL：固定 seed 下按 `derive_int` 公式断言精确抽中座位；同 seed 可复现；全 skip→None；权重（同目标两票在池中出现两次）。
- 集成：MAJORITY 与 RANDOM_PROPOSAL 各跑一局自定义配置完整对局（必终局）。
- 回归：全量套件、确定性（默认值字节级不变）、500 局扫描、mypy strict + ruff 全绿。

## 6. 明确不在范围

- 狼头/leader-decides 规则（需 M1 没有的「狼队长」概念）。
- FIRST_PROPOSAL（依赖提交顺序，规则语义弱）。
- 狼队私聊协商（M2 agent 层）。
