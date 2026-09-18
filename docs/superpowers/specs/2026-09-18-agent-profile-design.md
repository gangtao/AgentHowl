# AgentProfile：每座位独立配置的 Agent（契约与装配）— 设计文档

> 日期：2026-09-18 · 状态：已批准 · 关联：GitHub issue #56（子 issue #57 人格、#58 技能包、#59 跨局记忆、#60 档案评估）· 上游：`docs/specs/requirements.md` §5.2（建局请求）、§8.3（分层路由）；agent 层规格 `2026-07-16-agent-layer-design.md`

## 1. 背景与目标

内置 `AgentPlayerPort` 的配置目前是**全局一份**：建局只有 `ai_model` / `ai_model_speech`（CLI 另有 `--reflection-model` / `--thinking`），所有 AI 座位共用；`AgentConfig` 每座位一个实例但内容相同；bot 座位名固定 `Bot{seat}`（API）/ `P{i}`（CLI）。

目标：每个座位成为**独立配置的 Agent**——本期做基础契约与装配层（模型路由一组字段），人格 / 技能包 / 跨局记忆各自的 issue 落地时**增量**加字段，契约不破坏。

**交付判据**：
- 同一局里不同座位可配不同 `model` / `model_speech` / `reflection_model` / `thinking` / `temperature` / 展示名；各座位 LLM 调用参数正确。
- 旧入口（API `ai_model` / `ai_model_speech`、CLI `--ai-model` 等）行为不变，等价于 `"*"` 默认档案。
- API 建局回显解析后的档案映射；CLI 开局打印座位档案表；键名笔误/越界座位/冲突配置 fail-loud（400 / argparse 错误）。
- 确定性不变（`agent_seed` 仍取 `GameConfig.seed`；候选洗牌本已按座位区分）。

## 2. 档案 schema（新文件 `backend/app/agent/profile.py`）

```python
class AgentProfile(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")  # 键名笔误 fail-loud
    name: str | None = None            # 展示名（roster display_name）；缺省 Bot{seat}（终审补记：去首尾空白，空串归一为 None）
    model: str
    model_speech: str | None = None    # 发言层模型（None=同 model）
    reflection_model: str | None = None
    thinking: bool = False
    temperature: float = Field(default=0.3, ge=0.0, le=2.0)

AgentProfiles = dict[str, AgentProfile]   # 键：座位号字符串（"0".."N-1"）或 "*"
```

- **查找规则** `profile_for(agents, seat) -> AgentProfile | None`：先 `str(seat)`，再 `"*"`，都无则 `None`（该座位用 RandomBot）。
- **校验** `validate_profiles(agents, num_players)`：键只能是 `"*"` 或 `0..num_players-1` 的十进制整数字符串，否则 `ValueError`（API → 400，CLI → 参数错误）。
- `to_agent_config(profile, game_config) -> AgentConfig`：`model` / `model_speech` / `reflection_model` / `thinking` / `temperature` 逐项映射；`agent_seed = game_config.seed or 0`；其余 `AgentConfig` 字段（`deadline_margin_s` 等）保持默认。
- **旧字段折叠** `legacy_to_profiles(ai_model, ai_model_speech, reflection_model=None, thinking=False) -> AgentProfiles`：`ai_model` 非空 → `{"*": AgentProfile(model=ai_model, ...)}`；为空 → `{}`。
- **冲突**：`agents` 含 `"*"` 且旧字段 `ai_model` 也给出 → `ValueError("ai_model 与 agents['*'] 不能同时指定")`。
- 本期**不含** `personality` / `skills` / `memory_id`（#57/#58/#59 各自增量添加；`extra="forbid"` 保证在此之前这些键被拒绝而非静默忽略）。

## 3. 装配

### 3.1 `runtime/registry.py`

- `GameHandle.__init__(..., agents: AgentProfiles)` 取代 `ai_model` / `ai_model_speech` 两个属性；`GameHandle.profile_for(seat)` 委托 `profile.profile_for`。
- `GameRegistry.create(config, *, allow_spectators, num_ai_players=None, agents=None, ai_model=None, ai_model_speech=None)`：`agents` 与旧字段折叠合并（冲突抛 `ValueError`），`validate_profiles` 后存入 handle。旧调用方（测试、rest.py）不改签名。
- `start()`：`fill_with_bots` 改为 `fill_with_bots(name_for=lambda seat: profile.name or f"Bot{seat}")`（`GameLobby.fill_with_bots(name_for: Callable[[int], str] | None = None)`，缺省行为不变）；对每个空位：`profile_for(seat)` 为 `None` → `BotPlayerPort`，否则 `_build_agent_port(seat, handle)`。
- `_build_agent_port`：`agent_port_factory` 存在则照旧调用（签名 `(seat, handle)` 不变，测试桩不受影响）；否则 `build_agent_port(seat, handle.config, handle.profile_for(seat))`。
- 真人已 `join` 的座位即使有档案也不生效（档案只作用于空位）；不报错。

### 3.2 `agent/agent_player.py`

- `build_agent_port(seat, game_config, profile: AgentProfile) -> AgentPlayerPort`：由 `to_agent_config(profile, game_config)` 生成 `AgentConfig`，客户端仍为 `LiteLLMInstructorClient()`。旧签名 `(seat, config, ai_model, ai_model_speech, thinking=, reflection_model=)` 删除（调用方只有 registry 与 CLI，一并改）。

### 3.3 `cli/play.py` / `cli/play_human.py` / `cli/render.py`

- `load_agent_profiles(path) -> AgentProfiles`：`yaml.safe_load` 读文件（YAML 为 JSON 超集，`.json` 亦可），顶层须为 `{"seats": {...}}`；每项 `AgentProfile.model_validate`；解析/校验错误 → `argparse.ArgumentTypeError`（含文件名与出错键）。
- `main`：`--agents PATH`；旧旋钮 `--ai-model` / `--ai-model-speech` / `--reflection-model` / `--thinking` 经 `legacy_to_profiles` 折叠为 `"*"`；两者冲突（文件含 `"*"` 且给了 `--ai-model`）→ 参数错误。`validate_profiles(agents, config.num_players)`。**终审补记**：`--ai-model` 缺席而给了其他旧旋钮 → 参数错误（不静默丢弃，不叠加到档案）；YAML 中 `0:` 与 `"0":` 折叠后重复 → 参数错误；`'*'` 须加引号写进 `--agents` 帮助。
- `_wire_game(config, *, human_seat=None, agents: AgentProfiles | None = None)`：取代 `ai_model` 等四个参数；每座位 `profile_for` → `build_agent_port` / `BotPlayerPort`；roster 展示名 = `profile.name or f"P{i}"`（真人座仍 `P{i}`）；**任一档案 `thinking=True`** → `_THINK_TIMEOUTS`。`run_watch` / `run_play` 相应改为接收 `agents`。
- `render.py` 新增 `render_agent_roster(agents: AgentProfiles, num_players: int, human_seat: int | None) -> str`：一行一座位 `0号 老张 · ollama/qwen3:8b（发言 openai/gpt-4o-mini）· thinking · T=0.7`，bot 座 `0号 Bot（随机）`，真人座 `2号 你（真人）`；看局/玩局开始时打印（GM 视角信息，仅终端本地）。
- `Makefile`：`AGENTS ?=`，`_AIFLAGS` 加 `$(if $(AGENTS),--agents $(AGENTS),)`。

### 3.4 `api/rest.py` / `schemas/games.py`

- `CreateGameRequest.agents: dict[str, AgentProfile] = {}`（与旧 `ai_model` / `ai_model_speech` 并存）。
- `create_game_endpoint`：`games.create(..., agents=req.agents, ai_model=req.ai_model, ai_model_speech=req.ai_model_speech)`；`ValueError` → `ToolCallError`（400）。
- `CreateGameResponse.agents: dict[str, AgentProfile]` 回显 handle 里解析后的映射（含旧字段折叠结果）。
- 档案属 HOST 建局输入，不进 observation / 观众视图（不新增读取端点；YAGNI）。

### 3.5 依赖与 import 纪律（终审补记）

`app/runtime`、`app/api`、`app/cli` 不得在模块级 import `app.agent.agent_player` / `app.agent.llm_client`（litellm 惰性加载）；`profile.py` 对 `AgentConfig` 的引用经 `TYPE_CHECKING` 守卫 + 函数内 import；`tests/test_agent_profile.py::test_importing_registry_does_not_load_litellm` 守卫此约束（已写入 CLAUDE.md）。

`pyyaml` 加入核心依赖；`types-PyYAML` 加入 dev 组（mypy strict）。

## 4. 文档

- README「终端对局」加 `--agents` 示例与 YAML 样例；「LLM 提供方配置」说明每座位可独立配模型。
- PRD §5.2 建局请求体补 `agents` 字段与查找/冲突规则。

## 5. 测试（零 IO、零 mock；YAML 加载用 tmp_path）

新增 `backend/tests/test_agent_profile.py`：
- schema：未知键拒绝；`temperature` 越界拒绝；缺 `model` 拒绝。
- `profile_for`：座位优先于 `"*"`；无匹配 `None`。
- `validate_profiles`：`"*"`、`"0"`、`"8"` 通过；`"9"`（越界）、`"a"`、`"-1"` 拒绝。
- `legacy_to_profiles` 折叠与冲突。
- `to_agent_config` 逐字段映射、`agent_seed` 取 `config.seed`。

`tests/test_registry.py` 补：`registry.create(agents=…)` 后 `handle.profile_for(seat)` 按座位/`"*"` 解析；`start()` 后 roster 展示名取 `profile.name`（缺省 `Bot{seat}`）、无档案座位为 `BotPlayerPort`；旧 `ai_model` kwarg 折叠为 `"*"`；冲突抛 `ValueError`。（默认工厂需 litellm，故真实 `build_agent_port` 路径不在此测；改由 `test_agent_integration.py` 补一例：`agent_port_factory` 读 `handle.profile_for(seat)` 经 `to_agent_config` 构造 `AgentConfig`，`ScriptedLLMClient` 记录每次调用的 model，断言两座位各异。）

`tests/test_api_lobby.py` / `test_agent_integration.py` 补：`agents` 建局回显；旧 `ai_model` 回显为 `{"*": ...}`；两者冲突 → 400；越界座位键 → 400；档案未知键 → 422（FastAPI 请求体校验）。既有 E2E（旧 `ai_model` 路径）回归。

`tests/test_cli_play_watch.py` 补：`load_agent_profiles`（tmp YAML：座位 + `"*"`；错误文件报参数错误）；`_wire_game(agents=…)` 两座位 `AgentConfig` 各异、bot 座为 `BotPlayerPort`、roster 名；thinking 超时选择；旧旋钮折叠。`test_cli_render.py` 补 `render_agent_roster`。

## 6. 明确不在范围

- `personality` / `skills` / `memory_id`（#57 / #58 / #59）。
- 外部 Agent（`player_type=AGENT`）的档案。
- 对局中修改档案；档案读取端点；每座位独立超时。
