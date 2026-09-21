# Agent 档案评估：离线指标分析器 + A/B bench 驱动 — 设计文档

> 日期：2026-09-21 · 状态：已批准 · 关联：GitHub issue #60（epic #56 收官；依赖 #64 `GameMeta.agents`；服务于 #57 人格、#58 技能包、#59 跨局记忆的效果验证）· 上游：`docs/specs/requirements.md` §5.2（回放 / meta）、§1.3（引擎零 IO、事件溯源）

## 1. 目标与交付判据

回答「这个 Agent 配置有没有用」：从**已落盘的事件日志**离线统计每个档案（按内容指纹聚合）的多局胜率与行为指标，并提供一个 A/B bench 驱动器把两份档案交错放进同一批对局。

**交付判据**：
- 零 LLM：`python -m app.cli.bench --games N`（无 `--agents`）用随机 bot 跑 N 局，落盘并产出**全部**指标（人格 / 技能指标为 0），报告含「随机 bot」组。
- `--agents a.yaml --agents-b b.yaml` 两份档案交错分配座位、逐局轮转；报告按标签 A/B 显示并给出 `Δ(A−B)` 差异列。
- `--report-only DIR` 对任意来源（API / CLI / bench）的 JSONL 日志目录得到同样的报告。
- 档案身份 = **内容指纹**（去 `name` / `memory_id` 后的规范化 JSON 摘要）；标签只是显示。
- 技能装配次数通过事件 `meta["skills"]` 落盘（runtime 写、引擎不感知），任何来源的日志都能统计。
- 引擎零改动；分析器纯函数、零 IO；测试用随机 bot 局与手工事件序列。

## 2. 指标定义（每座位每局 `SeatStats` → 按指纹（× 角色）汇总 `ProfileStats`）

| 组 | 字段 | 口径 |
|---|---|---|
| 胜负 | `games`、`wins`、`win_rate` | 本座位阵营 == `GAME_OVER.winner`；平局（`None`）不计胜 |
| | `wolf_games/wolf_wins`、`good_games/good_wins`、`by_role[role]` | 角色来自 `ROLES_ASSIGNED`；阵营 = `faction_of(role)` |
| 存活 | `alive_at_end`、`survive_rate`、`rounds_alive`、`avg_rounds_alive` | 死亡轮次 = 死亡事件时 `state.round`；存活者 = 终局 `state.round` |
| | `exiled`、`exiled_rate`、`night_killed`、`night_killed_rate` | `PLAYER_EXILED.seat` / `NIGHT_RESOLVED.deaths`（含毒杀，统称夜死） |
| 发言 | `speeches`、`speech_chars`、`avg_speech_chars` | `PLAYER_SPOKE.content` 字符数 |
| | `claims`、`claim_rate`、`badge_flows`、`badge_flow_rate` | 带 `claim_role` / 带非空 `badge_flow` 的发言 / 发言数 |
| 警长 | `sheriff_games`、`candidacies`、`candidacy_rate`、`elected`、`withdrew` | `SHERIFF_CANDIDACY(running=True)` / `SHERIFF_ELECTED` / `SHERIFF_WITHDREW`；分母 = `config.sheriff.enabled` 的局数 |
| 投票 | `votes`、`abstains`、`abstain_rate` | `VOTE_CAST`；`target is None` 为弃票 |
| | `pk_votes_eligible`、`vote_changes`、`vote_change_rate` | PK 轮（`VOTE_STARTED.tie_round == 1`）中，该投票人首轮目标 ∈ PK 候选 → 计入分母；PK 目标 ≠ 首轮目标 → 计入分子 |
| 狼队 | `wolf_nights`、`proposals`、`no_kill_proposals`、`no_kill_proposal_rate` | 本狼在世且当夜有 `WOLF_KILL_PROPOSED` 的夜；`target is None` 为空刀提案 |
| | `revote_nights`、`revote_night_rate`、`decided_no_kill`、`decided_no_kill_rate` | 团队事件记到每个在世狼：当夜出现 `WOLF_KILL_REVOTE` / `WOLF_KILL_DECIDED.target is None`；分母 = `wolf_nights` |
| 技能 | `skills_assembled`、`skill_counts[name]` | 事件 `meta["skills"]`（逗号分隔）按 `actor_seat` 计数 |

比率字段在汇总时按「分子和 / 分母和」计算（非每局比率再平均）；分母为 0 → `None`（报告显示 `N/A`）。`meta.agents` 无该座位 → 指纹 `None`，归「随机 bot」组。

## 3. 分析器（新包 `backend/app/eval/`，纯函数，零 IO）

- `fingerprint.py`
  - `profile_fingerprint(profile: AgentProfile) -> str`：`json.dumps(profile.model_dump(mode="json", exclude={"name", "memory_id"}), sort_keys=True, ensure_ascii=False)` 的 sha1 前 10 位。
  - `profile_summary(profile) -> str`：`{model}` + `· 技能 a,b`（有则）+ `· 性格 {personality_summary}`（有则）+ `· T={temperature}`（非默认 0.3 时）+ `· thinking`（有则）。
- `metrics.py`
  - `SeatStats(BaseModel)`（非 frozen，全部计数字段默认 0；`skill_counts: dict[str, int]`）。
  - `GameAnalysis(BaseModel)`：`game_id`、`winner: str | None`、`rounds: int`、`sheriff_enabled: bool`、`roles: dict[int, RoleType]`、`fingerprints: dict[int, str | None]`、`seats: dict[int, SeatStats]`。
  - `analyze_game(meta: GameMeta, events: Sequence[Event]) -> GameAnalysis`：`state = initial_state(meta)`；逐事件：先用**应用前**的 `state`（当前 `round`、在世狼集合、投票轮上下文）做归因，再 `state = reduce(state, event)`。投票上下文：`VOTE_STARTED` 记 `(tie_round, candidates)`，`tie_round == 0` 时清空并记录首轮目标表 `first_targets[voter]`；`tie_round == 1` 的 `VOTE_CAST` 按 §2 口径计改票。夜：`ROUND_STARTED` 开新夜，`revote_seen`/`decided_no_kill_seen` 复位，`wolf_nights` 在该夜首个 `WOLF_KILL_PROPOSED` 时对所有在世狼 +1（同夜只加一次）。死亡：`NIGHT_RESOLVED.deaths` → `night_killed`、`rounds_alive = state.round`；`PLAYER_EXILED.seat` → `exiled`、`rounds_alive = state.round`；`HUNTER_SHOT.victim` / `WOLF_SELF_DESTRUCT.seat` 只记 `rounds_alive`。终局：未死者 `alive_at_end = 1`、`rounds_alive = state.round`；`wins` 按阵营。技能：任何带 `meta["skills"]` 且 `actor_seat` 非空的事件，`skills_assembled += 1`、逐名 `skill_counts` +1。
  - `ProfileStats(BaseModel)`：§2 全部汇总字段 + `by_role: dict[RoleType, RoleStats(games, wins)]` + `summary: str`（首次遇到的档案摘要；随机 bot 为「随机 bot」）；`rate` 属性按分子/分母和计算。
  - `aggregate(analyses: Iterable[GameAnalysis], profiles: Mapping[str, AgentProfile] | None = None) -> dict[str | None, ProfileStats]`：按指纹合并；`profiles` 用于填 `summary`（由调用方从各局 `meta.agents` 收集）。
  - `diff(a: ProfileStats, b: ProfileStats) -> dict[str, float | None]`：所有比率字段与 `avg_*` 的 `a − b`（任一为 `None` → `None`）。
- 与 #64 的契约：`GameMeta.agents` 键为座位号字符串，只含实际建成 Agent 端口的座位。

## 4. 事件 `meta["skills"]`（runtime）

- `GameRunner._drive_seat`：`port.act(...)` 返回后 `skills = tuple(getattr(port, "last_skills_used", ()))`；`await self._commit(res.events, skills=skills)`。
- `GameRunner._commit(events, timed_out=False, skills=())`：已有的「meta 充实」处，`skills` 非空时只在**首条**事件 `meta` 追加 `"skills": ",".join(skills)`；超时代打路径不传 `skills`。
- 引擎不读 `meta`；`Event.meta` 已随 JSONL 序列化。
- 隔离（实现期附注，Ruling 2）：`meta["skills"]` 可暴露阵营（`wolf-*` 技能名），API 对非 GM 视角（玩家 / 观众的 `/events` 与 WS 帧）只序列化公开 meta 键（`wall_ts`、`timeout`，`app/api/views.py::PUBLIC_META_KEYS`）；`/replay` 终局后全量不变；离线分析器读 store 全量。

## 5. bench 驱动（`backend/app/cli/bench.py`）与 `_wire_game` 扩展

- `_wire_game(config, *, human_seat=None, agents=None, library=None, experiences=None, store: EventStore | None = None, game_id: str = "cli")`：新增两参数，默认行为不变。
- 参数：`--games N`（默认 1）、`--preset`、`--seed S`（默认 42）、`--agents PATH`（A）、`--agents-b PATH`（B，需 `--agents`）、`--label-a`（默认 `A`）、`--label-b`（默认 `B`）、`--skills-dir`、`--out DIR`（默认 `data/bench/<YYYYmmdd-HHMMSS>`）、`--json PATH`、`--report-only DIR`。`--report-only` 与跑局参数互斥；A/B 内容相同（同指纹）拒绝；`--report-only` 目录不存在、`--out` 已存在且非空均为参数错误；未终局日志不计入汇总并提示跳过数（实现期附注）。
- 座位分配：`assign_seats(num_players, game_index, a: AgentProfiles, b: AgentProfiles | None) -> AgentProfiles`：座位 s 取 `a` 若 `(s + game_index) % 2 == 0` 或 `b is None`，否则 `b`；对选中集合 `profile_for(set, s)`，None 则不放（随机 bot）；返回按座位号键的映射（不含 `"*"`）。纯函数，确定性。
- 每局：`seed = S + i`，`config = build_preset(preset).model_copy(update={"seed": seed})`，`game_id = f"bench-{seed}"`，`_wire_game(config, agents=assign_seats(...), library=, store=store, game_id=game_id)` → `await runner.run()`；打印 `seed={seed} winner={winner} rounds={round}`。顺序执行。不装配跨局记忆、不跑 postgame（档案里的 `memory_id` 只被记进 meta）。
- 标签映射：`labels: dict[str, str]` = 对 A 集合的每个档案 `fingerprint → label_a`（多个档案时 `A/{key}`，key 为 yaml 座位键），B 同理；随机 bot 组标签「随机 bot」。
- 分析：`for gid in store.list_games(): analyze_game(store.load_meta(gid), store.load_events(gid))` → `aggregate` → `render_table` 打印；`--json` 写 `to_json`。`--report-only DIR` 只做这一步（无标签时用 `profile_summary` 作显示名）。
- `Makefile`：`bench` 目标（`GAMES`、`AGENTS`、`AGENTS_B`、`ARGS`）。

## 6. 报告（`backend/app/eval/report.py`）

- `render_table(stats: Mapping[str | None, ProfileStats], labels: Mapping[str | None, str]) -> str`：一行一档案；列：`档案 · 局数 · 胜率 · 狼胜 · 好人胜 · 存活率 · 均存活轮 · 放逐率 · 发言均长 · 声称率 · 上警率 · 改票率 · 空刀率 · 重提率 · 技能次数`；比率 `xx.x%`，`None` → `N/A`；列宽按东亚宽度（`unicodedata.east_asian_width` W/F 计 2）对齐。恰有两个带标签的档案时追加 `Δ(A−B)` 行（用 `diff`）。
- `to_json(stats, labels) -> dict[str, object]`：`{"profiles": [{"label", "fingerprint", "summary", ...全部字段, "by_role": {...}, "skill_counts": {...}}], "diff": {...} | None}`。

## 7. 测试（零 IO 零 mock；文件用 `tmp_path`）

- `tests/test_eval_fingerprint.py`：同内容不同 `name` / `memory_id` 指纹相同；改温度 / 技能顺序 / 人格 → 不同；`profile_summary` 格式。
- `tests/test_eval_metrics.py`：随机 bot 局（`run_game`）→ 每座位 `wins` 与终局阵营一致、`alive_at_end + exiled + night_killed + 其它死亡 = 1`、`rounds_alive ≤ rounds`；手工事件序列：改票率（首轮 A → PK 改 B 记 1/1；首轮目标不在 PK 候选 → 0/0）、空刀 / 重提 / 决定空刀率、声称 / 警徽流率、上警 / 当选 / 退水、弃票率、`meta["skills"]` 计数；无档案座位指纹 `None`；`aggregate` 合并两局按指纹、`by_role`；`diff` 差值与 `None` 传播。
- `tests/test_game_runner.py`：带技能端口 → 该行动首条事件 `meta["skills"] == "a,b"`、同批后续事件无；无技能不写；超时代打不写。`tests/test_event_store.py`：`meta` 随 JSONL 往返（加一断言）。
- `tests/test_cli_bench.py`：`assign_seats` 交错 / 轮转 / 无 B 全 A / `"*"` 与座位专属解析 / 确定性；`main(["--games","2","--out",tmp,...])` 零 LLM → 2 个 JSONL、输出含「随机 bot」与 `2`；`--report-only` 同目录输出一致；`--json` 结构；`--agents-b` 无 `--agents` → 参数错误；`--report-only` 与 `--games` 同给 → 参数错误。
- `tests/test_agent_bench.py`：env 门控 `test_ab_bench_smoke`：`AGENTHOWL_SMOKE_MODEL` 下 A（多疑 0.9）/ B（从众 0.9）各跑 1 局打印表格，不断言方向。

## 8. 明确不在范围

显著性检验 / 置信区间；Markdown / HTML 报告；并行跑局；bench 内跨局记忆与 postgame；按 `memory_id` 的经验增长曲线；真人座位。
