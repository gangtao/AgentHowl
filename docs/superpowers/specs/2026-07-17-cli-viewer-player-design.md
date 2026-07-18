# CLI 观战/对局器设计 —— 在终端里看局与玩局（issue #44）

日期：2026-07-17
关联：issue #44（DX 工具，M3 前端 #26 的热身，正交）
前置：M2 全部合并（store/runtime/api/agent/验收）

## 目标

无 Web 前端时，让人在终端里**看一整局**（事件流渲染成可读中文播报）与**玩一局**
（交互式扮演一个座位）。纯客户端：只渲染服务端过滤后的视角，零裁决、零信息隔离
旁路——与 API 同一安全口径（`build_observation`/`visible_events` 唯一过滤点）。

## 决策摘要

| 决策点 | 结论 |
|---|---|
| 接入方式 | **进程内 async**：直接跑 runtime `GameRunner` + `ConnectionManager`，无 server、无新依赖；API 客户端模式本期不做（后续 issue） |
| 看局节奏 | 默认 `--delay`（约 0.6s 逐事件自动推进）+ `--step`（回车逐步）；all-bot 局否则瞬间跑完 |
| 看局默认视角 | **GM**（看全：角色/夜刀/狼聊/查验），`--view spectator|seat:N` 可切；玩局恒用本座视角 |
| 渲染 | 专用 CLI 渲染器（不复用 agent 私有 `_render`）；轻量 ANSI 上色，无 rich/textual 依赖，非 TTY 自动关色 |
| 输入 | 友好行式 mini-syntax → `{tool, arguments}`；行读取器可注入（测试用脚本 reader，无需 TTY） |

## 为何进程内 async（而非经 GameRegistry）

`registry.start()` 内部 `asyncio.create_task(runner.run())`，会与"订阅须先于 run"
的要求竞态（否则漏开局首批 `GAME_CREATED`/`ROLES_ASSIGNED`）。CLI 需要在 run 前
挂上打印型订阅者，故手工装配 store/runner/connections（~15 行），换取订阅时序可控。
纯 spectator 的同步 `run_game` 路径（先跑完再叙述）不用，因为它不能实时流、也不能
容纳真人座位。

## 模块划分（`app/cli/`）

### render.py（新，共享叙述器）
- `render_event(event: Event) -> str`：按 `EventType` 渲染成可读中文行，复用
  `app/engine/events.py` 的 payload 模型。至少覆盖叙述相关类型：
  `ROUND_STARTED`/`PHASE_CHANGED`(公开)/`PLAYER_SPOKE`/`LAST_WORDS`/`DEATH_ANNOUNCED`/
  `NIGHT_RESOLVED`/`PLAYER_EXILED`/`HUNTER_SHOT`/`WOLF_SELF_DESTRUCT`/`VOTE_STARTED`/
  `VOTE_CAST`/`VOTE_RESULT`/`SHERIFF_*`/`ELECTION_STAGE_CHANGED`/`BADGE_PASSED`/
  `GAME_OVER`；GM 视角另含 `ROLES_ASSIGNED`/`GUARD_PROTECTED`/`WOLF_KILL_*`/`WITCH_*`/
  `SEER_CHECKED`。未特判类型回退简洁通用格式（非 raw dict dump）。
- `render_observation(obs: PlayerObservation) -> str`：多行局势摘要（轮/阶段/存活/
  警长/自身私有信息，排除内部 `wolf_chat` 键）。
- `render_tools(tools: tuple[str, ...]) -> str`：可用工具提示。
- `color(text, style)` 小工具：ANSI 上色；`sys.stdout.isatty()` 为假或
  `NO_COLOR`/`--no-color` 时输出纯文本。

### play.py（新，入口 `python -m app.cli.play`）
- argparse：`--seat N`（设=真人玩该座；缺=纯看局）、`--preset`、`--seed`、
  `--view gm|spectator|seat:N`（仅看局）、`--delay FLOAT`、`--step`、
  `--ai-model STR`（可选 LLM 自对局）、`--no-color`。
- 装配（两模式共用）：`InMemoryEventStore` → 构造 roster → ports（见下）→
  `conns = ConnectionManager(state_provider=lambda: runner.state)`（lambda 容忍
  run 前不被调用）→ `runner = GameRunner(store, config, game_id, roster, ports, conns)`
  → **先** `conns.subscribe(viewer, printing_cb)` → `asyncio.run(driver())`。
- ports 规则：
  - 真人座（`--seat N`）：`HumanPlayerPort()`。
  - 其余座：`--ai-model` 设 → `build_agent_port(seat, config, ai_model, None)`；
    否则 `BotPlayerPort(state_provider=lambda: runner.state)`。

### 看局模式（无 --seat）
- 打印型订阅者按 `--view` 定 viewer（GM 默认 / SPECTATOR / seat:N）。
- 节奏：订阅回调在 runner 提交路径内被 await，故回调里 `await asyncio.sleep(delay)`
  或 `--step` 等回车即自然为整局限速。
- `await runner.run()` 至 GAME_OVER，打印胜负横幅。

### 玩局模式（--seat N）
- ports：座 N = `HumanPlayerPort()`，其余 = bot/agent。
- 打印型订阅者 viewer=N（看到本座私有 + 公开事件叙述）；玩局默认 `--delay 0`。
- 并发跑：`asyncio.gather(runner.run(), turn_loop())`，`runner.run()` 返回后取消
  `turn_loop`。turn_loop：
  1. `prompt = await port.wait_armed(timeout)`（None→再轮询/检查是否终局）。
  2. 渲染 `prompt.observation`（`render_observation`）+ `available_tools_for(obs)`
     + 截止时间。
  3. `line = await read_line("> ")`（**注入型** async 读取器，默认
     `asyncio.to_thread(input, prompt)`；测试注入脚本 reader）。
  4. `parse_line(line, obs) -> ToolCall`（mini-syntax，见下）→
     `parse_tool_call(call, actor_seat=N) -> Action`。解析/工具错误 → 打印提示重读。
  5. `outcome = await port.submit_and_wait(action)`；渲染信封（ok / rejected_reason）；
     被拒则窗口仍开，重读（至截止或引擎 MAX_REJECTIONS，超时则 runner 落默认行动，
     CLI 提示"超时代打"）。
- 宽松默认超时（如 speech/action 各 120s，`RunnerTimeouts`；可留常量）。

### 输入 mini-syntax（parse_line）
首 token = 命令，其余 = 参数，映射到 `{tool, arguments}`：
- `speak <text...>` → `{speak, {content}}`（MVP 仅 content；claim_role/badge_flow 留后续）
- `vote <seat>` / `vote abstain` → `{vote, {target_seat}}` / `{vote, {abstain: true}}`
- `night <action_type> [seat]` → `{night_action, {action_type, target_seat?}}`
  （kill/check/save/poison/guard/shoot/skip）
- `sheriff <action_type> [seat|direction]` → `{sheriff_action, {action_type, target_seat?/direction?}}`
- `self_destruct` → `{self_destruct, {}}`
- `help` → 打印 `available_tools_for(obs)` + 语法提示（不提交）
- `state` / `speeches` → 重印当前 observation / 已公开发言（本地渲染，不提交）
- 空行/无法解析 → 提示重读；解析层不做合法性裁决（交引擎）。

### LLM 自对局（可选 --ai-model）
复用看局路径，全座 `build_agent_port(...)`。测试 env 门控（需 Ollama），CI 不跑真模型。

## 硬约束（CLAUDE.md）

- CLI 是纯客户端：只经 `visible_events`/`build_observation` 取视角，零裁决零过滤旁路
- 不改引擎；渲染器复用引擎 payload 模型，不 import api（避免拖入 FastAPI）
- `_your_turn_payload` 在 api 层且 import FastAPI —— CLI 不 import，自行用
  `available_tools_for(obs)` 拼所需信息
- 订阅须先于 `runner.run()`；`state_provider` lambda 须容忍 run 前不被调用

## 测试策略

- **单测（无 runner，无 IO）**：`render_event` 对每个叙述相关 EventType + 回退产出
  非空可读文本；`render_observation`/`render_tools` 非空；`parse_line` 各命令 →
  `ToolCall` → `parse_tool_call` 得预期 Action；非法行拒绝提示。
- **集成（进程内 runner，固定 seed）**：
  - 看局：全 bot 局 `--delay 0` 跑到 GAME_OVER，捕获 stdout，断言叙述含
    死亡/投票/GAME_OVER 行；GM 视角含夜间/角色行、SPECTATOR 视角仅公开。
  - 玩局：真人座由**脚本 reader**提交合法行动至终局；断言该座提交被引擎接受、
    对局收敛；一例非法输入 → 提示后合法重提成功。
- **LLM 自对局**：env 门控 smoke（`AGENTHOWL_SMOKE_MODEL`），默认 skip。
- 质量门：`uv run pytest`、`uv run mypy app`（strict）、`uv run ruff check .`、
  `uv run ruff format --check .` 全绿。

## 明确不做（YAGNI）

- Web 前端上帝视角 / 实时直播（#26 M3）
- API 客户端模式（连已跑 server；后续 issue）
- 重型 TUI / 鼠标 / 多局面板
- `speak` 的 claim_role/badge_flow 参数（MVP 仅 content）
- 服务器重启续局（#37 前置）

## 收尾

- 全部判据绿 → PR → 合并后关 #44。
