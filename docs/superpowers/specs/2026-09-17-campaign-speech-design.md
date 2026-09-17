# 警长竞选上警发言子阶段 — 设计文档

> 日期：2026-09-17 · 状态：已批准 · 关联：GitHub issue #47 · 上游：`docs/specs/requirements.md` §3.1（line 86「上警玩家依次发言→可退水→警下投票」、line 88 警徽流）、§4.1（`speak.badge_flow`「仅预言家竞选时用」、`get_speeches.phase` 含 `SHERIFF_ELECTION`）

## 1. 背景与目标

PRD §3.1 规定竞选流程为「上警 → **依次发言** → 可退水 → 警下投票」。M1 把竞选发言列为简化项并挂到 M2（见 `pk-speech-design` §7、`withdraw-design`、`badge-flow-design`「M2 竞选发言落地后自然扩展」），M2 收尾时漏掉。后果：警下投票零信息；警徽流只有竞选平票（`SHERIFF_PK`）时才有机会声明；首日跳身份/悍跳无处发生。

本期补齐 **speech 子阶段**：候选人按法官定序依次公开发言，之后进入既有退水确认。

**交付判据**：
- 默认配置下竞选子阶段序列为 `candidacy → speech → withdraw → vote → direction → announce`，由 `ELECTION_STAGE_CHANGED` 完整可重建。
- 发言顺序按「单顺双逆」经 seeded RNG 决定，同 seed 可复现；`SEAT_ASC` 可选。
- 上警发言可携带合法警徽流并进入 `badge_flow_claims`。
- 发言中途态逐事件回放与 live 一致（`speech_order`/`speech_idx` 全程事件推导，不给 issue #37 添新债）。
- `campaign_speech_enabled=False` 时行为与本期之前完全一致。
- 超时代打、RandomBot、AgentPlayer、CLI 均能走通 speech 子阶段；全量套件、确定性、500 局扫描、mypy strict + ruff 全绿。

## 2. 规则依据（发言顺序）

线下法官惯例为「看时间单顺双逆」：法官取当前时间分钟尾数，单数则上警玩家按座号顺序发言，双数则逆序（例：1/4/5/7/8/12 上警，15:25 → 1→12 顺序；15:26 → 12→1 逆序）。本质是法官借一个与玩家无关的外部随机源，在「座号升序/降序」间二选一——**不是随机起始位**。引擎无钟表，且一切随机须走 seeded RNG（CLAUDE.md），故映射为 RNG 抽奇偶位。

退水时机：实战中「发言期间随时退水」与「发言结束后法官宣布退水时间」均合法。本期只做后者（与 PRD §3.1 原文一致，沿用既有 `withdraw` 子阶段）；前者见 §8。

## 3. 配置（`engine/config.py`，同步更新 PRD §3.2）

```python
class CampaignSpeechOrder(StrEnum):
    JUDGE_ODD_EVEN = "JUDGE_ODD_EVEN"  # 法官「单顺双逆」：RNG 抽奇偶，升序或降序
    SEAT_ASC = "SEAT_ASC"              # 固定座号升序（无随机对照/测试）

class SheriffRule(BaseModel):
    ...
    campaign_speech_enabled: bool = True
    campaign_speech_order: CampaignSpeechOrder = CampaignSpeechOrder.JUDGE_ODD_EVEN
```

`JUDGE_ODD_EVEN`：`rng.derive_int(seed=config.seed, purpose="campaign_speech_dir", seq=state.state_version, modulo=2)`；`0` → 候选人座号升序，`1` → 降序。与白天的 `SpeechOrderRule.ODD_EVEN_CLOCK`（按 `round` 奇偶，首日恒顺序）刻意区分：竞选发言只发生一次，须走 RNG 才有随机性，故独立枚举。

## 4. 状态机与事件契约

### 4.1 子阶段

`ElectionStage` 新增 `SPEECH = "speech"`。`_advance_election` 的 `candidacy` 收尾分支：

- 无候选人 → `_lose_badge(NO_CANDIDATES)`（不变，不进 speech）。
- `campaign_speech_enabled=True` → 计算发言顺序，发 `ELECTION_STAGE_CHANGED(stage=SPEECH, speech_order=order)`，返回等待发言。
- `campaign_speech_enabled=False` → 直接进 `withdraw`（现行为，事件序列逐字节不变）。

新增 `speech` 收尾分支（队列耗尽、`expected_actors` 为空时到达）：发 `ELECTION_STAGE_CHANGED(stage=WITHDRAW)` 并重置 `sheriff_confirmed`——即把现 `candidacy → withdraw` 的转移体抽成一个内部函数，两处共用。`withdraw` 及其后的全部分支不动。

### 4.2 事件

- `ElectionStageChangedPayload` 新增可选字段 `speech_order: tuple[int, ...] | None = None`。reduce：非 `None` 则一并写 `speech_order` 与 `speech_idx=0`（与 `PHASE_CHANGED.speech_order` 同语义）。旧持久化日志无该键 → 默认 `None`，向后兼容。
- 发言复用 `PLAYER_SPOKE`（PUBLIC）。既有 reduce 已推进 `speech_idx` 并记录 `badge_flow_claims`。**不新增事件类型**。
- 顺序在进入 speech 时一次算定并写入事件；回放只读事件、不重算 RNG。
- `/speeches?phase=SHERIFF_ELECTION`：端点按 `PHASE_CHANGED` 标注发言所属阶段，上警发言自动归入，无需改动。

## 5. 引擎校验（`engine/phases.py`、`engine/engine.py`）

- `expected_actors`：`SHERIFF_ELECTION` + `stage == "speech"` → `speech_idx < len(speech_order)` 时为 `{speech_order[speech_idx]}`，否则空集（触发 advance 进入 withdraw）。
- `_validate` 的 `Speak` 门：合法阶段增加「`SHERIFF_ELECTION` 且 `stage == speech` 且队列未耗尽」（记为 `campaign_speaking`）。其他竞选子阶段的 `Speak` 仍 `WRONG_PHASE`。BIDDING 拒绝不镜像到上警发言——其顺序由 `campaign_speech_order` 独立决定，与 `speech_order_rule` 无关。
- `_validate_sheriff` 的发言期守卫：竞选语境下**发言队列未耗尽时**（`campaign_speaking`，或 `SHERIFF_PK` 且 `speech_idx < len(speech_order)`），任何 `SheriffAction` → `WRONG_PHASE`。必要性：该函数末尾兜底分支对 `SHERIFF_ELECTION/SHERIFF_PK` 一律接受 `VOTE_SHERIFF`，而当前发言者恰在 `expected_actors` 内——不加守卫则发言者可在发言期投票。`SHERIFF_PK` 发言期的同一口子是**既有漏洞**（平票候选人可在自己发言轮次投票并计入票型），由同一道守卫一并修复，补回归测试。
- `badge_flow` 合法语境：`SHERIFF_PK 发言回合` → `SHERIFF_PK 发言回合 或 campaign_speaking`。结构校验（开关、长度、去重、存活目标）不变；不验角色真伪（悍跳合法）。
- 自爆：`_validate_self_destruct` 对 `SHERIFF_ELECTION` 全程放行、不经 `expected_actors`，speech 子阶段自爆走既有「吞警徽 + 立即天黑」路径，代码不改、补测试。残留的 `speech_order`/`speech_idx` 无害：后续每个发言型阶段入口都经事件重置队列。

## 6. 下游适配（observation schema 不变；`election_stage` 已在观察内）

| 模块 | 改动 |
|---|---|
| `runtime/defaults.py` | `stage == SPEECH` → `Speak(content=TIMEOUT_SPEECH)`。现状会落入 vote 分支产出被引擎拒绝的 `VOTE_SHERIFF`，必须修 |
| `runtime/game_runner.py` | `_speech_window` 须把上警发言计为发言型窗口（取 `speech_timeout_sec` 而非 `action_timeout_sec`）。**终审补记**：本表初稿按「谁按竞选子阶段分支」枚举，漏了这个按「是否发言窗口」分支的模块；根因是发言队列谓词多处手写，已收敛为 `phases.pk_speaking` / `phases.speech_queue_pending` 供校验、默认行动、bot、runner 共用 |
| `agent/memory.py` | `_render` 为 `ELECTION_STAGE_CHANGED` 加专用渲染（终审补记；不用全局 `exclude_none`，以免丢掉弃票 `target=None` 等有语义的 None） |
| `cli/bot.py` | speech 子阶段随机发言；1/4 概率附带合法警徽流。把 PK 发言分支里的警徽流生成抽成局部 helper 共用 |
| `agent/decisions.py` | `SHERIFF_ELECTION` 且 `obs.election_stage == "speech"` → `DecisionKind.SPEECH`；其余子阶段仍 `SHERIFF` |
| `agent/prompts.py` | 警徽流字段开放条件由「phase ∈ {SHERIFF_PK}」改为「SHERIFF_PK 或 (SHERIFF_ELECTION 且 stage=speech)」；新增上警发言引导语（竞选理由、可声称身份、预言家报查验与警徽流）。狼人公开发言沿用既有昼间装配签名隔离，私有分区不入 prompt |
| `schemas/actions.py` | `available_tools_for`：speech 子阶段返回 `("speak", "self_destruct", *只读)`，不再提示 `sheriff_action` |
| `cli/render.py` | `ELECTION_STAGE_CHANGED` 携 `speech_order` 时输出「上警发言顺序：…」；`PLAYER_SPOKE` 渲染不变 |
| `cli/play_human.py` | 无需改：`speak` 指令已存在；提示来自 `available_tools_for` |

LLM 成本：首日新增 k 次发言调用（k=候选人数），走既有 speech 模型路由。

## 7. 测试（TDD；引擎测试零 IO、零 mock）

新增 `backend/tests/test_campaign_speech.py`：
- 子阶段序列：默认配置下时间线为 `candidacy, speech, withdraw, vote, …`；`speech` 事件携带的 `speech_order` 恰为候选人集合的一个排列。
- 顺序规则：`SEAT_ASC` 恒升序；`JUDGE_ODD_EVEN` 在一组 seed 上升序与降序**均出现**，且同 seed 两次运行一致。
- 发言流：`expected_actors` 依次为各候选人；全部发完后 stage 变 `withdraw`，退水/投票照旧。
- 拒绝矩阵：非当前发言者 `Speak` → `NOT_YOUR_TURN`；警下玩家 `Speak` → `NOT_YOUR_TURN`；当前发言者在 speech 期间提交 `RUN_FOR_SHERIFF`/`WITHDRAW`/`VOTE_SHERIFF` → `WRONG_PHASE`（其他人 → `NOT_YOUR_TURN`）；`withdraw`/`vote` 子阶段 `Speak` → `WRONG_PHASE`。
- 既有漏洞回归（加在 `test_pk_speech.py`）：`SHERIFF_PK` 发言期当前发言者 `VOTE_SHERIFF` → `WRONG_PHASE`，`sheriff_votes` 保持为空。
- 警徽流：上警发言携合法警徽流 → 接受且写入 `badge_flow_claims`；超长/重复/死目标 → `BADGE_FLOW_INVALID`；`badge_flow_enabled=False` → 拒。
- 开关关闭：`campaign_speech_enabled=False` 时时间线无 `speech`，candidacy 后直达 withdraw。
- 自爆：speech 中途狼自爆 → `SHERIFF_BADGE_LOST(SELF_DESTRUCT)` + 立即天黑。
- 回放保真：发言进行到一半时，`reduce(events[:k])` 的 `election_stage`/`speech_order`/`speech_idx`/`badge_flow_claims` 与 live 逐字段相等。

既有测试适配：默认行为变化会打断逐步驱动竞选的用例（`test_sheriff`/`test_withdraw`/`test_pk_speech`/`test_badge_lost`/`test_election_timeline`/`test_speech_direction`/`test_self_destruct_skip` 等）。在 `tests/factories.py` 加 `run_campaign_speeches(state)` 辅助（循环让 `expected_actors` 发言直到 stage 离开 `speech`），在这些用例的 candidacy 之后调用——**不**靠全局关开关回避，保证默认路径被既有用例一并覆盖。

其余：`test_runtime_defaults`（speech 超时 → 空发言）、`test_agent_decisions`（speech 子阶段 → SPEECH）、`test_agent_prompts`（警徽流字段开放 + 引导语；狼人上警发言 prompt 不含私有分区）、`test_schemas`（工具提示）、`test_cli_render`（顺序行）。回归：确定性、500 局扫描（bot 真实走上警发言）、API E2E、隔离矩阵。

## 8. 明确不在范围

- 发言期间随时退水（规则上合法；后续 issue，届时 `SheriffRule` 加退水时机开关）。
- 警下玩家在竞选期发言。
- `speech_order_rule=BIDDING`。
- 狼队刀口共识（issue #46）。
- 其余竞选游标（`sheriff_confirmed`、PK 收窄的 `sheriff_candidates`）的事件化（issue #37）——本期不恶化、不修复。
