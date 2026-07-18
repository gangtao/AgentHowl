# AgentHowl 🐺

多智能体狼人杀（Werewolf）对局平台：每个座位既可以是 LLM Agent，也可以是真人，通过同一套玩家 API 接入。服务端规则引擎是唯一裁判，全部对局历史以事件溯源记录，可确定性重放。

## 当前状态

- ✅ **M1 — 规则引擎核心**（已完成）：纯函数引擎、事件溯源、四套标准板子、随机 bot 全自动对局与 500 局终止性扫描
- 🚧 **M2 — API + Agent 接入**（[issue #25](https://github.com/gangtao/AgentHowl/issues/25)）：FastAPI REST/WS、事件持久化、超时代打、LiteLLM + instructor 的 Agent 层
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
│   └── cli/
│       ├── bot.py         # RandomBot + run_game：全自动对局驱动
│       └── simulate.py    # 命令行模拟入口
├── tests/                 # 190+ 测试：规则单测/隔离/确定性/500 局扫描
└── pyproject.toml
docs/
├── specs/requirements.md  # ★ 权威设计文档（PRD + 技术设计，中文）
└── superpowers/           # 每个特性的设计 spec 与实施计划（开发记录）
```

## 快速开始

依赖 [uv](https://docs.astral.sh/uv/) 与 Python 3.11+。

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

所有规则均为 `GameConfig` 开关：胜负条件、夜间行动顺序、发言方向（警长决定/固定）、平票规则（PK 后无放逐/PK 后随机）、狼刀决策（全员一致/相对多数/加权随机）、女巫同夜双药与自救、守卫同守/奶穿、警长竞选（退水、警徽流、1.5 票权、自爆吞警徽）、遗言规则、狼人自刀/空刀等。

## 开发

```bash
cd backend
uv run pytest -q               # 全量测试（含确定性重放与 500 局终止性扫描）
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
- 警长竞选完整子阶段机（上警 → 退水确认 → 投票 → 方向决策 → 公布），全部子阶段边界经 `ELECTION_STAGE_CHANGED` 事件可从日志重建
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

无需前端，直接在终端看局或玩局（进程内跑，无需起 server）：

```bash
cd backend

# 看局：全 bot 自对局，GM 视角逐事件叙述（--delay 控制节奏、--step 回车逐步）
uv run python -m app.cli.play --seed 3 --delay 0.6
uv run python -m app.cli.play --view spectator      # 只看公开信息（拟真观战）
uv run python -m app.cli.play --step                 # 回车逐步推进

# 玩局：你扮演 2 号座位，其余内置 bot 填充
uv run python -m app.cli.play --seat 2
#   轮到你时输入：speak 我怀疑3号 / vote 3 / vote abstain /
#   night check 5 / sheriff vote_sheriff 4 / self_destruct / help

# LLM 自对局（需本地 Ollama）：全座 LLM Agent，GM 视角围观
uv run python -m app.cli.play --ai-model ollama/llama3.1 --delay 0.3
```

纯引擎胜负统计（无叙述、极快）另见 `uv run python -m app.cli.simulate --games 100`。

## License

[Apache 2.0](LICENSE)
