# M2.5 里程碑验收设计 —— 端到端锁定判据 + 缺口补测（issue #32）

日期：2026-07-17
关联：issue #32（父 issue #25，PRD §9 M2 判据）
前置：#28 store、#29 runtime、#30 api、#31 agent —— 全部已入 main

## 目标

端到端串起 M2.1–M2.4，锁定 M2 里程碑验收判据。#32 是**验收**而非新子系统：
既有测试已证明的判据以"验收矩阵"引用，只为**真实缺口**补测；仅需一处最小
生产改动（`create_app` 注入 `agent_port_factory`）。验收矩阵全绿后关父 issue #25。

## 决策摘要

| 决策点 | 结论 |
|---|---|
| 已覆盖判据（真人顶替/超时/重连/RandomBot 全 AI 局） | 不重复造测；验收矩阵引用既有通过测试 |
| 成本测量（判据 7） | env 门控 bench：LiteLLM 回调累计 token，跑一局真实 Ollama，打印总量；手动跑，不入 CI |
| 全 AgentPlayer 经 API 跑局 | `create_app` 加 `agent_port_factory` DI 钩子，测试注入脚本化 mock LLM，零网络 |

## 现状审计（判据 → 覆盖）

| # | 判据 | 状态 | 证据 |
|---|---|---|---|
| 1 | 全 AI 完整对局经 API/WS（非 CLI 直连） | 部分 | `test_api_e2e::test_acceptance_12_ai_full_game_via_api` 用 **RandomBot** 填充经 API/WS 跑到 GAME_OVER + replay 一致；**缺** LLM AgentPlayer 经 API 的等价局 |
| 2 | 真人经同一玩家 API 顶替任意座位 | 已覆盖 | `test_api_e2e::test_acceptance_human_can_take_any_seat`（+ `test_api_ws::test_human_plays_whole_game_via_ws`、`test_api_play::test_human_seat_plays_via_rest`） |
| 3 | 超时代打生效，事件带 `meta.timeout=true` | 已覆盖 | `test_game_runner::TestTimeoutAndRetry::test_hanging_port_replaced_by_default`（断言 `e.meta.get("timeout")=="true"`） |
| 4 | 断线重连 `from_seq` 补发 == 错过的可见后缀 | 已覆盖 | `test_api_e2e::test_acceptance_reconnect_restores_view`（+ `test_api_ws::test_reconnect_backfills_from_seq`） |
| 5 | 工具调用契约稳定；instructor 校验失败重试兜底 | 部分 | §4.1 契约由 `test_schemas` 覆盖；**缺** instructor 校验失败→重试恢复的测试 |
| 6 | 信息隔离抽查（无权视角看不到 WOLVES/GM_ONLY） | 部分 | REST `/events` 隔离矩阵已覆盖（`test_api_e2e::test_acceptance_isolation_matrix_via_api`）；**缺** 活 WS 流上的狼/民隔离矩阵 |
| 7 | 单局 LLM token/费用粗测 | 缺 | 无任何 token/成本测量 |

README（仓库根）无 API 快速开始一节。

## 交付物

### A. 生产改动（唯一一处）：`app/main.py::create_app` 增 `agent_port_factory`

- 签名新增可选参数：
  `create_app(*, store=None, timeouts=None, data_dir=None, agent_port_factory=None)`。
- 直接透传给 `GameRegistry(store, timeouts, agent_port_factory=agent_port_factory)`
  （registry 自 Task 7 已支持该参数）。
- 默认 `None` → 行为与现状完全一致（`ai_model` 路径仍走真实 LiteLLM）。
- 无此钩子则经 API 的 AI 局会命中真实网络，无法在 CI 内 mock —— 这是补测判据 1
  的前置。

### B. 缺口补测

补测集中在新文件 `tests/test_acceptance_m25.py`（判据 1/6）与既有 smoke/单测文件
（判据 5/7），复用既有 helper（`tests/llm_helpers.py` 的 `ScriptedLLMClient`
/`action_to_decision`；`tests/factories.py`；WS 测试的 TestClient 惯用法）。

**判据 1 —— 全 AgentPlayer 经 HTTP+WS 跑到 GAME_OVER**（`test_acceptance_m25.py`）
- `create_app(store=InMemoryEventStore(), timeouts=<宽松>, agent_port_factory=<脚本工厂>)`。
- 脚本工厂：对每个 AI 座位返回 `AgentPlayerPort`，其 `LLMClient` 为 `ScriptedLLMClient`，
  脚本经 `handle.runner.state` + `RandomBot.choose_action` + `action_to_decision`
  产出合法决策（与 `test_agent_integration` 同法，但**现在经 ASGI app**）。
  工厂签名 `(seat, handle) -> AgentPlayerPort`，与 registry 的 `agent_port_factory`
  契约一致。
- 流程：`POST /games`（`ai_model="scripted"`、`num_ai_players` = 全部空位、
  `allow_spectators=true`）→ `POST /start` → 观战者 WS 收流至 `game_over`。
- 断言：GM `/replay` 终局为 GAME_OVER；store 事件与运行态一致（沿用既有
  replay-parity 口径）；每个 AI 座位确为 `AgentPlayerPort`（经 registry 断言，
  测试内白盒读取 handle）。

**判据 5 —— instructor 校验失败→重试恢复**（`tests/test_agent_llm_client.py` 扩充）
- 在 `litellm.acompletion` 边界打桩（`LiteLLMInstructorClient` 包装的那个 callable）：
  首次返回**校验不通过**的结构化响应，二次返回合法响应。
- 断言 `complete_structured(...)` 经重试最终返回合法决策实例，且底层 completion
  callable 被调用 ≥2 次 —— 证明 `max_retries=2` 接线对弱模型坏输出的恢复能力。
- **实现兜底（降级路径，若 instructor 内部机制导致边界打桩过脆）**：改为断言
  `LiteLLMInstructorClient` 确将 `max_retries` 传入 instructor 客户端，并在报告中
  说明退化原因。二选一由实现者按 instructor 实测行为决定；spec 接受任一。

**判据 6 —— 活 WS 流上的狼/民隔离矩阵**（`test_acceptance_m25.py`）
- 一局内：狼座 token、民座 token、观战 token 各开一条 WS。
- 驱动至夜间产生 WOLVES 事件（脚本/bot 均可，沿用既有 WS 测试推进法）。
- 断言：`WOLF_KILL_PROPOSED`（WOLVES 可见）**仅**出现在狼座 WS 流；民座与观战流
  **无**该事件；任何非 GM 流**永不**出现 GM_ONLY 事件。与 REST 隔离矩阵同口径，
  但在活 WS 帧上校验。

**判据 7 —— 单局 token/成本 bench**（env 门控，`smoke` 标记；`tests/test_agent_bench.py`）
- 门控与既有 smoke 一致：`AGENTHOWL_SMOKE_MODEL` 未设 / Ollama 不可达则 skip。
- 挂 LiteLLM token 回调（`litellm.success_callback` 或逐调用 `response.usage`）
  累计 prompt+completion token 跨一局真实 Ollama 对局。
- 断言仅 `total_tokens > 0`（结构性），并 `print` token 总量供人工读数。
- 备注：本地 Ollama 无定价，`completion_cost` ≈ 0 —— bench 报 token 数（有意义值），
  成本尽力而为。为控时长，可用最小人数 preset 或跑一局至 GAME_OVER；env 门控故
  时长可接受。

### C. 文档

- README（仓库根）新增 **"API 快速开始 / API Quick Start"** 一节：`curl` 走一遍
  建局（含 `ai_model`）→ join → start → my-turn/actions → WS 连接 → replay；
  附 smoke/bench 环境变量（`AGENTHOWL_SMOKE_MODEL`）用法。
- 验收矩阵：以上"现状审计"表的最终版（补测后全部→已覆盖）纳入本 spec 收尾节，
  README 附精简版链接回本 spec。

## 硬约束（复述自 CLAUDE.md / PRD §1.3）

- 引擎纯函数零 IO 不变；补测只碰 api/runtime/agent/test 与文档
- 服务端唯一事实来源；隔离仍是 `build_observation`/`visible_events` 单一过滤点
- 全 AgentPlayer 经 API 的测试用脚本 mock LLM，**零网络**；真实模型仅 env 门控 bench
- `create_app` 新参数默认 None，既有全部测试语义不变

## 测试策略与质量门

- 新测试：`tests/test_acceptance_m25.py`（判据 1/6）、`test_agent_llm_client.py` 扩充
  （判据 5）、`tests/test_agent_bench.py`（判据 7，默认 skip）。
- 质量门（`backend/`）：`uv run pytest -q`（含既有全量，360s timeout）、
  `uv run mypy app`（strict）、`uv run ruff check .`、`uv run ruff format --check .`。
- CI 影响：判据 1/5/6 入 CI（mock，零网络）；判据 7 默认 skip。

## 明确不做（YAGNI）

- 前端（M3）；token 预算硬闸 / 分层路由调优（跟进 #42）；服务器重启续局（#37/M3）；
  多进程 / Redis；真实模型全量 CI（成本与时长不可接受，仅 env 门控 bench）。
- bench 只**测量**不**强制**任何预算。

## 收尾

- 验收矩阵全绿 → PR → 合并后 issue #32 关闭 → 关父 issue #25（M2 完成）。
