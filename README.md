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

## License

[Apache 2.0](LICENSE)
