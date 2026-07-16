# agent 层设计 —— 内置 LLM AgentPlayer（issue #31，M2.4）

日期：2026-07-16
关联：issue #31（父 issue #25，PRD §4.4 / §8.3）
前置：#28 store、#29 runtime、#30 api（均已入 main，55026f4）

## 目标

实现 `backend/app/agent/`：让任意座位可由 LLM Agent 扮演。Agent 是"诚实观察者"——
只依据 `PlayerObservation` 与自己订阅到的**可见事件**决策，绝不触碰引擎状态；
经与真人/bot 完全相同的 `PlayerPort.act(observation, deadline_ts)` 缝隙接入 runner。
LLM 层模型无关（LiteLLM + instructor），默认本地 Ollama，零 API key 可跑。

## 决策摘要

| 决策点 | 结论 |
|---|---|
| 默认 LLM 提供方 | Ollama 本地（默认 `ollama/llama3.1`）：免费、离线可开发；弱工具调用靠 instructor JSON 校验+重试兜底 |
| Agent 接入方式 | 进程内 port：`AgentPlayerPort` 实现 `PlayerPort`，registry 注入 AI 座位；不走 HTTP 自连 |
| 真模型测试口径 | env 门控 pytest：`AGENTHOWL_SMOKE_MODEL` 未设或端点不通即 skip；CI/单测全用 mock `LLMClient` |
| 狼夜间私聊范围 | 单次私有推理 LLM 调用（非多轮群聊）：产出只用于夜间行动 + 存入 `night_private` 记忆分区；不新增引擎事件类型（多轮狼聊留待后续 issue） |
| Completeness 问答 | 并入每轮反思调用（L=5 预置 + M=2 自问，直接从短期记忆作答），不引入 Sentence-BERT（PRD §4.4.2 初版口径） |

## 模块划分（`backend/app/agent/`）

### llm_client.py
- `LLMClient(Protocol)`：
  `complete_structured(system_prompt, user_prompt, response_model, model, temperature=0.3) -> BaseModel`。
  相对 PRD §4.4.3 签名**去掉冗余 `tools_schema` 参数**（schema 已由
  `response_model` 携带并渲染进 instruction 段）——规格偏差在此声明。
- `LiteLLMInstructorClient`：`instructor.from_litellm(litellm.completion)` 包装；
  按模型选 mode：`litellm.supports_function_calling(model)` → TOOLS，否则 JSON
  （Ollama 走 JSON mode，instructor 负责 Pydantic 校验 + 失败重试，默认
  `max_retries=2`）。
- 新增生产依赖：`litellm`、`instructor`。

### decisions.py
- 各阶段 LLM 必须填充的 Pydantic 响应模型（皆含 `reasoning: str` 先行字段，
  引导 CoT）：
  - `NightDecision{reasoning, action_type, target_seat: int | None}`
  - `SpeechDecision{reasoning, content, claim_role: RoleName | None, badge_flow: list[int]}`
  - `VoteDecision{reasoning, target_seat: int | None, abstain: bool}`
  - `SheriffDecision{reasoning, action_type, target_seat: int | None, direction: Direction | None}`
  - `WolfDeliberation{analysis, proposed_target: int}`（夜间私有推理专用）
- decision → 引擎 `Action` 的纯函数映射（复用 `app.engine.actions` 构造器；
  非法值由引擎裁决 → runner 既有 MAX_REJECTIONS 重试兜底）。

### prompts.py —— 三段式（PRD §4.4.1）
1. **静态段**（system prompt，可整段缓存）：游戏规则 + 本局 config 要点
   （角色表、警长开关等）+ 该座位角色说明与阵营目标。中文。
2. **动态段**：当前 observation 摘要（阶段/轮次/存活/警长/自身私有信息）+
   记忆上下文（见 memory.py）。
3. **指令段**：本次决策类型说明 + 响应模型字段说明 + 反幻觉自检问句
   （"当前是什么阶段？你的角色是什么？"）+ 候选座位列表。
- **候选列表顺序随机化**（抗位置偏置）：`random.Random(hash((agent_seed, seat,
  state_version)))` 洗牌，确定性可复现。
- **公私分离结构保证**：装配发言/投票 prompt 的函数**签名上拿不到**
  `night_private` 分区（类型层面隔离），并有单测断言昼间 prompt 文本
  永不含夜间私有推理内容。

### memory.py —— PRD §4.4.2 "三件套"
- `AgentMemory`：条目从**订阅到的可见事件**摄入（registry 把 memory 以
  viewer=seat 订到 `ConnectionManager`，与远端玩家所见完全一致）。
- 条目结构：`{round, phase, kind, text, score, private: bool}`；
  `night_private` 分区单列。
- **Freshness**：最近 K=15 条原文保留。
- **Informativeness** 规则打分：5=自身身份/查验结果；4=死亡事件；
  3=身份声称/警徽流；2=用药/守护等私有行动；1=其它。窗口外按分取 top-N。
- **反思**：观察到新 `ROUND_STARTED` 时，对上一轮做一次廉价 LLM 总结调用，
  同一调用内回答 Completeness 问句（L=5 预置——含"你的角色/当前阶段/谁死了/
  谁跳了什么/你的目标"，M=2 自问自答）。反思失败仅告警降级（保留原始条目），
  不影响行动。
- `build_context(seat) -> str`：新鲜窗口 + 高分补充 + 反思摘要拼接，供动态段。

### agent_player.py
- `AgentPlayerPort(seat, config: AgentConfig, client: LLMClient, memory)`，实现
  `PlayerPort`：
  1. `act(observation, deadline_ts)`：按 `observation.phase`（镜像 bot 的分支法）
     选决策类型 → 装配 prompt → `complete_structured` → decision → Action。
  2. **狼夜（NIGHT_WEREWOLF）两段式**：先私有推理调用（上下文含队友、击杀史、
     `private` 字段）→ 产出存 `night_private` 分区 → 提议目标转 `NightAction`。
     白天发言是**独立调用**，上下文=公开记忆+自身身份事实，结构上无法引用
     夜间推理文本（CLAUDE.md 硬约束落点）。
  3. **超时安全边际**：`deadline_ts - now < margin`（默认 2s）时不再发起 LLM
     调用，直接抛 `TimeoutError`；LLM 任何异常同样上抛——**runner 既有
     异常→默认行动兜底负责活性**，agent 内零兜底逻辑（单一责任）。
  4. 一个 port 同时至多一个未决 `act`（沿用 #30 终审口径，无流水线）。
- `AgentConfig`：`model`（默认 `ollama/llama3.1`）、`model_speech: str | None`
  （None→同 model；§8.3 分层路由的落点）、`reflection_model: str | None`
  （None→同 model）、`temperature=0.3`、`agent_seed: int`（默认取
  GameConfig.seed 派生）、`deadline_margin_s=2.0`。

### 接线（registry / schemas 增量）
- `CreateGameRequest` 增 `ai_model: str | None = None`、
  `ai_model_speech: str | None = None`：
  - `ai_model=None` → AI 座位照旧填 `BotPlayerPort`（现有测试与快速对局零变化）。
  - `ai_model` 设置 → `start(fill_with_bots=True)` 时空座位注入
    `AgentPlayerPort`，registry 同时把各 agent 的 memory 订到
    `ConnectionManager(viewer=seat)`。
- runner / engine / store **零改动**（唯一例外：若实现中发现 observation 缺
  agent 必需字段，走引擎小 PR 单独评审）。

## 硬约束（复述自 CLAUDE.md / issue #31）

- 狼私聊与公开发言必须是**分开的 LLM 调用**，私有推理永不入昼间 prompt
- agent 只经 observation/可见事件决策——不 import engine.state 读全量状态
- engine 不 import agent；agent 可 import engine（类型）/schemas，不 import api
- LLM 失败的活性兜底 = runner 默认行动机制，agent 不自造兜底

## 测试策略

1. **单测（mock LLMClient，零网络）**：
   - prompt 装配：静态段含正确角色；候选洗牌确定性；指令段含响应 schema 说明
   - **私泄断言**：狼座写入 night_private 后，装配全部昼间 prompt，断言
     文本不含私有推理串（关键隔离测试）
   - memory：K=15 窗口、打分 top-N、反思摘要注入、反思失败降级
   - decision→Action 映射：各阶段合法映射被引擎接受（复用扫描式窗口探针）
   - instructor 重试路径：mock 先回非法后回合法 → 最终成功
2. **集成（scripted mock，真 runner）**：9 座全 `AgentPlayerPort`（mock 客户端
   按脚本决策）跑到 GAME_OVER；memory 确有摄入；一例 mock 抛异常 → 该窗口
   落默认行动、对局继续。
3. **Smoke（`-m smoke`，env 门控）**：`AGENTHOWL_SMOKE_MODEL` 已设且 Ollama
   端点可达才跑；一次真实夜间行动 + 一次真实发言经完整 AgentPlayerPort。
   `smoke` marker 注册进 pyproject 并默认 deselect。
4. 质量门：`uv run pytest`、`uv run mypy app`（strict）、`uv run ruff check .`、
   `uv run ruff format --check .`。

## 明确不做（YAGNI）

- 多轮狼人夜间群聊事件（需新引擎事件类型，另立 issue）
- Sentence-BERT / 向量检索记忆（PRD 初版口径明确排除）
- prompt 缓存计费优化、token 预算硬闸（§8.3 全量落地留 M3+；本期仅以
  分层模型字段留出路由落点）
- AFK 真人座 AI 接管；HTTP 自连型 agent 进程（进程内 port 已覆盖 M2 验收）
- 前端 agent 观测 UI（M3）
