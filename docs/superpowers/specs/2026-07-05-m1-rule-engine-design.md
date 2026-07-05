# M1 规则引擎核心 — 设计文档

> 日期：2026-07-05 · 状态：已批准 · 上游规格：`docs/specs/requirements.md`（§3、§6.4、§8.4、§9-M1）

## 1. 目标与交付判据

实现 AgentHowl 的规则引擎核心（M1）：纯函数引擎、`GameConfig`/presets、阶段状态机、事件溯源与 `reduce`、信息隔离 observation，以及一个用脚本 bot 跑完整对局的 CLI。

**交付判据**（与上游规格 §9-M1 一致）：
- 规格 §8.4 的规则单元测试全部通过；
- 确定性重放通过：固定 `seed` 时两次运行产生完全相同的事件日志，且 `reduce(events)` 与实时状态一致；
- CLI 可用随机 bot 跑完多局（多 seed），每局必然终局且有胜负（或达 `max_rounds` 判平局）。

## 2. 核心架构决策

### 2.1 事件是唯一写路径（已选方案 A）

`step(state, action)` 内部流程固定为：**校验 → 决定事件 → `reduce` 应用事件**。状态只能经 `reduce(state, event)` 变更，不存在第二条写路径。因此"直播即回放"由结构保证而非测试保证；前端未来的 TypeScript `reduce()` 只需镜像这一个函数。

备选方案 B（state-first + 事件日志）因存在双写路径漂移风险被否决；方案 C（`eventsourcing` 库）因依赖过重、抽象泄漏被否决。

### 2.2 自实现阶段机（不引入 python-statemachine）

`Phase` 为普通枚举，转移逻辑是纯函数。理由：零额外依赖；phase 只是 `GameState` 上的一个字段，天然可序列化、可由 `reduce` 重建；库的实例/回调生命周期与纯函数模型不契合。

### 2.3 无隐藏状态的确定性随机

`rng.py` 把每次随机抽取实现为 `(seed, purpose, seq)` 的纯函数（哈希派生），用于发牌与平票随机。抽取结果是事件序列位置的确定函数，重放自然复现；`GameState.rng_state` 退化为一个计数器。

## 3. 模块布局

引擎为纯包，只 import 标准库与 Pydantic：

```
backend/app/engine/
├── config.py       # GameConfig + 子规则模型 + 4 个 preset + validate_config()
├── state.py        # GameState, Player, NightActions（frozen Pydantic 模型）
├── events.py       # EventType 枚举, Event 模型, Visibility, reduce()
├── actions.py      # 行动意图模型（night_action / vote / speak / sheriff_action 一一对应工具 schema）
├── phases.py       # Phase 枚举 + 转移逻辑（expected_actors、下一阶段推导）
├── engine.py       # step(state, action) -> StepResult(new_state, events, rejection)
├── resolver.py     # resolve_night() / count_votes() / check_win() 纯函数
├── rng.py          # 确定性随机派生
└── observation.py  # build_observation(state, seat) + visible_events() 可见性过滤
```

CLI 与 bot 在引擎包之外：`backend/app/cli/`（simulate 入口 + RandomBot）。测试在 `backend/tests/`。

## 4. 数据模型要点

- `GameConfig` 及子规则（`WitchRule`/`GuardRule`/`SheriffRule` 等）与 presets 严格按规格 §3.2 实现；`validate_config()` 校验人数、night_order 角色、胜利条件相容性。
- `GameState`/`Player`/`Event` 均为 frozen Pydantic 模型；`reduce` 用 `model_copy(update=...)` 返回副本，纯度由类型系统强制。
- `Event` 字段照规格 §6.4：`seq, game_id, ts, type, actor_seat, payload, visibility, meta`。纯引擎内 `ts` 是逻辑 tick，墙钟时间由 runtime（M2）写入 `meta`，保证确定性与真实时间无关。
- 事件 payload 按 `EventType` 定义为类型化模型（非自由 dict），reducer 与测试受 mypy strict 检查。
- **狼人共识**：每只存活狼在 `NIGHT_WEREWOLF` 提交 `kill(target)`；全员一致 → 刀该目标，任何分歧或明确 skip → 空刀（规格默认"意见不统一视为空刀"）。提案事件 `WOLF_KILL_PROPOSED`（`WOLVES` 可见），决定事件 `WOLF_KILL_DECIDED`（`GM_ONLY`）。
- 发言内容对引擎不透明，原样存入 `PLAYER_SPOKE`；`claim_role`/`badge_flow` 作为 payload 透传（供 M2+ 的 agent 与前端使用）。

## 5. 阶段机与流程

`Phase` 枚举照规格 §3.3 清单。两个纯函数承载转移：`expected_actors(state) -> set[seat]`（当前谁可行动）与 `step` 内的自动推进循环 —— 应用玩家行动后，引擎持续产出系统事件（`PHASE_CHANGED`、`NIGHT_RESOLVED`、`DEATH_ANNOUNCED`、`VOTE_RESULT`、`GAME_OVER`…）直到抵达需要玩家输入的阶段。runtime/CLI 永不裁决规则，只路由"该谁行动"。

- **夜晚**：子阶段按 `config.night_order` 依序（配置中不存在的角色跳过；相应角色已死时自动跳过并写 `GM_ONLY` 跳过事件）。规格的"并行开窗、串行结算"在引擎内表现为严格串行的阶段序；并行开窗是 M2 runtime 的职责。女巫的刀口信息只在 `WOLF_KILL_DECIDED` 之后注入其 observation，从结构上满足"女巫必须在狼之后"。
- **夜晚结算**：实现规格 §3.3 伪代码 —— 守卫挡刀不挡毒；同守同救按 `guard_plus_antidote_cancels` 判死；结算后立即 `WIN_CHECK`。**狼刀在先**：狼已达成胜利条件则直接终局，女巫毒/猎人枪一律无效。
- **首日**：`SHERIFF_ELECTION` 在 `DEATH_ANNOUNCE` 之前（上警 → 竞选发言 → 可退水（失投票权）→ 警下投票 → 平票 `SHERIFF_PK` → 再平票警徽流失）。
- **自爆**：`actions.py` 中的独立行动类型 `self_destruct`（仅存活狼人、白天发言/竞选阶段可用）。效果：身份公开、立即出局、跳过当天剩余发言与投票直接入夜；发生在竞选期则按 `wolf_selfdestruct_eats_badge` 吞警徽。
- **遗言**：按 `LastWordsRule` 判定 —— 默认仅首夜死者有夜间遗言；白天被票/技能出局者始终有遗言。
- **投票 → 放逐**：警长 1.5 票；白痴翻牌后投票作废；平票 → `VOTE_PK`（平票者发言、其余人投）→ 再平票按 `TieRule`。被放逐者是猎人 → `HUNTER_SHOOT`（被毒不可开枪）；是白痴 → `IDIOT_FLIP`（免死、失投票权、当天投票作废、直接入夜）。
- 达到 `max_rounds` → `GAME_OVER` 且 `winner=None`（平局），模拟不可能死循环。

## 6. 信息隔离（安全边界）

`observation.py` 提供两个函数，直播与回放共用，此外别无过滤点：
- `build_observation(state, seat) -> PlayerObservation`：按规格 §4.2 注入角色专属 `private`（狼队友/狼聊、预言家验人记录、女巫药态与刀口、守卫上次守护、猎人可否开枪）。解药用完且 `knows_kill_after_antidote_used=False` 时不再注入 `tonight_killed_seat`；死者不再收到夜间私有信息。
- `visible_events(events, viewer) -> list[Event]`：viewer 为某 seat、`SPECTATOR` 或 `GM`，按 `Visibility` 过滤。

## 7. 错误处理

- 非法意图（越权、时机不对、目标已死、连守同一人等）→ `StepResult` 携带类型化 `RejectedReason` 枚举，状态不变、不产生事件。
- 引擎不变量被破坏（不可能状态）→ 抛 `EngineInvariantError`，绝不静默继续。

## 8. CLI 与脚本 bot

`uv run python -m app.cli.simulate --preset std_12_yn_hunter_idiot --seed 42 [--games N] [--verbose]`

- `RandomBot`：在合法行动集合内均匀随机选择，随机源由（对局 seed + seat）派生，全程确定。
- 主循环：读 `state.current_actors` → 向 bot 要行动 → `step()` → 打印公开事件；终局时校验 `reduce(全部事件)` 与最终状态一致并打印胜方。
- `--games 500`：多 seed 扫描，断言每局都终止且有结果。

**有意推迟项**：`speech_order_rule=BIDDING`（Werewolf Arena 竞价发言）在 M1 只接受配置但返回拒绝（`BIDDING_NOT_IMPLEMENTED`），M2 有真实 agent 后再实现。其余发言顺序规则 M1 全部交付。

## 9. 测试策略（对应规格 §8.4）

全部引擎测试零 IO、零 mock：

| 文件 | 覆盖 |
|---|---|
| `test_config.py` | preset 校验、`validate_config()` 失败用例 |
| `test_night_resolution.py` | 结算矩阵：守+刀、救+刀、同守同救、毒穿守、空刀/自刀、女巫同夜单药、首夜自救开关 |
| `test_wolf_first.py` | 狼刀在先：达成条件后毒/枪无效 |
| `test_hunter.py` | 开枪可用性（被毒不可、被票可）、枪杀时序 |
| `test_idiot.py` | 翻牌免死一次、失投票权、当天投票作废 |
| `test_sheriff.py` | 竞选、PK、再平票警徽流失、自爆吞警徽、1.5 票、移交/撕警徽 |
| `test_last_words.py` | 首夜有/之后无/白天始终有 |
| `test_win_conditions.py` | 屠边两侧、屠城、放逐光狼 |
| `test_isolation.py` | 非狼 observation 无 `teammates`/`wolf_chat`；私有字段仅本人可见；解药用尽后无刀口；每种事件类型的可见性过滤 |
| `test_determinism.py` | 同 seed 两次运行事件日志逐字节一致；`reduce(events)` == 实时终态 |
| `test_sim_game.py` | 随机 bot 多 seed 完整对局：必终局、必有结果、回放一致 |

## 10. M1 内部分期（每期测试全绿并提交后进入下一期）

1. **核心循环**：config/state/events/reduce + 夜晚（守/狼/女巫/预言家）+ 白天发言/投票/放逐 + 胜负判定 + RandomBot + CLI（暂用无猎人/白痴的测试配置）。
2. **角色补全**：猎人（首夜确认/开枪）、白痴（翻牌）、遗言规则，四个 preset 全绿。
3. **警长层**：竞选、PK、警徽流字段、自爆、1.5 票、发言顺序规则。
4. **加固**：隔离测试、确定性测试、500 局模拟扫描、mypy strict 与 ruff 全干净。

## 11. 明确不在 M1 范围

- 任何 IO：网络、数据库、LLM 调用（M2 的 runtime/agent/api 层）。
- 竞价发言 BIDDING 的实际逻辑（M2）。
- 前端 TypeScript `reduce()`（M3+，但本设计的事件契约是其唯一依据）。
- 情侣/丘比特、白狼王、骑士等扩展角色（规格中标注为预留）。
