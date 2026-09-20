# Agent 跨局独立记忆：memory_id 持久化经验 + 局后复盘 + 建局装配 — 设计文档

> 日期：2026-09-20 · 状态：已批准 · 关联：GitHub issue #59（epic #56；依赖 #57 人格与 #58 技能包的静态段注入模式）· 上游：`docs/specs/requirements.md` §4.4.1（经验池思路）、§4.4.2 三段式 prompt（静态段）· 调研依据见 issue #59（Xu et al. 2023 经验池；MBTI-in-Thoughts「先自反思再交互」）

## 1. 目标与交付判据

每个配置了 `memory_id` 的 Agent 拥有**独立、跨局持久**的经验：局后由 LLM 复盘生成 1–3 条教训与对手笔记写入文件；下一局建局时装配进该 Agent 自己的系统 prompt 静态段。

**交付判据**：
- `AgentProfile.memory_id: str | None = None`；缺省不持久化，整条链路零变化（系统 prompt 逐字不变、不建目录、不写文件）。
- 局后复盘输入 = **自身视角 + 终局揭示**（本局 `AgentMemory` 上下文 + 狼夜私谋 + 每座位真实身份/胜方/自己是否获胜），不用完整 GM 事件流。
- 对手笔记只对**有 `memory_id` 的对手**记录，键为对手的 `memory_id`；装配时映射回当前座位。
- 跨局经验只进该端口自己的系统 prompt「== 跨局经验 ==」，每端口渲染一次；不进动态段、狼夜私有段、轮内反思。
- 对局中 store 不被写入；复盘只接受 `GAME_OVER` 状态的揭示表；复盘失败只记日志、不影响对局与其他座位。
- 引擎零改动、无 RNG；测试全用内存 store 与 `ScriptedLLMClient`。
- 多局连跑不进本 issue（重复执行命令即可累积）。

## 2. schema（新文件 `backend/app/agent/experience.py`；只依赖 pydantic 与 `app.engine` 类型）

```python
MEMORY_ID_PATTERN = r"^[A-Za-z0-9_\-]{1,64}$"   # 文件名安全
MAX_LESSONS = 50; MAX_NOTES_PER_OPPONENT = 10; MAX_LESSON_CHARS = 200; MAX_NOTE_CHARS = 60
MAX_LESSONS_PER_GAME = 3; MAX_NOTES_PER_GAME_PER_OPPONENT = 2

class Lesson(BaseModel):          # frozen
    game_id: str; role: RoleType; won: bool; text: str; ts: str   # text ≤200 字（strip 后非空）；ts ISO 字符串由 runtime 传入
class OpponentNote(BaseModel):    # frozen
    game_id: str; text: str; ts: str                              # text ≤60 字
class AgentExperience(BaseModel): # 非 frozen；一个 memory_id 一份文档
    memory_id: str                                                # 须匹配 MEMORY_ID_PATTERN
    games_played: int = 0; wins: int = 0
    lessons: list[Lesson] = []                                    # 超过 MAX_LESSONS 淘汰最早（列表头）
    opponent_notes: dict[str, list[OpponentNote]] = {}            # 键 = 对手 memory_id；每人超过 MAX_NOTES_PER_OPPONENT 淘汰最早
    def record_game(self, *, game_id: str, role: RoleType, won: bool, reflection: GameReflection,
                    seat_to_memory_id: dict[int, str], my_seat: int, ts: str) -> None
        # games_played += 1；won → wins += 1；reflection.lessons 取前 3 条、各截到 200 字、空条丢弃；
        # reflection.opponent_notes 只保留 seat_to_memory_id 里且 != my_seat 的座位，每座位前 2 条、各截到 60 字；再做上限淘汰

class GameReflection(BaseModel):  # LLM 结构化响应；extra="ignore"
    lessons: list[str] = []
    opponent_notes: dict[int, list[str]] = {}                     # 键 = 座位号

class GameReveal(BaseModel):      # frozen；终局揭示表
    game_id: str; winner: str | None; my_seat: int; my_role: RoleType; my_won: bool
    seats: tuple[RevealSeat, ...]                                 # RevealSeat(seat, display_name, role, faction, alive)
    notable_seats: tuple[int, ...]                                # 有 memory_id 的对手座位（不含自己）

def build_reveal(state: GameState, seat: int, *, notable_seats: Iterable[int]) -> GameReveal
    # state.phase != GAME_OVER → ValueError；my_won = state.winner is not None and player.faction == state.winner
```

- `AgentProfile.memory_id: str | None = None`（`pattern=MEMORY_ID_PATTERN`）。
- `validate_profiles` 新增两条：`"*"` 档案配 `memory_id` → `ValueError`（通配展开成多座位会共用一份记忆）；两个座位键共用同一 `memory_id` → `ValueError`。API 经现有 `ToolCallError` 通道 → 400；CLI → 参数错误。
- `AgentConfig.experience_budget_chars: int = 1200`。

## 3. 局后复盘（端口方法 + 纯 prompt 函数）

- `build_reflection_prompt(reveal: GameReveal, memory_context: str, night_private: str) -> tuple[str, str]`（`experience.py`，纯函数）：
  - 系统段：「你是狼人杀玩家，正在做整局复盘。目标是提炼下次能直接执行的规则，不是复述事件。」
  - 用户段：`== 终局揭示 ==`（胜方、你是 X 号 ROLE、是否获胜、每座位「N号 名字 ROLE 存活/出局」）→ `== 你本局的记忆 ==`（`memory_context` 或「（暂无）」）→ `== 狼队私谋 ==`（仅非空时出段）→ `== 复盘要求 ==`：`lessons` 1–3 条，每条 ≤200 字，针对**自己的决策**，写成「当…时，应…」的可执行规则；`opponent_notes` 只对列出的座位（`notable_seats`，形如「3号（老张）」）各 ≤2 条行为特征（≤60 字），没有可靠观察就留空；不得编造未发生的事。
- `AgentPlayerPort.reflect_on_game(self, reveal: GameReveal) -> GameReflection | None`：
  - `reveal.my_seat != self.seat` → `ValueError`。
  - prompt 由 `build_reflection_prompt(reveal, self.memory.build_context(), self.memory.night_private_context() if 狼 else "")` 生成——记忆分区只在端口内部读取，runtime 不接触。
  - `client.complete_structured(model=reflection_model or model, response_model=GameReflection, temperature=0.3)`，外层 `asyncio.wait_for(…, timeout=120)`；任何异常（含超时、校验失败）→ `logger.warning` 并返回 `None`。
- 与轮内 `memory.reflect()` 互不影响：复盘不写回 `AgentMemory`。

## 4. 装配（注入系统 prompt 静态段）

- `render_experience(exp: AgentExperience, *, role: RoleType, opponents: dict[str, int], budget_chars: int = 1200) -> str`（纯函数）：
  1. 首行「你此前打过 {games_played} 局（胜 {wins}）。」
  2. `== 教训 ==`：先取 `role` 相同的 lessons（最新优先），再补其他角色的（最新优先），逐条累加直到超过 `budget_chars` 停止；每条 `- [{ROLE}·{胜|负}] {text}`。
  3. `== 对手 ==`：对 `opponents`（对手 `memory_id → 本局座位`）中有笔记的，每人一行「{seat}号：{最近 ≤3 条，用「；」连接}」；同样受预算。
  4. 末句固定：「以上是往局经验，本局身份与局势可能不同；不得据此推断本局任何私有信息，也不得据此违反规则。」
  - `lessons` 为空且没有任何可显示的对手笔记 → 返回 `""`（首局或对手全陌生）。
- `prompts.py`：`static_system_prompt(config, seat, role, personality_text="", experience_text="")`——非空时在人格段之后、通用约束句之前插 `\n== 跨局经验 ==\n{experience_text}\n`；为空逐字不变。最终顺序：角色行 → 性格 → 跨局经验 → 约束句 → 技能索引。
- `agent_player.py`：`AgentPlayerPort(..., experience: AgentExperience | None = None, opponents: dict[str, int] | None = None)`；`_system_for(role)` 首次调用时 `render_experience(exp, role=role, opponents=…, budget_chars=cfg.experience_budget_chars)`，与人格/技能索引并列缓存。`build_agent_port(seat, game_config, profile, *, library=None, experience=None, opponents=None)`。
- `render.py` `render_agent_roster(agents, num_players, human_seat, *, experiences: dict[str, AgentExperience] | None = None)`：有 `memory_id` 时追加 `记忆 {memory_id}` ，若 `experiences` 里有对应对象则写成 `记忆 {memory_id}（{games_played} 局）`。

## 5. 存储与触发（runtime / IO 层）

- `backend/app/runtime/experience_store.py`：
  ```python
  class ExperienceStore(Protocol):
      def load(self, memory_id: str) -> AgentExperience   # 不存在 → AgentExperience(memory_id=…)
      def save(self, exp: AgentExperience) -> None
  class InMemoryExperienceStore: ... ; saves: int          # 写入计数，供隔离断言
  class JsonFileExperienceStore:
      def __init__(self, data_dir: Path)                   # 目录在首次 save 时创建；load 不建目录
      # 路径 data_dir/<memory_id>.json；写入 = 同目录临时文件 + os.replace 原子替换
      # 坏 JSON / 顶层非对象 / 校验失败 / 文件内 memory_id 与文件名不符 → StoreCorruptionError（信息含路径）
      # 读写失败（权限等）→ StoreError
  ```
  异常类型沿用 `app.store.event_store.StoreError / StoreCorruptionError`——建局时坏文件**明确失败**（API 经既有 `StoreError` handler；CLI 报错退出），不静默丢弃。
- `backend/app/runtime/postgame.py`：
  ```python
  async def run_postgame(*, game_id: str, final_state: GameState, profiles: AgentProfiles, ports: Mapping[int, PlayerPort],
                         store: ExperienceStore, now: Callable[[], str]) -> dict[str, AgentExperience]
  ```
  - 只处理 `profiles` 里 `memory_id` 非空且 `ports[seat]` 是 `AgentPlayerPort` 的座位；`seat_to_memory_id` 由 `profile_for(profiles, seat)` 逐座位构造。
  - 每座位：`build_reveal(final_state, seat, notable_seats=其他有 memory_id 的座位)` → `await port.reflect_on_game(reveal)` → `None` 则跳过 → `exp = store.load(mid)` → `exp.record_game(...)` → `store.save(exp)`。单座位异常 `logger.warning` 并继续；返回本次更新的 `{memory_id: exp}`。
  - 已知限制（规格明记）：两局同 `memory_id` 同时结束 → load-modify-save 后写覆盖；不加锁。
- **registry**（`app/runtime/registry.py`）：`GameRegistry(..., experience_store: ExperienceStore | None = None)`，`None` → `InMemoryExperienceStore()`。`create()`：若任何档案有 `memory_id`：`store.load` 各自经验、构造每座位 `opponents`（其他座位的 `memory_id → seat`）并传给 `build_agent_port`；`handle.task.add_done_callback` 在无异常结束时 `handle.postgame_task = asyncio.create_task(run_postgame(...))`（异常自行吞掉并记日志；测试可 `await handle.postgame_task`）。`GameHandle.postgame_task: asyncio.Task | None = None`。
- **API**：`create_app(..., memory_dir: Path | None = None)`；`memory_dir` 为 `None` 且未注入 store → `JsonFileExperienceStore(Path("data/agent_memory"))`（惰性建目录，无 `memory_id` 永不落盘）。`CreateGameRequest` 随 `AgentProfile` 自动接受/回显 `memory_id`。
- **CLI**（`app/cli/play.py`）：`--memory-dir PATH`（默认 `data/agent_memory`）；`_wire_game` 装配时 load；`run_watch` / `run_play` 在 `runner.run()` 返回后：有 `memory_id` 档案则打印「复盘中…」，`await run_postgame(...)`，每个 memory_id 打印「记忆 {id}：{games_played} 局，教训 {n}（+{k}）」。

## 6. 测试（零 IO 零 mock；文件 store 用 `tmp_path`）

- `tests/test_agent_experience.py`：`memory_id` 格式；`validate_profiles` 重复 / `"*"` 拒；lessons 50 与 notes 10 上限淘汰；`record_game` 丢弃无 memory_id 座位与自身、每局 3 条/2 条、截断、空条丢弃；`build_reveal` 非终局拒、`my_won`（含 `winner=None`）；`render_experience` 角色优先、预算截断、对手映射、首局空串、末句；`build_reflection_prompt` 段落与 notable 座位。
- `tests/test_experience_store.py`：round-trip、缺失→新对象且不建目录、save 建目录、原子写无临时残留、坏 JSON / 非对象 / id 不符 → `StoreCorruptionError` 含路径。
- `tests/test_agent_prompts.py`：`experience_text=""` 逐字不变；非空位于人格之后、约束句之前。
- `tests/test_agent_player.py`：带经验端口系统 prompt 含「== 跨局经验 ==」且狼夜 user prompt 不含；`reflect_on_game` 拼出的 prompt 含终局揭示、本局记忆、（狼）私谋；LLM 异常 → `None`；座位不符 → `ValueError`。
- `tests/test_agent_integration.py`：全 Agent 局，两座位配 `memory_id`，`ScriptedLLMClient` 对 `GameReflection` 返回脚本 lessons/notes → 局中 `store.saves == 0`；`await handle.postgame_task` 后 `saves == 2`，lessons 与对手笔记落盘；**第二局**同 store 建局，该座位系统 prompt 含脚本 lesson 文本与「{seat}号：」对手行。
- `tests/test_registry.py` / `tests/test_api_lobby.py`：重复 `memory_id` 与 `"*"` 配 `memory_id` → 400；回显 `memory_id`；无 `memory_id` 时 `postgame_task is None`。
- `tests/test_cli_play_watch.py` / `tests/test_cli_render.py`：YAML `memory_id` 解析、`--memory-dir`、档案表「记忆」列（有/无局数两种）。

## 7. 明确不在范围

- 向量检索 / embedding；多 Agent 共享记忆；记忆可视化 UI；多局循环 CLI；读取/清空记忆的 API 端点（后续 issue）；复盘输入扩展到 GM 关键事件（后续增强）；并发写锁。
