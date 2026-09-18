# 狼队刀口收敛（可见提案 + 收敛轮）— 设计文档

> 日期：2026-09-18 · 状态：已批准 · 关联：GitHub issue #46 · 上游：`docs/specs/requirements.md` §3.1（line 85「狼人刀法：意见不统一视为空刀」）、§3.4（line 287「狼人 kill：队内共识」）、§4.2（line 450「狼人夜晚可见 `private.tonight_kill_proposal`」）；agent 层规格 `2026-07-16-agent-layer-design.md`（狼夜单次私有推理，多轮狼聊推迟）

## 1. 背景与诊断

真实 LLM 对局中狼队频繁空刀。三层原因：

1. **规则层**：默认 `WolfKillRule.UNANIMOUS_OR_NO_KILL` 要求全员提案一致。
2. **可见性断线（既有缺陷）**：runner 按座号串行驱动各狼、observation 在轮到该狼时构建，后手狼在时序上**能**看到先手提案；但 observation 的 `private.tonight_kill_proposal` 取自 `pending_night.wolf_target`——那是 `WOLF_KILL_DECIDED` **裁决后**才写入的值。狼行动时它恒为 `None`，狼夜 prompt 里「队友已提议刀 X 号」一句从未出现过；PRD §4.2「夜晚可见 `tonight_kill_proposal`」实际未兑现。队友提案只以通用格式（`WOLF_KILL_PROPOSED actor=0 {...}`，2 分）混在记忆里，小模型基本忽略。
3. **不能改口**：每狼每夜只提一次（`wolf_proposals` 按座位记录，提过即不再是 `expected_actors`）。先手提完后，后手一旦不同意就直接空刀，先手没有机会改。

现实中狼队达成一致靠三件事：**提案对队友可见、可以反复改口收敛、超时按规则兜底**（线下：法官「狼人请统一意见」，到时仍不统一算空刀；线上：队友选择实时可见可改，超时多数票、平票随机）。当前实现第一件断线、第二件不存在、第三件只有最严一档在用。

## 2. 目标与交付判据

补齐「可见 + 可改 + 兜底」，不放松规则默认值：

- 狼在夜间 observation 里看到本轮队友已提交的提案与之前各轮的分歧；非狼/死狼看不到。
- 一轮提案后若「按规则裁决为空刀，且本轮至少有一个非空提案，且轮次未用尽」→ 引擎发 `WOLF_KILL_REVOTE`（WOLVES 可见）清空提案再开一轮；末轮仍不一致按 `wolf_kill_rule` 兜底。`wolf_consensus_rounds=1` 与现状逐字节一致。
- 狼夜 prompt 列出队友提案并引导跟刀；重提轮给出上一轮分歧。仍是单次私有推理调用，公私分离不变。
- CLI 提供 `--wolf-rule` / `--wolf-rounds` 旋钮；README/Makefile 同步。
- 全程事件推导（无游标 `model_copy` 直写）；回放与 live 逐字段一致；确定性、500 局扫描、隔离矩阵全绿。

## 3. 配置（`engine/config.py`，同步 PRD §3.2）

```python
class GameConfig(BaseModel):
    ...
    wolf_kill_rule: WolfKillRule = WolfKillRule.UNANIMOUS_OR_NO_KILL  # 不变
    wolf_consensus_rounds: int = 2  # 狼队提案最多几轮（≥1）；1 = 一轮定夺（旧行为）
```

`validate_config` 增加 `wolf_consensus_rounds >= 1` 校验。默认 2：规则不变，只多一次统一意见的机会。

## 4. 引擎

### 4.1 状态（`engine/state.py`）

```python
wolf_proposals: dict[int, int | None]                  # 不变：本轮提案 seat->target
wolf_kill_round: int = 1                               # 本夜第几轮提案（事件推导）
wolf_proposal_history: tuple[tuple[tuple[int, int | None], ...], ...] = ()
# 之前各轮的提案快照（每轮为按座位排序的 (seat, target) 元组），事件推导
```

`ROUND_STARTED` 的 reduce 已重置 `wolf_proposals`；同处一并重置 `wolf_kill_round=1`、`wolf_proposal_history=()`。

### 4.2 事件（`engine/events.py`）

```python
EventType.WOLF_KILL_REVOTE = "WOLF_KILL_REVOTE"

class WolfKillRevotePayload(EventPayload):
    round_no: int                                      # 刚结束的那一轮（从 1 起）
    proposals: tuple[tuple[int, int | None], ...]      # 该轮提案快照（按座位升序）
```

- 可见性 **WOLVES**（狼队私有事实；GM/上帝视角可见，观众/非狼不可见——沿用 `WOLF_KILL_PROPOSED` 口径）。
- reduce：`wolf_proposals={}`、`wolf_kill_round=state.wolf_kill_round+1`、`wolf_proposal_history=history+(p.proposals,)`。`acted_seats` 不动（狼的 `expected_actors` 只看 `wolf_proposals`）。
- 加入 `EVENT_PAYLOAD_TYPES` 映射（fail-loud 契约）。
- 载荷携带快照而非只带轮次号：回放/前端 reducer 不必自行从 `WOLF_KILL_PROPOSED` 重建历史；`WOLF_KILL_DECIDED` 不变。

### 4.3 转移（`engine/engine.py` `_system_transition` 的 `NIGHT_WEREWOLF` 收尾）

```
target = _wolf_consensus(state)
if target is None and _has_nonempty_proposal(state) and state.wolf_kill_round < config.wolf_consensus_rounds:
    emit WOLF_KILL_REVOTE(round_no=state.wolf_kill_round, proposals=snapshot)   # 狼重新成为 expected_actors，advance 循环自然停下
    return
emit WOLF_KILL_DECIDED(target)  # 现有路径（含末轮兜底）
```

- 「全员主动空刀」（提案全为 `None`）不算分歧 → 直接空刀，不重提。
- `RANDOM_PROPOSAL` 只要有非空提案就必出结果 → 天然不重提；`MAJORITY` 只在并列时重提；`UNANIMOUS_OR_NO_KILL` 在任何不一致时重提。
- `_wolf_consensus` 的 `RANDOM_PROPOSAL` 分支 RNG purpose 不变（`"wolf_kill"`，seq=state_version）。

### 4.4 校验

不变：`Speak`/`NightAction` 校验与轮次无关；每轮每狼提一次（`expected_actors` 排除已提者）。

## 5. observation（`engine/observation.py`，同步 PRD §4.2）

狼**存活**且处于夜间时 `private` 新增（非狼/死狼不出现，隔离矩阵补断言）：

| 字段 | 值 |
|---|---|
| `kill_rule` | `config.wolf_kill_rule` 的值（**终审补记**：供 prompt 规则句分支） |
| `tonight_kill_proposals` | 本轮已提交提案 `{seat: target\|None}`（含自己；模型内键为 `int` 座位号，经 API JSON 序列化后为字符串——与既有 `badge_flow_claims` 同口径） |
| `kill_proposal_history` | 之前各轮快照列表，每项形如 `{seat: target\|None}` |
| `kill_vote_round` / `kill_vote_rounds_max` | 当前轮次 / `wolf_consensus_rounds` |

既有 `tonight_kill_proposal`（裁决后刀口）保留原语义与位置，不改。PRD §4.2 line 450 改写为：「夜晚可见 `private.tonight_kill_proposals`（本轮队友提案）、`kill_proposal_history`、`kill_vote_round`；裁决后可见 `tonight_kill_proposal`」。

## 6. 下游

| 模块 | 改动 |
|---|---|
| `agent/prompts.py` `build_wolf_night_prompt` | 「狼队私有」段改读新字段：列出本轮队友提案（`队友 3 号提议刀 8 号；队友 6 号提议空刀`）；**跟刀引导**（**终审修正**：规则句须按 `private.kill_rule` 分支，不得写死）：UNANIMOUS「狼队须全员一致才能出刀，否则空刀……请跟刀」/ MAJORITY「按相对多数裁决，并列即空刀……请向多数靠拢」/ RANDOM「在非空提案中加权随机选定……请跟刀以提高命中概率」；重提轮（`kill_vote_round>1`）追加：「第 k/N 轮：上一轮意见不一致（{分歧}），请统一意见」，末轮提示按规则（UNANIMOUS「仍不一致将空刀」/ MAJORITY「仍并列将空刀」；RANDOM 无重提轮）。`_render_observation` 的「局势」段排除这些收敛键（结构化段已单独呈现，避免原始 dict 重复）。删除失效的 `tonight_kill_proposal` 行（该字段在狼行动时恒空） |
| `agent/memory.py` | `_render` 给 `WOLF_KILL_REVOTE` 专用渲染（「狼队第 k 轮意见不一致：…，重新提案」）；`_SCORE_2` 加入该类型（与 `WOLF_KILL_PROPOSED` 同档） |
| `agent/decisions.py` | 不变（`WOLF_NIGHT` → `WolfDeliberation`） |
| `cli/bot.py` / `runtime/defaults.py` | 不变：重提轮 `expected_actors` 重新包含狼，bot 随机再提、超时默认仍是空刀/随机目标 |
| `cli/render.py` | `render_observation` 狼视角显示本轮队友提案与轮次；`render_event` 渲染 `WOLF_KILL_REVOTE`（GM 视角「[GM] 狼队第 k 轮意见不一致（0号→8号、1号→3号、6号→8号），重新提案」） |
| `cli/play.py` + `Makefile` + `README.md` | `--wolf-rule unanimous\|majority\|random`（映射到 `WolfKillRule`）、`--wolf-rounds N`；Makefile 变量 `WOLF_RULE` / `WOLF_ROUNDS` 并入命令片段；README「终端对局」与规则开关段落说明 |
| `api/rest.py` | 不变：`config_override` 已透传新键 |
| `schemas/actions.py` | 不变 |

LLM 成本：仅在狼队分歧时每狼多一次私有推理调用（默认最多 1 次重提）。

## 7. 测试（TDD；引擎测试零 IO、零 mock）

新增 `backend/tests/test_wolf_consensus.py`：
- 一致 → 一轮结束，无 `WOLF_KILL_REVOTE`，事件序列与 `rounds=1` 相同。
- 不一致（UNANIMOUS）→ 发 `WOLF_KILL_REVOTE(round_no=1, proposals=快照)`，`wolf_proposals` 清空、`wolf_kill_round==2`、`wolf_proposal_history` 含快照、狼重新进入 `expected_actors`；第二轮一致 → 出刀。
- 末轮仍不一致 → `WOLF_KILL_DECIDED(None)`，不再重提；`rounds=3` 时可重提两次。
- 全员空刀 → 不重提，直接空刀。
- `rounds=1` → 与现状一致（不一致直接空刀，无 REVOTE 事件）。
- `RANDOM_PROPOSAL` 有非空提案 → 不重提；`MAJORITY` 明确多数 → 不重提，并列 → 重提。
- `ROUND_STARTED` 重置轮次与历史。
- 回放保真：重提中途任意前缀 `reduce(events[:k])` 的 `wolf_proposals`/`wolf_kill_round`/`wolf_proposal_history` 与 live 相等。
- 配置校验：`wolf_consensus_rounds=0` 被拒。
- 整局终止性（bot，多预设多 seed）；`test_determinism` 与 500 局扫描回归。

隔离（`test_isolation.py` 补）：狼夜间 observation 含新字段且只含队友+自己；非狼 / 死狼 / 观众不含；`WOLF_KILL_REVOTE` 对非狼视角过滤（复用 `WOLF_KILL_PROPOSED` 的矩阵）。

Agent（`test_agent_prompts.py` 补）：狼夜 prompt 含队友提案与跟刀引导；重提轮含「上一轮」分歧与轮次；无提案时不含「队友…提议」；昼间 `build_prompt` 仍拿不到私有分区（既有测试）。`test_agent_memory.py` 补 REVOTE 渲染。

CLI（`test_cli_render.py` / `test_cli_smoke.py` 或新 `test_cli_args.py`）：`--wolf-rule`/`--wolf-rounds` 解析进 `GameConfig`；REVOTE 渲染非空可读；狼视角观察含提案行。

## 8. 明确不在范围

- 狼队自由文本夜间私聊（`private.wolf_chat`，PRD 预留）——另立 issue，待 M3 上帝视角可展示狼聊时做。
- 提案顺序轮换/头狼指定：runner 仍按座号驱动（最小座号狼先提，效果类似线下头狼）；先看真实对局效果。
- `MAJORITY` 并列时随机兜底的新规则值。
- 预设默认 `wolf_kill_rule` 改动。
