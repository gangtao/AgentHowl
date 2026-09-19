# AgentHowl 🐺

多智能体狼人杀（Werewolf）对局平台：每个座位既可以是 LLM Agent，也可以是真人，通过同一套玩家 API 接入。服务端规则引擎是唯一裁判，全部对局历史以事件溯源记录，可确定性重放。

## 当前状态

- ✅ **M1 — 规则引擎核心**（已完成）：纯函数引擎、事件溯源、四套标准板子、随机 bot 全自动对局与 500 局终止性扫描
- ✅ **M2 — API + Agent 接入**（[issue #25](https://github.com/gangtao/AgentHowl/issues/25)，已完成）：事件持久化、超时代打运行时、FastAPI REST/WS + token 认证、LiteLLM + instructor 的 Agent 层、端到端验收矩阵
- ✅ **终端观战/对局器**（[issue #44](https://github.com/gangtao/AgentHowl/issues/44)，已完成）：无需前端，在终端里看局或亲自玩一个座位（见下「终端对局」）
- 🚧 **M3 — 前端上帝视角**（[issue #26](https://github.com/gangtao/AgentHowl/issues/26)）：React 实时观战/回放，TS 侧与后端对齐的同一 `reduce()`

## 架构原则

1. **引擎纯函数、零 IO**（`backend/app/engine/`）：`step(state, action) -> (new_state, events)`，只依赖 stdlib + Pydantic；网络/DB/LLM 一律在外层（M2 的 `runtime/`）。
2. **事件溯源**：一切状态变更都是 append-only 事件，`state = reduce(events)`；实时状态与重放状态逐字段等价（测试钉死）。少数流程游标字段是文档化例外。
3. **服务端唯一事实来源**：客户端与 Agent 只提交意图（intent），从不自行裁决。
4. **信息隔离是服务端安全边界**：`observation.py` 按视角（座位/狼队/GM/观众）过滤事件与状态，前端零过滤。
5. **确定性随机**：所有随机经 `(seed, purpose, seq)` 的 SHA-256 派生（`rng.py`），同 seed 同操作序列 → 字节级相同的事件日志。
6. **规则不硬编码**：每个规则变体都是 `GameConfig` 开关。

## 目录结构

```
backend/
├── app/
│   ├── engine/            # ★ 纯逻辑，零 IO
│   │   ├── config.py      # GameConfig、角色/规则枚举、四套 presets
│   │   ├── state.py       # GameState / Player（frozen Pydantic）
│   │   ├── events.py      # 事件类型、typed payload、reduce()（唯一写路径）
│   │   ├── actions.py     # 玩家意图（夜间技能/发言/投票/上警/自爆…）
│   │   ├── phases.py      # 阶段状态机、竞选子阶段、expected_actors
│   │   ├── engine.py      # create_game / step / advance：校验→决策→发事件
│   │   ├── resolver.py    # 夜间串行结算、胜负判定、计票
│   │   ├── observation.py # 按视角构建观察（信息隔离）
│   │   └── rng.py         # 确定性随机派生
│   ├── store/             # M2.1 事件持久化（append-only；内存 + JSON 文件）
│   ├── runtime/           # M2.2 对局驱动、超时代打、连接管理、玩家端口
│   ├── api/               # M2.3 FastAPI REST + WebSocket + token 认证
│   ├── agent/             # M2.4 LLM Agent 层（LiteLLM + instructor、记忆、prompt）
│   ├── schemas/           # 请求/响应与工具调用模型
│   ├── main.py            # FastAPI 装配入口（uvicorn app.main:app）
│   └── cli/
│       ├── bot.py         # RandomBot + run_game：全自动对局驱动
│       ├── simulate.py    # 命令行模拟入口（胜负统计）
│       ├── render.py      # 终端叙述器：事件/观察 → 可读中文
│       ├── play.py        # 终端观战/对局入口（python -m app.cli.play）
│       └── play_human.py  # 交互玩局：mini-syntax + turn-loop
├── tests/                 # 380+ 测试：规则/隔离/确定性/API E2E/Agent/CLI
└── pyproject.toml
Makefile                   # 仓库根：dev/test/build/运行命令（make help）
docs/
├── specs/requirements.md  # ★ 权威设计文档（PRD + 技术设计，中文）
└── superpowers/           # 每个特性的设计 spec 与实施计划（开发记录）
```

## 快速开始

依赖 [uv](https://docs.astral.sh/uv/) 与 Python 3.11+。

**最简：从仓库根用 `make`**（各命令自动在 `backend/` 下经 uv 执行，无需手动 `cd`）：

```bash
make install     # 同步依赖
make watch       # 终端看一局（GM 视角叙述到终局）
make play SEAT=2 # 亲自玩 2 号座位
make check       # 全量质量门：lint + 格式 + 类型 + 测试
make help        # 查看全部命令
```

或直接用 uv（需先 `cd backend`）：

```bash
cd backend
uv sync

# 跑一局全 AI 对局（确定性：同 seed 结果恒同）
uv run python -m app.cli.simulate --preset std_9_kill_side --seed 42 --verbose

# 批量模拟 + 胜率统计（每局都校验重放一致性）
uv run python -m app.cli.simulate --preset std_12_yn_hunter_idiot --seed 1 --games 100
```

## 板子（presets）

| preset | 局型 | 配置要点 |
|---|---|---|
| `std_12_yn_hunter_idiot` | 标准 12 人预女猎白 | 4狼4民 + 预言家/女巫/猎人/白痴，屠边 |
| `std_12_yn_hunter_guard` | 标准 12 人预女猎守 | 白痴换守卫，夜序含守卫先行 |
| `std_9_kill_side` | 9 人屠边局 | 3狼3民 + 预女猎 |
| `std_9_kill_all` | 9 人屠城局 | 同上，胜负条件 KILL_ALL |

所有规则均为 `GameConfig` 开关：胜负条件、夜间行动顺序、发言方向（警长决定/固定）、平票规则（PK 后无放逐/PK 后随机）、狼刀决策（全员一致/相对多数/加权随机；意见不一致时可再开 `wolf_consensus_rounds` 轮统一意见）、女巫同夜双药与自救、守卫同守/奶穿、警长竞选（上警发言及其顺序、退水、警徽流、1.5 票权、自爆吞警徽）、遗言规则、狼人自刀/空刀等。

## 开发

仓库根的 `Makefile` 封装了全部常用命令（`make help` 查看）：

```bash
make check        # 全量质量门：lint + 格式 + 类型 + 测试（= 下面四条）
make test         # 全量测试（含确定性重放与 500 局终止性扫描）
make typecheck    # mypy 严格模式
make lint         # ruff 静态检查
make format       # ruff 自动格式化
make serve        # 启动 API 服务（uvicorn 热重载）
make smoke        # 真模型 smoke（需 AGENTHOWL_SMOKE_MODEL + Ollama）
```

等价的原始命令（`cd backend` 后）：

```bash
uv run pytest -q               # 全量测试
uv run mypy app                # 严格模式类型检查
uv run ruff check . && uv run ruff format --check .
```

约定（详见 `CLAUDE.md`）：

- 文档与注释用中文；代码标识符、API 名与 schema 用英文
- 规则引擎测试不依赖任何 IO 或 mock；确定性测试用固定 `GameConfig.seed`
- 新增事件类型必须登记 `EVENT_PAYLOAD_TYPES`（fail-loud tripwire 强制）

## 游戏逻辑要点

- 夜间行动窗口可并行开放，但按 `night_order` **串行结算**（女巫必须先看到狼刀结果）
- **狼刀优先**：夜间狼人达成胜利条件即刻终局，之后的毒/枪作废（可配置）
- 警长竞选完整子阶段机（上警 → 上警发言 → 退水确认 → 投票 → 方向决策 → 公布），上警发言顺序按法官「单顺双逆」经 seeded RNG 决定；全部子阶段边界经 `ELECTION_STAGE_CHANGED` 事件可从日志重建
- 狼人私聊与公开发言将使用分离的 LLM 调用（M2），私有推理不进公开上下文

## 文档

- **[docs/specs/requirements.md](docs/specs/requirements.md)** — 权威 PRD：GameConfig schema、阶段状态机、角色时序、Agent 工具契约、API 设计、里程碑
- **[docs/superpowers/specs/](docs/superpowers/specs/)** 与 **[plans/](docs/superpowers/plans/)** — 每个特性的设计文档与实施计划

## API 快速开始 / API Quick Start

后端提供统一玩家 API（真人与 LLM Agent 走同一套）。启动：

```bash
cd backend
uv run uvicorn app.main:app --reload   # http://localhost:8000
```

一局最小流程（`curl`；`$BASE=http://localhost:8000/api/v1`）：

```bash
# 1) 建局：9 人屠边预设，空位由 LLM Agent 填充（ai_model 省略则用内置随机 bot）
curl -s -X POST $BASE/games -H 'Content-Type: application/json' \
  -d '{"preset":"std_9_kill_side","config_override":{"seed":3},"ai_model":"ollama/llama3.1"}'
# → {game_id, host_token, spectator_token, config}

# 2) （可选）真人加入任意空座，拿 player_token 与 ws_url
curl -s -X POST $BASE/games/$GID/join -H 'Content-Type: application/json' \
  -d '{"display_name":"Alice","player_type":"HUMAN"}'
# → {player_token, seat, ws_url}

# 3) 开局（仅 host_token）：缺员座位按 ai_model 填充后起 runner
curl -s -X POST $BASE/games/$GID/start -H "Authorization: Bearer $HOST_TOKEN" \
  -H 'Content-Type: application/json' -d '{"fill_with_bots":true}'

# 4) 真人轮询自己的行动窗口（长轮询；204=暂未轮到）
curl -s "$BASE/games/$GID/my-turn?wait=5" -H "Authorization: Bearer $PLAYER_TOKEN"

# 5) 提交工具调用（§4.1 契约；actor_seat 一律取自 token，不接受 body 指定）
curl -s -X POST $BASE/games/$GID/actions -H "Authorization: Bearer $PLAYER_TOKEN" \
  -H 'Content-Type: application/json' -d '{"tool":"vote","arguments":{"target_seat":2}}'

# 6) 局终 GM 全量回放
curl -s $BASE/games/$GID/replay -H "Authorization: Bearer $SPECTATOR_TOKEN"
```

WebSocket（按视角推送过滤后事件流；断线可凭同 token + `from_seq` 重连补发）：

```
GET /api/v1/ws?token=<token>[&from_seq=<n>]
# server→client 帧：game_event / your_turn / phase_change / game_over
# client→server 帧：与 POST /actions 等价（同 schema 同信封）
```

真实模型冒烟与 token bench（默认跳过，需本地 Ollama）：

```bash
ollama pull llama3.1 && ollama serve &
AGENTHOWL_SMOKE_MODEL=ollama/llama3.1 uv run pytest -m smoke -q -s
```

## M2 验收矩阵（PRD §9）

| 判据 | 证据（测试） |
|---|---|
| 全 AI 完整对局经 API/WS（RandomBot） | `tests/test_api_e2e.py::test_acceptance_12_ai_full_game_via_api` |
| 全 **LLM Agent** 完整对局经 API/WS | `tests/test_acceptance_m25.py::test_all_agentplayer_game_via_http_ws` |
| 真人经同一玩家 API 顶替任意座位 | `tests/test_api_e2e.py::test_acceptance_human_can_take_any_seat`、`tests/test_api_ws.py::test_human_plays_whole_game_via_ws` |
| 超时代打，事件带 `meta.timeout=true` | `tests/test_game_runner.py::TestTimeoutAndRetry::test_hanging_port_replaced_by_default` |
| 断线重连 `from_seq` 补发一致 | `tests/test_api_e2e.py::test_acceptance_reconnect_restores_view` |
| 工具契约稳定 + instructor 校验重试 | `tests/test_schemas.py`、`tests/test_agent_llm_client.py::test_instructor_retries_on_invalid_then_valid` |
| 信息隔离（REST + 活 WS） | `tests/test_api_e2e.py::test_acceptance_isolation_matrix_via_api`、`tests/test_acceptance_m25.py::test_ws_isolation_matrix_wolf_villager_spectator` |
| 单局 LLM token 粗测 | `tests/test_agent_bench.py::test_single_game_token_bench`（env 门控） |

## 终端对局 / CLI Play

无需前端，直接在终端看局或玩局（进程内跑，无需起 server）。**从仓库根用 `make`**：

```bash
make watch                                     # 看一局 bot 对局（GM 视角叙述到终局）
make watch VIEW=spectator                      # 只看公开信息（拟真观战）
make watch SEED=3 ARGS=--step                  # 指定 seed + 回车逐步推进
make play SEAT=2                               # 亲自玩 2 号座位，其余内置 bot
make watch AI_MODEL=ollama/qwen2.5-coder:7b    # LLM 自对局（需 Ollama）
make watch AI_MODEL=ollama/qwen2.5-coder:7b WOLF_RULE=majority   # 狼刀相对多数即可
make watch WOLF_ROUNDS=3                                        # 狼队最多三轮统一意见
make watch AGENTS=agents.yaml            # 每座位独立模型/温度/thinking（见下方样例）
make sim GAMES=100                             # 纯引擎胜负统计（无叙述、极快）
```

玩局时轮到你，按提示输入：`speak 我怀疑3号` / `vote 3` / `vote abstain` / `night check 5` / `sheriff vote_sheriff 4` / `self_destruct` / `help`。

### 本地 LLM 模型选择

结构化输出对本地模型敏感。经实测（结构化决策成功率）：

- **快速可靠首选：`ollama/qwen2.5-coder:7b`**（结构化 JSON 稳、~4s/次；已实测跑通整局）。
- **推理模型（qwen3/qwen3.5 等）默认不可用**：它们在硬 JSON 模式下把内容写进思考通道、
  返回空 content 而解析失败。用 `THINKING=1` 开启思考模式（软 JSON 解析 + Ollama `think`），
  即可用其更强的推理，但**单次决策可达数分钟**、整局很慢：

```bash
make watch AI_MODEL=ollama/qwen3:8b THINKING=1
```

不开 `THINKING` 时对 Ollama 模型会显式传 `think=false`（这也修复推理模型的空 content 问题）。

等价的原始命令（`cd backend` 后，`python -m app.cli.play`）：

```bash
cd backend
uv run python -m app.cli.play --seed 3 --delay 0.6            # 看局
uv run python -m app.cli.play --view spectator                # 拟真观战
uv run python -m app.cli.play --seat 2                        # 玩 2 号座位
uv run python -m app.cli.play --ai-model ollama/llama3.1      # LLM 自对局
uv run python -m app.cli.simulate --games 100                 # 纯引擎胜负统计
```

### 每座位 Agent 档案 / Per-seat Agent Profiles

`--agents`（或 `make … AGENTS=`）指向一份 YAML，给每个座位独立配置 `model` /
`model_speech` / `reflection_model` / `thinking` / `temperature` / `name`（展示名）；
不带 `--agents` 时行为不变（全内置随机 bot）。查找规则：**座位号优先于 `"*"`**，
都没配的座位用内置随机 bot；`--ai-model` 等旧旋钮等价于 `agents["*"]`，与档案文件里
的 `"*"` 同时给出会报参数错误。开局会在终端打印一张座位档案表。

```yaml
# agents.yaml
seats:
  "0": { name: 老张, model: ollama/qwen2.5-coder:7b, thinking: false, skills: [seer-badge-flow, logic-chain],
         personality: {description: 老油条，话不多但每句都带钩子, traits: {多疑: 0.9, 冷静: 0.8}} }
  "3": { model: ollama/qwen3:8b, thinking: true, temperature: 0.7,
         personality: {preset: {system: MBTI, value: ENFP}, style_notes: 爱用感叹号} }
  "*": { model: ollama/qwen2.5-coder:7b }   # 其余座位的默认档案
```

```bash
make watch AGENTS=agents.yaml
```

### 人格 / Personality

每座位档案的 `personality` 字段（issue #57）给该座位的 Agent 配置任意性格特点，三层输入可任意
组合，翻译成系统 prompt 静态段的一句「你的性格：…」加若干行行为倾向句：

- `description`：自由文本描述，≤300 字，如「老油条，话不多但每句都带钩子」。
- `traits`：自定义特质词表，`词 → 0–1 强度`（<0.34 略微、<0.67 比较、≥0.67 非常）；内置
  狼人杀语境词表 15 个——多疑、冲动、谨慎、从众、好胜、冷静、健谈、沉默、固执、圆滑、直率、
  乐观、悲观、逻辑、感性；词表外的词按形容词原样纳入。
- `preset`：现成体系预设之一（MBTI 与 Big Five 地位相同），`{system: MBTI, value: ENFP}`
  （四字母代码）或 `{system: MBTI, value: {E: 0.8, N: 0.6, F: 0.5, P: 0.5}}`（逐轴强度）；
  Big Five 同理，`{system: BIG_FIVE, value: {O: 0.7, C: 0.3, E: 0.6, A: 0.5, N: 0.4}}`
  （键取 O/C/E/A/N）。
- `style_notes`：口头禅/语气，≤100 字，渲染为「说话风格：…」，与 description 同受护栏。

三层同时给出时按出现顺序即优先级（描述 > 特质 > 预设），相互冲突以先出现的描述为准；预设
展开用隐式写法，不会在 prompt 里出现「MBTI」「Big Five」等体系名。护栏：`description` /
`traits` 键 / `style_notes` 含越权或改规则短语（如「你知道谁是狼」「上帝视角」）建局即拒绝
（CLI 参数错误 / API 422）。人设只影响 Agent 的说话风格与判断偏好，不改变游戏规则，也不出现
在夜间私聊或反思 prompt 里——只在系统 prompt 的静态段生效。

```yaml
seats:
  "0": { model: ollama/qwen2.5-coder:7b, personality: {description: 老油条，话不多但每句都带钩子, traits: {多疑: 0.9}} }
  "3": { model: ollama/qwen3:8b, personality: {preset: {system: MBTI, value: ENFP}, style_notes: 爱用感叹号} }
```

### 技能包 / Skill packs

每座位档案的 `skills: list[str]` 字段（`"*"` = 全部内置/外部技能）给该座位的 Agent
挂载打包好的策略说明（`SKILL.md`）；未配 `skills` 的档案行为不变（现状零改动）。

内置库在 `backend/skills/<name>/SKILL.md`，文件格式兼容
[Agent Skills Specification](https://agentskills.io/specification)：

```yaml
---
name: seer-badge-flow          # 须与目录名一致，[a-z0-9-]
description: 预言家上警时如何报查验结果与警徽流…   # 系统 prompt 只列这一行
metadata:                      # 自定义扩展字段，规范要求全为字符串
  roles: "SEER"                # 空格分隔 RoleType；缺省 = 全部角色
  phases: "SHERIFF_ELECTION SHERIFF_PK DAY_SPEECH"  # 空格分隔 Phase；缺省 = 全部阶段
  priority: "10"                # 整数；同阶段多技能按此降序装配
---
正文：中文策略说明（触发条件 → 做法 → 反例/风险）。
```

装配是渐进式的两层披露：系统 prompt 只列已配技能的 `name: description`；每次决策再按
`(我的角色, 当前阶段)` 过滤、按 `priority` 降序排序、按字符预算（`AgentConfig.skill_budget_chars`，
默认 1800 字）整篇取舍后把正文装进指令段。狼人的夜间私有调用与白天公开发言调用各取各阶段
的技能，公私分离不变。

外部技能目录（同名覆盖内置）：

- CLI：`--skills-dir PATH`（或 `make watch SKILLS_DIR=path/to/dir`、`make play SKILLS_DIR=...`）
- API 服务：环境变量 `AGENTHOWL_SKILLS_DIR`

未知技能名建局即错（CLI 参数错误 / API 400），`--skills-dir` 指向不存在的目录同样是参数错误。

首批内置 14 篇：

| 技能 | 一句话 |
|---|---|
| `seer-badge-flow` | 预言家上警时如何报查验结果与警徽流，让警徽在死后仍能传递验人信息 |
| `seer-vs-claim-jump` | 真预言家遭遇悍跳对跳时，如何用查验与警徽流逻辑压制对方并归票 |
| `wolf-claim-jump` | 狼人悍跳预言家的时机、编造可信查验的原则与队友配合边界 |
| `wolf-counter-hook` | 狼人倒钩站真预言家、卖队友换信任的时机与后期反水节奏 |
| `wolf-charge` | 狼人冲锋为悍跳队友背书、带节奏归票好人的配合打法 |
| `wolf-lay-low` | 狼人划水降低存在感、跟票不出逻辑漏洞的保守打法 |
| `wolf-team-kill` | 狼人夜晚提议刀口目标的优先级与队伍一致行动原则 |
| `witch-potion-timing` | 女巫首夜救人、毒药留用与白天是否报银水的决策原则 |
| `hunter-shot-target` | 猎人开枪目标优先级，以及是否提前跳猎人身份的取舍 |
| `sheriff-herding` | 竞选警长的理由陈述、发言方向选择、归票与警徽移交策略 |
| `vote-discipline` | 白天投票与平票 PK 阶段的跟票、弃票与平票选择纪律 |
| `logic-chain` | 用发言前后矛盾、票型与金水查杀链交叉验证找出可疑玩家 |
| `side-taking` | 预言家对跳时如何比较可验证性、选边并处理改站边的代价 |
| `strategy-adaptation` | 按身份可能性动态切换防守（Support）与进攻（Attack）发言策略 |

## LLM 提供方配置 / LLM Providers

Agent 层用 **LiteLLM + instructor**（`app/agent/llm_client.py`），模型是一个
litellm 的 `provider/model` 字符串——任意 litellm 支持的提供方都能用（本地或云端），
代码里不硬编码提供方。**API key 由 litellm 从各提供方的标准环境变量读取**，本项目不
经手密钥；切换提供方 = 换模型字符串 + 设对应环境变量。默认模型 `ollama/llama3.1`。

模型字符串在四处配置（均为同一 litellm 字符串）：

| 入口 | 方式 |
|---|---|
| CLI | `--ai-model` / `--ai-model-speech` / `--reflection-model`（或 `make … AI_MODEL= AI_MODEL_SPEECH= REFLECTION_MODEL=`） |
| HTTP API | `POST /games` 的 `ai_model` / `ai_model_speech` |
| 代码 | `AgentConfig.model` / `model_speech` / `reflection_model` |
| 每座位档案 | `--agents agents.yaml` 的 `seats.<座位>.model`（或 API `agents`）；座位优先于 `*` |

常见提供方（模型字符串 + 环境变量）：

```bash
# 本地 Ollama（默认）；远程 Ollama 用 OLLAMA_API_BASE 指向主机
make watch AI_MODEL=ollama/qwen2.5-coder:7b
OLLAMA_API_BASE=http://gpu-host:11434 make watch AI_MODEL=ollama/qwen2.5-coder:7b

# OpenAI
OPENAI_API_KEY=sk-...        make watch AI_MODEL=openai/gpt-4o-mini
# Anthropic
ANTHROPIC_API_KEY=sk-ant-... make watch AI_MODEL=anthropic/claude-3-5-haiku-latest
# Gemini
GEMINI_API_KEY=...           make watch AI_MODEL=gemini/gemini-1.5-flash
# Groq
GROQ_API_KEY=...             make watch AI_MODEL=groq/llama-3.1-70b-versatile
```

**AWS Bedrock（Anthropic 模型）** 需额外装 `boto3`（可选依赖组）：

```bash
uv sync --extra bedrock          # 装 boto3（litellm bedrock 后端需要）；或 cd backend && uv add boto3

# 鉴权二选一：
# 方式 A（Bedrock API 令牌，推荐）—— litellm 读 AWS_BEARER_TOKEN_BEDROCK：
export AWS_BEARER_TOKEN_BEDROCK=<你的 bedrock api 令牌>  AWS_REGION_NAME=us-east-1
# 方式 B（IAM 长期/临时凭证，走标准链 环境变量 / ~/.aws / IAM 角色）：
export AWS_ACCESS_KEY_ID=...  AWS_SECRET_ACCESS_KEY=...  AWS_REGION_NAME=us-east-1  # 临时凭证再加 AWS_SESSION_TOKEN=...

# 模型串 = bedrock/<model-id>。新版 Claude 多为“推理配置文件”（inference profile），
# 需用带区域前缀的 ID（us./eu./apac.），而非裸 on-demand ID：
make watch AI_MODEL=bedrock/us.anthropic.claude-sonnet-4-5-20250929-v1:0
```

（本账号可用模型可用 `aws bedrock list-foundation-models --by-provider anthropic` 查。）

**分层路由**：`--ai-model-speech` 给白天发言单独用（可更强的）模型，`--reflection-model`
给每轮记忆反思用（通常更便宜的）模型；两者缺省都等同 `--ai-model`。例如便宜模型跑
夜间/投票、强模型只用于发言：

```bash
make watch AI_MODEL=ollama/qwen2.5-coder:7b AI_MODEL_SPEECH=anthropic/claude-3-5-sonnet-latest
```

**解析模式自适应**：支持函数调用的云模型走 instructor TOOLS 模式（结构化更稳）；本地
模型落 JSON 模式；`--thinking` 走 MD_JSON 软解析（见上「本地 LLM 模型选择」）。

> 说明：本地 Ollama 路径经完整实测（含整局）。Bedrock 路径已验证到「litellm 识别
> bedrock 提供方 + 选 TOOLS 模式 + boto3 就位 + 凭证成功到达 Bedrock API」，且 litellm
> 支持 `AWS_BEARER_TOKEN_BEDROCK` 令牌鉴权（源码确认）；均未跑真实推理计费验证。
> 其它云端提供方（OpenAI/Anthropic 直连/Gemini/Groq）走同一 litellm
> 路径、理论可用，同样尚未端到端跑通。`think` 参数仅对 `ollama/*` 生效，不影响云模型。

## License

[Apache 2.0](LICENSE)
