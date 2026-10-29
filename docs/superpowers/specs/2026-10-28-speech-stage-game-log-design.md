# 发言阶段重排：状态桌面 + 右栏「发言台 / 对局记录」设计

> 设计稿：Claude Design 项目「AgentHowl 游戏化」第 8 轮（`docs/design/gamified-2026-10-27/options/{8a,8b,8c}.html`，
> 导出于 2026-10-28）。本文覆盖 `2026-10-28-ui-gamification-design.md` 的 §4.3（发言气泡）、§4.6（事件流抽屉）
> 与 §4.5 里「发言顺序」「村镇公告」两张卡在发言阶段的出现规则；其余章节不变。起因：issue #189。

## 1. 意图

现在的对局页把发言正文放在锚在座位上的羊皮纸气泡里。气泡遮桌面；引擎在 `PLAYER_SPOKE` 落地那一刻就把
发言权交给下一位，气泡随之换人，静音时刚说完的那句在桌上一帧都不出现；完整发言流藏在舞台最右 28px 的竖向页签
后面，没人知道它在那里。回放静音时发言一闪而过，暂停也看不到正文（#189）。

设计稿第 8 轮的决定（用户已定，原文见 8a 顶部说明）：

1. 去掉座位弹出的气泡，圆桌不再被遮挡；每个座位名字下方加一行状态（发言中 / 已发言 / 待发言 / 出局）。
2. 右栏上半是「发言台」：当前发言人的大头像 + 身份牌色环 + 计时环 + 正在生成的文字；下半是「对局记录」：
   当前视角可见的全部事件按时间倒序混排——发言、上警 / 警长、投票票型、死亡 / 遗言、自爆、日夜切换，以及只有
   我能看到的夜间行动（如预言家验人结果）；按日分隔，顶部可按类型过滤。
3. 村镇公告缩成桌心一行，墓地 / 警徽流都可从记录中追溯。
4. 底部 HUD 不变，轮到我时输入框仍在 HUD。

**目标**：任何视角、任何时刻，右栏都能读到当前这句和之前所有的话；回放静音时发言可读完。
**非目标**：不改引擎、事件形状、服务端可见性；不改 HUD、绳索条、结算页、大厅；手机端仍无设计稿。
**反目标**：任何「viewer === X 才显示」的前端分支；为了填满设计稿里的占位而捏造数据（提示语、模型名、时间）。

## 2. 范围与裁定

设计稿只画了白天发言（8a 旁听 / 8b 轮到我）与卡牌皮肤（8c）。下面这些是建造者判断，用户可推翻：

| # | 判断 | 理由 |
|---|---|---|
| R1 | 「发言台 + 对局记录」结构用于**所有有发言者的阶段**：白天发言、竞选发言（`SHERIFF_ELECTION speech`）、警长 PK、遗言。发言台头部标签分别为「发言中 / 竞选发言 / 遗言」，沿用 `SpeechBubble` 现在的三种 kind | 8a 的「下一步」已说明要同步到竞选 / PK / 遗言；留着气泡只给三个阶段用会同时维护两套发言展示 |
| R2 | **对局记录在所有阶段都在右栏下半**（夜间、投票、公布死讯也在）；右栏上半在发言阶段是发言台，其它阶段是现有的 `InfoRail` 卡片（最多 2 张，上半区 `max-height: 48%` 内滚动） | 回放拖到任何位置都该能读历史；现有卡片（票型 / 夜晚流程 / 验人记录 / 药瓶 / 墓地）仍有信息价值 |
| R3 | 宽屏（≥1100px）**删除事件流抽屉与 28px 页签**；`SpeechFeed` 由 `GameLog` 取代。窄屏（<1100px）右栏隐藏，`EventDrawer` 壳保留，页签文案改「发言台 · 对局记录 ▸」，抽屉里就是同一份右栏 | 记录已常驻右栏，抽屉在宽屏上是重复入口 |
| R4 | 记录行的时间列显示 `#seq`（mono），不显示时间 | 事件 `ts` 是逻辑时钟（≈ seq 秒），显示成钟点是捏造 |
| R5 | 过滤页签：全部 / 发言 / 投票 / 夜晚；事件流里存在 `SEER_CHECKED` 时多一个「验人」。文案不写「我的」 | 零过滤：页签出不出现只看数据；上帝视角同一个页签列出所有验人 |
| R6 | 8b 的「提示」行用确定性文案：「本轮自称：5号 警长、2号 预言家」——取 `logEntries` 里与最新一条同一个 `day` 的发言条目的 `claim`（去重保留最新），无人声明写「本轮尚无人声明身份」；队友信息已在 HUD 身份牌，不重复 | 设计稿那句是 LLM 式总结，前端没有这个数据；「本轮」不能靠 `ROUND_STARTED`（见 R12） |
| R7 | 发言台的「{model} · 声线：{…}」行只在 `meta.agents[seat]` 存在时渲染（上帝 `/meta` 带档案，玩家 / 观众是空对象）；model 去掉 `provider/` 前缀；声线：`voice.mode === "preset"` 写 `speaker`，`design` 写「定制」，无 voice 写「不配音」 | 数据驱动，不加视角分支 |
| R8 | 发言者尚未开口时发言台显示该座位 + 斜体「正在组织语言…」，本人回合写「轮到你发言…」；刚说完的上一句在记录顶部（最新在上）。**不**做 #189 里「上一句留在台上」 | 设计稿把「读上一句」的职责交给了记录；再在台上保留会和「发言中」语义打架 |
| R9 | 回放静音时按阅读时长停留（#189 ①）**纳入本次**：`readingDwellMs` 门控 | 设计解决「看得见历史」，不解决「来得及看」，两者缺一回放仍不可用 |
| R10 | 右栏宽度：≥1200px `minmax(400px, 42%)`，1100–1199px `minmax(360px, 40%)`；设计稿 1440 宽时右栏 700px（约 49%），桌子 500px | 桌子区 `--table-max: 560px` 需要 ≥ 600px；42% 在 1440 下右栏 605px、桌子区 ≈ 790px |
| R11 | 座位状态行只在设计稿画了的发言阶段写「发言中 / 已发言 / 待发言」；投票类阶段写「已投 / 未投 / PK 中 / 无票」；竞选报名写「上警 / 退水」；夜间不写；出局永远写「出局」 | 「圆桌只留状态」要在每个阶段都有意义；文案取自现有 `PlayerStatusPanel` / 票型卡 |
| R12 | 记录的「第 N 天 / 第 N 夜」只从**事件流里可复现的信号**推导（§6.1 的日夜扫描规则），不读 `state.round`、不依赖 `ROUND_STARTED` / 夜间 `PHASE_CHANGED` | 直播时玩家 / 观众收不到这两种事件（`engine.py::_begin_night` 发 GM_ONLY，前端靠 `phase_change` 帧改 `head.round/phase`，见 `store/game.ts::applyPhase`）；`logEntries(events, state)` 必须对同一份事件流给同一份结果，回放与直播才一致 |

## 3. 布局（覆盖原 §4.1 舞台部分）

```
┌──────────────────────── header 48px ─────────────────────────┐
│ ┌plaque┐                               │ ┌─ 发言台 / 信息卡 ─┐ │
│ │      │   table area (flex 1)         │ └───────────────────┘ │
│ └──────┘                               │ ┌─ 对局记录 ────────┐ │
│                                        │ │  (minmax(0,1fr))  │ │
│                                        │ └───────────────────┘ │
├──────────── bottom: HUD 150px / rope bar 72px ────────────────┤
```

- `GamePage.module.css`：`.stage` 列改 `minmax(0,1fr) minmax(400px, 42%)`（见 R10），去掉第三列 28px；
  `gap 16px 20px; padding: 16px 24px 16px 24px`。`.rail` 改为 `display:grid; grid-template-rows: auto minmax(0,1fr);
  gap: 12px; padding-top: 0; min-height: 0`（原 `padding-top: 56px` 是给木牌让位，木牌在桌子区一侧，右栏不需要）。
- `.rail > .railTop`：`max-height: 48%; overflow-y: auto; min-height: 0`，发言阶段里放 `SpeakerStand`，其它阶段放
  `InfoRail`（`railCards` 最多 2 张）。
- `.rail > .railLog`：`GameLog`，`min-height: 0`。
- 1100–1199px：第二列 `minmax(360px, 40%)`。<1100px：`.stage` 列 `minmax(0,1fr) 28px`，右栏隐藏，`EventDrawer`
  页签「发言台 · 对局记录 ▸」，抽屉内容 = 同一份 `.rail`（上半 + 记录）。<900px 规则不变（仍走抽屉）。

## 4. 桌面：只留状态

### 4.1 座位状态行

- `lib/seatModel.ts`：`SeatModel` 增加 `status: { text: string; tone: SeatStatusTone }`，
  `SeatStatusTone = "now" | "done" | "wait" | "dead" | "none"`。由新纯函数
  `seatStatus(state, seat, input: { speaking: number | null; votes: Record<number, number | null> })` 计算，放
  `src/lib/seatStatus.ts`：
  - `!player.alive` → 「出局」`dead`。
  - 发言类阶段（`DAY_SPEECH`、`LAST_WORDS`、`SHERIFF_PK`、`SHERIFF_ELECTION` 且 `election_stage === "speech"`）：
    座位在 `speech_order` 里 → `seat === speaking` 「发言中」`now`；`index < speech_idx` 「已发言」`done`；否则「待发言」
    `wait`。不在顺序里 → `""` `none`（PK 时的非候选人、遗言阶段的其他人）。「正在出声优先」与 #185 一致：
    `speaking` 由 GamePage 传入（`voicingActor ?? turnSpeaker`）。
  - 投票类阶段（`VOTE`、`VOTE_PK`、`SHERIFF_ELECTION/SHERIFF_PK` 且 `election_stage === "vote"`）：PK / 警 PK 的候选
    人 → 「PK 中」`now`；`!can_vote` → 「无票」`none`；`votes[seat]` 存在 → 目标非 null 写「已投 {t}号」、null 写「弃票」，
    `done`；否则「未投」`wait`。`votes` 即 `voteTally` / `sheriffVoteTally` 的 `votes`（voter → target）。
  - `SHERIFF_ELECTION` 报名阶段（`election_stage === "candidacy"`）：`sheriff_declared` 含且 `sheriff_withdrawn` 不含 →
    「上警」`now`；`sheriff_withdrawn` 含 → 「退水」`done`；否则 `""`。
  - 其它阶段（夜间、`DEATH_ANNOUNCE`、`EXILE`、`LOBBY`、`GAME_OVER`）→ `""` `none`。
- `GameTable`：座位按钮里名字下方加 `<span className={styles.status} data-tone={…}>`（10px，`now` 金 `--ah-gold`、
  `done` `--ah-text-muted`、`wait` `--ah-text-dim`、`dead` `--ah-dead-fg`）；空字符串仍占一行高（10px line-height）避免
  座位跳动。`aria-label` 追加状态文案（`seatLabel` 里 `发言中` 一项改为取 `status.text`）。
- `CardBoard`（8c）：名字移到 `bottom: 18px`，状态行 `bottom: 5px`，同样 `data-tone`。
- 删除 `SpeechBubble`（两种 layout）与 `GameTable.module.css` 里的气泡样式；`GameTableProps.speech` 删除；
  `lib/tableText.currentSpeechItem` 保留给发言台用。

### 4.2 桌心一行 `speechProgress`（替代 `bubble` 与「村镇公告」卡）

`stageContent` 的 `bubble` 分支改为：

```ts
| { kind: "speechProgress"; lastNight: string | null; lastTally: string | null;
    done: number; total: number; next: number | null }
```

- `lastNight`：`townNews(events, state)` 的「昨夜」行值（「平安夜」/「3号、7号 死亡」），没有则 null。
- `lastTally`：上一轮 `VOTE_RESULT` 的 `4号 ·4 ｜ 8号 ·2`（现有 `lastVoteSummary` 去掉 `← 投票人` 部分）。
- `done = speech_idx`，`total = speech_order.length`，`next = speech_order[speech_idx + 1] ?? null`。
- `TableCenter` 渲染两行 11px/1.7 `--ah-text-dim`，居中在桌心篝火下方（设计稿 8a：`top 445px / width 260px`）：
  第一行「昨夜 {lastNight}（绿 / 红）· 昨日票型 {lastTally}」（两者都空则整行不渲染）；第二行「发言进度 **{done}** / {total}
  · 下一位 {next}号」，`next === null` 写「· 最后一位」。
- `CardBoard` 的 `showCenter` 对 `speechProgress` 为 true，渲染在牌阵下方一行（8c：`top 656px`，宽同牌阵，内容合并成一行用 `·` 连接）。
- `railCards`：删除 `"order"` 卡（`PlayerStatusPanel` 整个删除）；`DAY_SPEECH` 分支里 `news` 保留给非发言阶段（发言阶段上半区本就不渲染卡片）。`MAX_CARDS` 改 2。

## 5. 右栏上半：发言台 `SpeakerStand`（`src/components/SpeakerStand/`）

出现条件（GamePage）：`speaking !== null && SPEAKING_PHASES.has(phase)`（`SHERIFF_ELECTION` 还要
`election_stage === "speech"`）。否则上半区渲染 `InfoRail`。

Props（零过滤，无 viewer）：

```ts
interface SpeakerStandProps {
  seat: number; name: string; role: RoleType | null; avatar: string | null;
  kind: "speech" | "campaign" | "last_words";
  /** 该座位这一轮的发言（currentSpeechItem），还没说为 null。 */
  item: SpeechItem | null;
  /** 本人回合（GamePage 由 viewer 推出，与原 SpeechBubble.mine 同义）。 */
  mine: boolean;
  deadline: number | null; limit: number | null; now?: () => number;
  voicing: boolean;
  /** meta.agents[seat] 有则传（R7）。 */
  agent?: { model: string; voice: string } | null;
  /** 8a 底行「之后 8号 → 9号 → 你」的数据：发言顺序里当前位之后的座位。 */
  queue: number[];
  /** R6：本轮已声明的身份，[seat, role]。 */
  claims: [number, RoleType][];
}
```

**旁听 / 他人发言（8a / 8c 右上）**：木牌面板（`.ah-wood` 底、`2px solid --ah-gold` 边、`0 0 30px rgba(240,192,96,.18)`），
`grid-template-columns: 120px 1fr; gap 18px; padding 16px 18px`。

- 左：104px 圆环 `conic-gradient(--ah-gold 0 {p}%, #2a1d14 {p}%)`，`p = left/limit`（无 `limit` 或 `deadline` → 100%），
  内 94px `RoleToken variant="seat"`（有头像显示头像）；下方 heading 18px「{seat}号 · {name}」；mono 12px 金「{left}s」
  （无 deadline 不显示）。倒计时逻辑沿用 `SpeechBubble.useLeft`（提到 `src/lib/useCountdown.ts`）。
- 右上标签行：胶囊「发言中 / 竞选发言 / 遗言」（`--ah-fire` 底 `#2b1a08` 字 11px 700）；`item.claim` → 描边金签「自称 {ROLE_ZH}」；
  `item.badgeFlow` 非空 → `tag tag-neutral`「警徽流 a → b」；`agent` → 11px muted「{model} · 声线：{voice}」；右侧
  `voicing` 时六根跳动音柱（沿用 `SpeechBubble` 的 `.bars` 动画）。
- 正文：羊皮纸块 `#e9dcc2` / `#2b2116` 14px/1.85 `min-height 96px; max-height 40vh; overflow-y:auto`，`item.content ?? item.text`；
  `voicing` 时末尾闪烁光标 ▍；`item === null` → 斜体 `--ah-parch-muted`「正在组织语言…」（`mine` 时「轮到你发言… /
  轮到你时在此陈述竞选理由…（草稿会保留）/ 写下遗言…」，沿用现有 `PLACEHOLDER`）。
- 底部 12px `--ah-text-dim`：「之后 {queue.join(" → ")}」，`queue` 为空写「最后一位 · 发完即进入{投票 | 下一阶段}」
  （`kind === "speech"` 写投票，其余写下一阶段）。

**轮到我（8b）**：`mine && item === null` 时切紧凑版：`display:flex; gap 18px; align-items:center`；左 84px 环（76px 徽记）；
中：heading 20px「{seat}号 · {name}」+ 胶囊「轮到你」+ 12px muted「{最后一位发言 · 发完即进入投票 | 之后 N号 → M号}」，
下一行 13px `--ah-text-dim`「本轮自称：…」（R6）；右：mono 28px 金「{left}s」+ 11px「剩余」。输入框仍在 HUD。
我说完后（`item !== null`）回到标准版，胶囊「发言中」。

## 6. 右栏下半：对局记录 `GameLog`（`src/components/GameLog/`）

### 6.1 选择器 `logEntries(events, state): LogEntry[]`（`src/lib/gameLog.ts`，纯函数）

```ts
type LogGroup = "speech" | "vote" | "night" | "seer" | "flow";
interface LogEntry {
  seq: number; type: EventType; group: LogGroup;
  /** 两字签：发言 / 遗言 / 上警 / 退水 / 竞选 / 警长 / 方向 / 警徽 / 投票 / 票型 / 放逐 / 天亮 / 开枪 / 自爆 / 翻牌 /
   *  守护 / 刀口 / 解药 / 毒药 / 验人 / 结算 / 发牌 / 跳过 / 开局 / 终局 */
  label: string;
  /** 行的主色（CSS 变量名，如 "--ah-wolf"），签边框 / 图标 / 私有行左边线共用。 */
  color: string;
  text: string;            // renderEventText 去掉【…】/ [GM] 前缀后的正文
  actor_seat: number | null;
  visibility: Visibility;
  /** 发言 / 遗言行多出来的字段（同 SpeechItem）。 */
  speech?: { content: string; claim: RoleType | null; badgeFlow: number[]; kind: "speech" | "last_words" };
  /** 「第 N 天」/「第 N 夜」：这条事件发生时所处的日夜；相邻两条不同则在它们之间画分隔线。 */
  day: string;
}
```

- 顺序：**按 seq 倒序**（最新在上）。
- `day` 的日夜扫描（R12，正序扫一遍，维护 `cur: { kind: "start" | "night" | "day"; n: number }`，初值 `start, 0`）：
  - `ROUND_STARTED` → `night, payload.round`（上帝 / 回放有这条，直接以它为准）；
  - `PHASE_CHANGED` 且 `isNight(to)` → 若 `cur.kind !== "night"` 则 `night, cur.n + 1`；
  - 夜间组事件（`GUARD_PROTECTED`、`WOLF_KILL_*`、`WITCH_*`、`SEER_CHECKED`、`NIGHT_RESOLVED`）→ 若 `cur.kind !== "night"`
    则 `night, cur.n + 1`（直播时预言家 / 狼只收到自己的夜间事件，靠它们开夜）；
  - 夜间组事件含 `ROLE_SKIPPED`（被跳过的女巫 / 守卫 / 预言家只收到这一条 ROLE_SELF 事件，它要能开夜）；
  - `PHASE_CHANGED` 且 `!isNight(to)` → 若 `cur.kind === "night"` 则 `day, cur.n`，若 `start` 则 `day, 1`，若已是 `day` 不变
    （从不加天）；
  - `DEATH_ANNOUNCED` → 同上，**但**扫描要记住「这一天是否已经天亮过」（`dawned`）：已天亮过的白天再遇到天亮 → `day, cur.n + 1`。
    观众（只有 PUBLIC 事件）一整夜收不到任何事件，夜从未被「开」过，下一次天亮时仍在白天，没有这条规则整局都是「第 1 天」
    （评审 C1）。第 1 轮上帝流里 `PHASE_CHANGED→SHERIFF_ELECTION` 先于 `DEATH_ANNOUNCED` 开了白天，此时 `dawned=false`，
    天亮不加天；
  - 其余事件不改 `cur`。`day` 文案：`start` → 「开局」，`night` → 「第 N 夜」，`day` → 「第 N 天」。
  - 同一份事件流在上帝 / 回放（有 `ROUND_STARTED`）与直播玩家（没有）下，公开事件落到的日夜标签必须相同——测试用金样
    fixture 的全量流分别与「只剩 PUBLIC」「PUBLIC ∪ ROLE_SELF」「PUBLIC ∪ WOLVES」三种过滤流逐条比对（「非 GM_ONLY」
    一种不够：狼每夜都有 `WOLF_KILL_PROPOSED`，会掩盖观众流的缺口）。
- 跳过不入记录：`ROUND_STARTED`、`PHASE_CHANGED`、`VOTE_STARTED`（信息已由分隔线 / 票型行承担）。
- 分组与签（`label` / `group` / `color`）：
  - `PLAYER_SPOKE` 发言 speech `--ah-gold`；`LAST_WORDS` 遗言 speech `--ah-wolf`。
  - `SHERIFF_CANDIDACY` 上警（`running=false` 写「不上警」）/ `SHERIFF_WITHDREW` 退水 / `ELECTION_STAGE_CHANGED` 竞选 /
    `SHERIFF_VOTE_STARTED` 竞选 / `SHERIFF_VOTE_CAST` 投票 / `SHERIFF_ELECTED` 警长 / `SHERIFF_DIRECTION_SET` 方向 /
    `BADGE_PASSED`、`SHERIFF_BADGE_LOST` 警徽 → group vote，color `--ah-gold`。
  - `VOTE_CAST` 投票 / `VOTE_RESULT` 票型（文案「4号 ·4 ｜ 8号 ·2 → 4号 出局 | 平票 …」，由 `VOTE_RESULT.tally` 生成）/
    `PLAYER_EXILED` 放逐 / `IDIOT_REVEALED` 翻牌 → vote，color `--ah-fire`（放逐 `--ah-wolf`）。
  - `DEATH_ANNOUNCED` 天亮（有死亡 `--ah-wolf`，平安夜 `--ah-ok`）/ `HUNTER_SHOT` 开枪 `--ah-god` / `WOLF_SELF_DESTRUCT`
    自爆 `--ah-wolf` → group flow。
  - `GUARD_PROTECTED` 守护 / `WOLF_KILL_PROPOSED`、`WOLF_KILL_DECIDED`、`WOLF_KILL_REVOTE` 刀口 / `WITCH_SAVED` 解药 /
    `WITCH_POISONED` 毒药 / `WITCH_POTION_CONSUMED` 毒药 / `NIGHT_RESOLVED` 结算 → group night，颜色沿用
    `nightSummary` 的 `--ah-line-*` / `--ah-wolf`。
  - `SEER_CHECKED` 验人 → group **seer**，`--ah-line-seer`。
  - `GAME_CREATED` 开局 / `GAME_STARTED` 开局 / `ROLES_ASSIGNED` 发牌 / `ROLE_SKIPPED` 跳过 / `GAME_OVER` 终局 → flow，
    `--ah-text-muted`（终局 `--ah-gold`）。
- `text`：复用 `renderEventText`，去掉开头的 `【…】`、`[GM] `、`  `（两空格缩进）与 `💥 `，发言 / 遗言行的 `text` 不用
  （正文在 `speech.content`）。`renderEventText` 从 `select.ts` 导出（目前是文件内函数）。

### 6.2 组件

- 面板：`rgba(22,27,40,.9)` 底、`1px solid --ah-panel-edge`、radius 8，`grid-template-rows: auto minmax(0,1fr)`。
- 头：heading 15px「对局记录」+ 12px muted「你可见的全部事件 · 最新在上」+ 右侧过滤签（`role="tablist"`，当前项
  `#2a3042` 底）：全部 / 发言（speech）/ 投票（vote）/ 夜晚（night）/ 验人（seer，仅当有 seer 条目）。过滤是组件内
  `useState`，默认「全部」。
- 列表 `overflow-y:auto; padding 6px 16px`，最新在上，不做自动滚动（新条目出现在顶部，用户滚到下面看旧记录时不被打断）。
  有未读新条目且 `scrollTop > 48` 时顶部显示胶囊「↑ 有 N 条新记录」（沿用 `SpeechFeed` 的 unread 逻辑，方向反过来）。
- 日夜分隔：两侧 1px `--ah-panel-edge` 线 + 居中 heading 13px「第 N 天 / 第 N 夜 / 开局」；在相邻两条 `day` 不同处渲染，
  列表最顶也渲染当前这段的标题。
- 事件行：`grid-template-columns: 40px 1fr; gap 12px; padding 6px 0`：左 36px 图标（flow / vote 用 Unicode 字形表：
  天亮 ☀、结算 ☾、警长 / 警徽 ★、票型 / 投票 ⚖、放逐 ✕、开枪 ➶、自爆 💥、翻牌 ◇、竞选 / 上警 / 退水 / 方向 ✦、
  开局 / 发牌 / 跳过 ·、终局 ⚑；night / seer 行用 24px `RoleToken role=… variant="outline"`），
  右：描边签 `label`（11px，`border-color/color` 取 `color`）+ 12px `--ah-text` 正文 + `#seq` mono 11px `#5a5f6a` 右对齐。
  `visibility !== "PUBLIC"` 的行加 `border-left: 2px solid var(color)`（原 §4.6 私有行规则）。
- 发言行：`padding 8px 0; border-top 1px dashed --ah-panel-edge`；左 36px `RoleToken` seat 变体（角色按 `rolesKnown` /
  `knownRoles` 同 `SpeechFeed` 现逻辑）；右：12px 金「{seat}号 {name}」+ 签（遗言 红签「遗言」；`claim` → 金签
  「自称 {ROLE_ZH}」；`badgeFlow` → 中性签）+ `#seq`；下一行 13px/1.7 正文。
- 回放：`cursor` 非 null 时 `seq === cursor` 的行 `data-current`（左侧 2px 金线 + 底色 `rgba(240,192,96,.08)`），游标因
  拖动 / 单步 / 翻页变化时 `scrollIntoView({ block: "nearest" })`；播放中的自然推进不滚（新条目在顶）。
- 空：「尚无记录」。

Props：`{ entries: LogEntry[]; state: GameState; cursor: number | null; avatars; knownRoles }`。`entries` 由 GamePage 用
`visibleEvents`（已按游标截断）算，和原 `SpeechFeed` 的截断语义相同（不是信息隔离）。

## 7. 回放：静音时按阅读时长停留（#189 ①）

- `src/lib/readingDwell.ts`：`readingDwellMs(event: Event, speed: number): number`——`PLAYER_SPOKE` / `LAST_WORDS`：
  `clamp(1500 + content.length * 150, 1500, 30000) / speed`（150 ms/字 ≈ 每秒 6–7 个汉字），其它事件 0。
- `GamePage` 回放门控改为：
  ```ts
  (seq) => {
    const parts = manifestRef.current[String(seq)];
    if (parts && useVoice.getState().enabled) return useVoice.getState().playSeq(gameId, seq, parts, auth);
    const ms = readingDwellMs(eventBySeq(seq), useGameStore.getState().speed);
    return ms > 0 ? dwell.sleep(ms) : null;
  }
  ```
  `dwell` 是一个可取消的 sleep（`src/lib/dwell.ts`：`sleep(ms)` 返回 promise，`cancel()` 让所有挂起的 promise 立即
  resolve）。`replayControls` 的 `onPause / onCursor / onStep / onLive` 在 `voice.clear()` 之后再 `dwell.cancel()`
  （`VoiceClearControl.clear` 由 GamePage 包一层同时做两件事，`replayControls` 签名不变）。
- 开语音且该 seq 有配音：行为与现在一致；开语音但该 seq 无配音：走阅读停留。

## 8. GamePage 装配

- 删除 `speech` / `bubbleItems` / `bubbleKind` 相关代码；新增：
  - `standSeat = speaking`（已有）；`standItem = currentSpeechItem(speechItems(visibleEvents), speaking)`；
  - `queue = view.speech_order.slice(view.speech_idx + 1)`（正在出声的是上一位时，`speech_idx` 已指向下一位，队列从它开始；
    这时 `queue` 应为 `speech_order.slice(speech_idx)`——用 `speech_order.indexOf(speaking) + 1` 取，统一两种情况）；
  - `claims`：`entries` 里 `day === entries[0].day` 且 `speech?.kind === "speech"` 且 `claim !== null` 的
    `[actor_seat, claim]`，按座位去重保留最新（R6 / R12）；
  - `agent`：`meta.agents[String(seat)]` 有则 `{ model: 去前缀, voice: … }`（R7）；`useGameStore((s) => s.meta)`。
  - `entries = logEntries(visibleEvents, view)`。
- 右栏 JSX：
  ```tsx
  <div className={styles.rail}>
    <div className={styles.railTop}>{stand ?? <InfoRail … />}</div>
    <div className={styles.railLog}><GameLog entries cursor state avatars knownRoles /></div>
  </div>
  ```
  窄屏 `EventDrawer` 的 `children` 换成同一段（`top` 插槽去掉）。
- `seatModel` 调用加 `votes`（voter → target，取 `voteTally/sheriffVoteTally(...).votes`；非投票阶段传 `{}`）。

## 9. 零过滤与约束

- `SpeakerStand` / `GameLog` / `seatStatus` / `logEntries` 的参数里没有 `viewer`；`mine` 由 GamePage 推出（原 §4.10 允许的
  唯一位置）。`grep -n "viewer" src/components/SpeakerStand src/components/GameLog src/lib/gameLog.ts src/lib/seatStatus.ts`
  为空作为检查项。
- 「验人」页签、「{model} · 声线」行、夜间私有行：都只看事件 / meta 里有没有数据。
- 不改 `engine/`、后端、事件形状；`make fixtures` 不需要重跑。
- 中文注释 / 英文标识符；纯函数进 `src/lib/`；CSS Module 里组合全局类必须 `:global()`。

## 10. 删除清单

`components/GameTable/SpeechBubble.tsx(+test)`、`components/SpeechFeed/*`、`components/PlayerStatusPanel/*`、
`lib/railCards.ts` 的 `"order"`、`stageContent` 的 `bubble` 分支（改 `speechProgress`）、`GamePage.module.css` 的
`.drawerRail`、e2e `screens.mjs` 里点 `button[aria-controls="event-drawer"]` 截抽屉的步骤（改为 1100 宽才截）。
`EventDrawer` 保留（窄屏）。原规格 §4.3 / §4.6 / §10「Agent 长发言放进座位气泡」条目作废，以本文为准。

## 11. 测试

- 纯函数：`seatStatus.test.ts`（每类阶段 × 存活 / 出局 / 发言中优先）；`gameLog.test.ts`（用 `__fixtures__/std_9_kill_all-3.json`
  跑全部事件：每种事件类型落到预期 label / group、倒序、`day` 分隔、跳过的三种类型不出现、`SEER_CHECKED` 为 seer；
  再用同一 fixture 过滤掉 `visibility === "GM_ONLY"` 的流跑一遍，公开事件的 `day` 与全量流逐条相同，`SEER_CHECKED` 落在
  「第 N 夜」而非「开局」）；
  `readingDwell.test.ts`（空正文 1.5 s、200 字 → 30 s 上限、速度 2× 减半、非发言 0）；`dwell.test.ts`（cancel 立即 resolve）；
  `stageContent.test.ts` 的 bubble 用例改 `speechProgress`（`next` 为最后一位时 null；无上一轮票型时 `lastTally` null）。
- 组件：`SpeakerStand.test.tsx`（未开口占位 / 本人占位 / voicing 光标与音柱 / 自称签 / `agent` 缺省不渲染模型行 / 8b 紧凑版 /
  队列文案）；`GameLog.test.tsx`（过滤页签、验人页签按数据出现、`data-current`、私有行左边线、空态）；`GameTable.test`
  与 `CardBoard.test`（状态行文案与 `data-tone`、不再有气泡、`aria-label` 含状态）；`GamePage.test.tsx` 现有 35 条按新
  DOM 更新（右栏出现「对局记录」、发言阶段出现发言台、非发言阶段出现信息卡）；回放门控测试：语音关时发言 seq 的 gate
  返回 promise 且 `onPause` 后立即 resolve。
- e2e：`frontend/e2e/play.mjs` 跑狼 / 预言家 / 民三种座位（HUD 契约不变，应直接通过）；`screens.mjs` 截上帝回放发言 /
  投票 / 夜晚 + 观众直播发言 + 卡牌皮肤 + 1100 宽抽屉，入 `docs/design/ui-speech-stage-2026-10-28/`。
- `cd frontend && npm run check` 以 `$?` 判定。

## 12. 交付

一个 PR：分支 `feat/ui-speech-stage-log`，从 `main`（52dbce3 之后）切出；按用户惯例 Native 执行 + 终审一位新开的
fable 评审；用户在 GitHub 合并。合并后关闭 #189（R8 说明「上一句留在台上」不做）。

## 13. 待用户确认

1. **R1**：竞选发言 / 警长 PK / 遗言三个阶段也立刻改用发言台 + 记录（设计稿还没画这三个状态）。
2. **R2**：非发言阶段右栏 = 现有信息卡（上）+ 对局记录（下）。
3. **R8**：直播静音时发言台显示下一位的「正在组织语言…」，上一句只在记录顶部，不在台上保留。
4. **R10**：右栏占 42%（1440 宽时 605px，设计稿是 700px）。
