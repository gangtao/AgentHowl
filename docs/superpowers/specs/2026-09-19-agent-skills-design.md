# Agent 技能包：SKILL.md 技巧库按角色/阶段渐进装配 — 设计文档

> 日期：2026-09-19 · 状态：已批准 · 关联：GitHub issue #58（依赖 #56 AgentProfile）· 上游：`docs/specs/requirements.md` §2 术语表（悍跳/倒钩/警徽流/归票…）、§4.4.2 三段式 prompt；`2026-09-18-agent-profile-design.md`；外部规范 [Agent Skills Specification](https://agentskills.io/specification)

## 1. 背景与目标

狼人杀有大量可传授的技巧。本期让每个 Agent 可配置**技能包**：技能是打包好的策略说明（`SKILL.md`），按角色与阶段自动装配进 prompt，并可 A/B 评估。调研依据见 issue #58（Strategy Adaptation 论文：策略显式写进 prompt + 角色估计 + 切换条件，狼队胜率最高；Agent Skills 规范：`SKILL.md` + 渐进披露）。

**交付判据**：
- `backend/skills/<name>/SKILL.md` 内置库（首批 14 篇）+ 可选外部目录（同名覆盖），文件格式兼容 Agent Skills 规范（自定义字段在 `metadata`）。
- `AgentProfile.skills: list[str]`（`"*"` = 全部）；未知技能名建局即错（API 400 / CLI 参数错误）。
- 系统 prompt 列出已配技能 `name: description`（第一层披露）；每次决策按 `(my_role, phase)` 过滤、按 priority 排序、按字符预算整篇取舍后把正文装进指令段（第二层）。
- 公私分离不变：狼夜私有调用只装 `phases` 含 `NIGHT_WEREWOLF` 的技能；昼间公开调用只装昼间阶段技能。
- `skills_text` 为空时 prompt 与现状逐字相同（不配技能零变化）。
- 端口记录 `last_skills_used` 并写 INFO 日志；开局档案表与建局响应显示技能名。

## 2. 技能文件格式

```
backend/skills/seer-badge-flow/SKILL.md
---
name: seer-badge-flow
description: 预言家上警时如何报查验与警徽流，以及如何应对悍跳
metadata:
  roles: "SEER"                                     # 空格分隔的 RoleType 名；缺省 = 全部角色
  phases: "SHERIFF_ELECTION SHERIFF_PK DAY_SPEECH"  # 空格分隔的 Phase 名；缺省 = 全部阶段
  priority: "10"                                    # 整数；同阶段多技能时降序装配；缺省 0
---
正文：中文策略说明，结构为「触发条件 → 做法 → 反例/风险」，≤ 600 字。
```

- `name`：1–64 字符，`[a-z0-9-]`，不以连字符开头/结尾、无连续连字符，**须与目录名一致**。`description`：1–1024 字符。
- `metadata` 只允许字符串值（规范要求）；`roles` / `phases` 里的名字须是 `RoleType` / `Phase` 的合法成员；`priority` 须为整数字符串。
- 正文长度上限 `MAX_BODY_CHARS = 1200`（首批约定 ≤ 600 字，上限留余量）。`references/` 等子目录允许存在，本期不装配。
- 任一校验失败 → `SkillError`（加载期 fail-loud）。

## 3. 模块 `backend/app/agent/skills.py`

```python
@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    roles: frozenset[RoleType]   # 空集 = 全部
    phases: frozenset[str]       # 空集 = 全部（值为 Phase.value）
    priority: int
    body: str
    source: Path

class SkillError(ValueError): ...

STAR = "*"
DEFAULT_SKILL_BUDGET_CHARS = 1800
BUILTIN_SKILLS_DIR = Path(__file__).resolve().parents[2] / "skills"   # backend/skills

class SkillLibrary:
    @classmethod
    def load(cls, dirs: Sequence[Path]) -> SkillLibrary        # 依次扫描，后者同名覆盖前者；每个子目录须含 SKILL.md
    def names(self) -> list[str]
    def get(self, name: str) -> Skill                           # 未知 → KeyError
    def resolve(self, wanted: Sequence[str]) -> list[Skill]     # 展开 "*"；未知名 → SkillError（含名字）
    def empty(cls) -> SkillLibrary

def parse_skill_md(path: Path) -> Skill                          # frontmatter（yaml.safe_load）+ 正文；校验
def select_skills(skills: Sequence[Skill], role: RoleType, phase: str) -> list[Skill]   # 过滤 + priority 降序、name 升序
def assemble_skills(skills: Sequence[Skill], budget_chars: int = DEFAULT_SKILL_BUDGET_CHARS) -> tuple[str, tuple[str, ...]]
    # 按序整篇累加，超预算即停（不截断正文）；返回 (文本, 用到的技能名)。文本形如：
    # "【技能：seer-badge-flow】\n<正文>\n\n【技能：…】\n<正文>"
def skills_index_text(skills: Sequence[Skill]) -> str            # "- name：description" 每行一条（系统 prompt 用）
def default_library() -> SkillLibrary                            # 进程内缓存的内置库（惰性加载）
```

- `load` / `parse_skill_md` 是 IO；`select` / `assemble` / `index_text` 纯函数。
- 模块不 import `agent_player` / `llm_client`（保持 litellm 惰性加载纪律）。

## 4. 档案与装配链

- `AgentProfile.skills: list[str] = Field(default_factory=list)`；元素为技能名或 `"*"`。
- 校验：`validate_profiles(agents, num_players, library: SkillLibrary | None = None)`——给了 `library` 就对每个档案 `library.resolve(profile.skills)`，未知名 → `ValueError`（沿用现有 API 400 / CLI 参数错误映射）。registry 与 CLI 都传库；API 层不额外做。
- `to_agent_config` 不变（技能不进 `AgentConfig`）；`build_agent_port(seat, config, profile, library)` 解析技能列表后传给端口。
- `AgentPlayerPort(..., skills: Sequence[Skill] = ())`：
  - `_system_for`：技能非空时在静态段末尾追加 `"\n== 你的技能 ==\n" + skills_index_text(skills)`。
  - `act`：`selected = select_skills(self._skills, obs.my_role, obs.phase)`；`text, used = assemble_skills(selected, self._cfg.skill_budget_chars)`；`self.last_skills_used = used`；`logger.info("seat=%d phase=%s skills=%s", …)`；`text` 经新增的 `skills_text: str = ""` 关键字参数传入 `build_prompt` / `build_wolf_night_prompt`。
  - `AgentConfig.skill_budget_chars: int = DEFAULT_SKILL_BUDGET_CHARS`。
- `prompts.py`：两个装配函数新增 `skills_text: str = ""`；非空时在「== 本次决策 ==」之前插入 `"== 技能提示 ==\n{skills_text}\n\n"`；为空时输出与现状逐字相同。
- 公私分离：技能正文是通用策略、不含本局私有信息；装配按调用进行，狼夜私有调用与昼间公开调用各取各的阶段。狼人的昼间技能（悍跳/倒钩）进入公开发言 prompt 是**预期**——它们是公开发言的策略。

## 5. 入口

- **registry**：`GameRegistry(store, timeouts, agent_port_factory, skill_library=None)`；`create()` 用 `self._skill_library or default_library()` 做 `validate_profiles`；`_build_agent_port` 传库给 `build_agent_port`。`agent_port_factory` 签名不变。
- **API**：`create_app(..., skills_dir: Path | None = None)`：`SkillLibrary.load([BUILTIN_SKILLS_DIR] + ([skills_dir] if skills_dir else []))` 注入 registry；环境变量 `AGENTHOWL_SKILLS_DIR` 作为 `main.py` 默认（`app/main.py` 里读取，仅此一处）。`CreateGameRequest.agents[*].skills` 随 `AgentProfile` 自动生效；回显同。
- **CLI**：`--skills-dir PATH`（单个目录）；`_wire_game(config, *, human_seat, agents, library)`；`main` 构建 `library`，`validate_profiles(agents, n, library)`；`render_agent_roster` 每座位追加 `技能 a,b`（无技能不显示）。
- **Makefile**：`SKILLS_DIR ?=` 并入命令片段。

## 6. 首批内置技能（`backend/skills/`）

| name | roles | phases | 要点 |
|---|---|---|---|
| `seer-badge-flow` | SEER | SHERIFF_ELECTION SHERIFF_PK DAY_SPEECH | 上警报查验、金水/查杀口径、警徽流两夜顺序、何时留验 |
| `seer-vs-claim-jump` | SEER | SHERIFF_ELECTION SHERIFF_PK DAY_SPEECH VOTE | 对跳时的逻辑：查杀优先、点出对方漏洞、归票节奏 |
| `wolf-claim-jump` | WEREWOLF | SHERIFF_ELECTION SHERIFF_PK DAY_SPEECH | 悍跳预言家：何时值得跳、编查验的原则、与队友配合 |
| `wolf-counter-hook` | WEREWOLF | DAY_SPEECH VOTE | 倒钩：站真预言家、卖队友换信任、后期反水时机 |
| `wolf-charge` | WEREWOLF | DAY_SPEECH VOTE | 冲锋：为悍跳狼站台、带节奏归票好人 |
| `wolf-lay-low` | WEREWOLF | DAY_SPEECH VOTE | 划水：低存在感、跟大票、不出逻辑漏洞 |
| `wolf-team-kill` | WEREWOLF | NIGHT_WEREWOLF | 刀口：优先真预言家/高威胁神职、避免刀被守/被救、与队友提案一致 |
| `witch-potion-timing` | WITCH | NIGHT_WITCH DAY_SPEECH | 首夜救/不救、毒药留给查杀、何时报银水 |
| `hunter-shot-target` | HUNTER | HUNTER_SHOOT DAY_SPEECH | 枪口：查杀 > 悍跳者 > 划水位；何时跳猎人 |
| `sheriff-herding` | 全部 | SHERIFF_ELECTION DAY_SPEECH VOTE LAST_WORDS | 争警长的理由、发言顺序选择、归票、警徽移交 |
| `vote-discipline` | 全部 | VOTE VOTE_PK | 不弃票、跟真预言家、平票时的选择 |
| `logic-chain` | 全部 | DAY_SPEECH VOTE | 用票型与发言前后矛盾找狼、金水链 |
| `side-taking` | 全部 | DAY_SPEECH VOTE SHERIFF_ELECTION | 对跳时如何站边、警徽流验证、改站边的代价 |
| `strategy-adaptation` | 全部 | DAY_SPEECH VOTE | 论文方法：对每人估计身份概率；被怀疑时 Support、锁定目标时 Attack |

写作约束：只给策略；不诱导非法行动（自爆/投票/用药均由引擎裁决合法性）；不含「你知道谁是狼」等越权信息；狼人技能不得指示在公开发言里泄露夜间私谋。

## 7. 测试（零 IO 零 mock；技能目录用 `tmp_path`）

`tests/test_agent_skills.py`：`parse_skill_md` 正常/各类错误（name 与目录不符、非法字符、未知角色/阶段、priority 非整数、正文超长、缺 frontmatter）；`SkillLibrary.load` 同名覆盖、`resolve("*")`、未知名报错；`select_skills` 过滤与排序；`assemble_skills` 预算整篇取舍与返回名单；`skills_index_text`。
`tests/test_builtin_skills.py`：遍历 `backend/skills/*/SKILL.md`：能加载、名与目录一致、roles/phases 合法、正文 ≤ 600 字、每篇 phases 非空、不含违规短语（`"你知道"`、`"上帝视角"`、`"无视规则"`）；14 篇齐全。
`tests/test_agent_prompts.py`：`skills_text=""` 输出与旧断言相同；非空时出现在「== 本次决策 ==」之前。
`tests/test_agent_player.py`：`ScriptedLLMClient` 捕获 user/system prompt：系统段含索引；预言家 DAY_SPEECH 含 `seer-badge-flow` 正文、不含 `wolf-*`；狼 NIGHT_WEREWOLF 私有调用含 `wolf-team-kill`、不含 `wolf-claim-jump`；狼 DAY_SPEECH 公开调用含 `wolf-claim-jump`、不含 `wolf-team-kill`；`last_skills_used`。
`tests/test_agent_profile.py`：`skills` 字段；`validate_profiles(..., library)` 未知名报错。
`tests/test_api_lobby.py`：未知技能 400；合法技能回显。
`tests/test_cli_play_watch.py` / `test_cli_render.py`：`--skills-dir` 覆盖内置；档案表含技能名。
`tests/test_agent_bench.py`：env 门控——`wolf-team-kill` 开/关各 1 局，输出空刀率（不断言方向，只断言可运行并打印）。

## 8. 明确不在范围

- `scripts/` 执行、`references/` 装配；技能自动学习/生成；技能市场。
- 技能依赖/互斥；对局中切换技能；每技能独立预算。
- 外部 Agent（`player_type=AGENT`）的技能。
