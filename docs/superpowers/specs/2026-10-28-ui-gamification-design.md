# 前端游戏化改版 · 暗夜村庄 — 设计文档

> 日期：2026-10-28 · 状态：已批准 · 设计稿：`docs/design/gamified-2026-10-27/`（Claude Design 项目「AgentHowl 游戏化」）· 对照基线：`docs/design/ui-baseline-2026-10-27/` · 上游：`docs/specs/requirements.md` §1.3（硬约束）、§7（前端）；`docs/superpowers/specs/2026-09-23-m3-frontend-design.md`（现有前端架构）、`2026-10-23-human-seat-player-view-design.md`（玩家视角 / ActionBar）

## 1. 目标与交付判据

把现有 Nocturne 风格的前端整体换成设计稿的「暗夜村庄」风格：夜色底、木牌、羊皮纸、篝火金，标题字 ZCOOL XiaoWei；对局页从「三栏 + 发言流」改为「全景圆桌 + 底部 HUD + 右栏信息卡 + 可收起事件流抽屉」。

**不变的部分**：`src/api/`、`src/store/`、`src/engine/`（TS reducer 与金样）、hash 路由、后端。改动只落在 `src/styles/`、`src/pages/`、`src/components/`、`src/lib/` 里的纯选择器，以及 `index.html` 的字体 link。

**交付判据**：

- 5 个可独立合并的 PR（§8），每个 PR `npm run check`（lint + tsc + vitest）全绿，后端测试不受影响。
- 零过滤不变量（规格 §1.3）不被削弱：所有新增选择器只收 `GameState` / `Event[]` / `YourTurn`，视角（GM / 观众 / 座位）只决定「渲染不渲染 HUD」，不决定「显示不显示某条信息」。
- 对局页每个阶段（夜间五个子阶段、警长竞选六个子阶段、白天发言 / 投票 / PK / 遗言、终局、回放）在玩家 / 上帝 / 观众三种视角下都有对应的桌心内容与右栏卡片（§4.4、§4.5 的表格）。
- 桌面优先：≥1200px 还原设计稿；1100px 以下右栏收进抽屉；900px 以下纵向堆叠仍可玩（§4.9）。手机端专门设计不在本次范围。
- 「圆桌 / 卡牌」桌面皮肤可切换并记忆（§7）。
- PR ② 与 ⑤ 完成后用角色感知的 Playwright 回归脚本（上一轮 issue #123 回归用的 `play2.mjs`，不在仓库内；本次把它整理进 `frontend/e2e/play.mjs` 一并提交）跑一遍各角色，并把新基线截图存到 `docs/design/ui-gamified-<日期>/`。

## 2. 设计语言（设计稿 1a / 2a）

### 2.1 色板（`src/styles/tokens.css`）

新 token 一律用 `--ah-` 前缀；旧的 `--color-bg / --color-surface / --color-text / --color-accent / --color-divider` 以及 `--color-neutral-*`、`--color-accent-*` 保留名字但改指向新值（见映射），以便未迁移的组件在过渡期不破。

| token | 值 | 用途 |
|---|---|---|
| `--ah-night` | `#0c0f17` | 页面底色 |
| `--ah-night-deep` | `#06080d` | 登录页地面、最深处 |
| `--ah-panel` | `#161b28` | 深色信息卡底 |
| `--ah-panel-edge` | `#2a3042` | 信息卡描边 |
| `--ah-panel-glass` | `rgba(22,27,40,.9)` | 对局页右栏卡（半透明） |
| `--ah-wood-hi` / `--ah-wood-lo` | `#3a2a1e` / `#24180f` | 木牌渐变（`linear-gradient(180deg, hi, lo)`） |
| `--ah-wood-edge` | `#5a4330` | 木牌描边 |
| `--ah-wood-shadow` | `#140c06` | 木牌下沿硬阴影（`0 6px 0`） |
| `--ah-wood-btn-hi` / `--ah-wood-btn-lo` | `#6b4a2e` / `#4a311c` | 木牌次按钮 |
| `--ah-wood-btn-edge` | `#8a6238` | 次按钮描边、头像环 |
| `--ah-parch` | `#e9dcc2` | 羊皮纸底 |
| `--ah-parch-hi` | `#f6efe0` | 羊皮纸上的输入框 |
| `--ah-parch-edge` | `#b9a582` | 羊皮纸描边 |
| `--ah-parch-shade` | `#c9b998` | 羊皮纸上的进度槽、次级签 |
| `--ah-parch-ink` | `#2b2116` | 羊皮纸上的正文 |
| `--ah-parch-ink-2` | `#5a4a33` | 羊皮纸上的次级文字 |
| `--ah-parch-muted` | `#8a7d66` | 羊皮纸 / 夜色上的弱文字 |
| `--ah-parch-link` | `#8a6a1e` | 羊皮纸上的链接 |
| `--ah-parch-danger` | `#a0493f` | 羊皮纸上的危险 / 倒计时 |
| `--ah-fire` | `#e3a648` | 篝火主色、链接、选中 |
| `--ah-fire-hi` / `--ah-fire-lo` | `#f0b85a` / `#c9842c` | 主按钮渐变 |
| `--ah-fire-edge` | `#7a4f1c` | 主按钮描边 |
| `--ah-fire-shadow` | `#5a3a12` | 主按钮下沿 |
| `--ah-gold` | `#f0c060` | 木牌上的标题字、当前项 |
| `--ah-text` | `#e8dfca` | 夜色上的正文 |
| `--ah-text-bright` | `#f1ead6` | 夜色上的标题 |
| `--ah-text-dim` | `#c9bca0` | 夜色上的次级文字 |
| `--ah-text-muted` | `#a79f8c` | 夜色上的说明文字 |
| `--ah-wolf` / `--ah-wolf-hi` / `--ah-wolf-lo` | `#c9463d` / `#7a2c26` / `#3d1512` | 狼阵营：环色 / 徽记渐变 |
| `--ah-wolf-fg` | `#f6d7d2` | 狼徽记前景 |
| `--ah-wolf-btn-hi` / `--ah-wolf-btn-lo` | `#a8352c` / `#6e1f18` | 血色按钮（刀 / 遗言 / 毒） |
| `--ah-god` / `--ah-god-hi` / `--ah-god-lo` | `#d9a84e` / `#7a5a1e` / `#3b2a0c` | 神职阵营 |
| `--ah-god-fg` | `#fbe7b5` | 神徽记前景 |
| `--ah-villager` / `--ah-villager-hi` / `--ah-villager-lo` | `#9aa3ad` / `#5a5f68` / `#2a2e36` | 村民 |
| `--ah-villager-fg` | `#e6eaee` | 村民徽记前景 |
| `--ah-dead-bg` / `--ah-dead-edge` / `--ah-dead-fg` | `#1b1f2a` / `#3b3f4a` / `#5a5f6a` | 出局座位（虚线 ✕） |
| `--ah-ok` / `--ah-ok-hi` / `--ah-ok-lo` | `#5a9a5a` / `#6fb86f` / `#3f7a3f` | 好人签、解药按钮 |
| `--ah-moon` | `radial-gradient(circle at 40% 35%,#fffbe9,#e8dcb8 60%,#c9b98c)` | 月亮 |
| `--ah-sky-night` | `#141c38` | 夜间阶段页面顶部天色 |
| `--ah-table-night` / `--ah-table-night-edge` | `#2a2a3a` / `#141622` | 夜间桌面 |
| `--ah-night-text` | `#b9c6e8` | 夜间木牌字、视角标签 |
| `--ah-night-muted` | `#6b7590` | 夜间说明文字 |
| `--ah-night-panel` / `--ah-night-panel-edge` | `rgba(16,19,31,.9)` / `#1c2236` | 夜间右栏卡 |
| `--ah-night-wood-edge` | `#3f2f22` | 夜间木牌描边 |
| `--ah-blood-sky` | `#2a1016` | 遗言 / PK / 狼胜结算的天色 |

旧名映射：`--color-bg → --ah-night`、`--color-surface → --ah-panel`、`--color-text → --ah-text`、`--color-accent → --ah-fire`、`--color-accent-2 → --ah-gold`、`--color-divider → rgba(232,223,202,.16)`；`--color-neutral-*` 改成夜色灰阶（900 `#161b28` … 100 `#f1ead6`），`--color-accent-*` 改成篝火阶。旧的 `--ah-line-*`、`--ah-tick-*`、`--ah-ok/warn/err` 保留。

### 2.2 字体

`index.html` 加 Google Fonts link：`ZCOOL+XiaoWei`、`Noto+Serif+SC:wght@400;600;700`、`IBM+Plex+Mono:wght@400;500`（`display=swap`）。token：

- `--font-heading: 'ZCOOL XiaoWei', 'Noto Serif SC', serif` — 标题、木牌、阶段名、角色名、按钮大字
- `--font-body: 'Noto Serif SC', Georgia, 'Songti SC', serif` — 正文、发言
- `--font-mono: 'IBM Plex Mono', ui-monospace, monospace` — id、seq、计数、模型名、座位号角标

离线时按 fallback 回退到系统衬线体，不自托管。

### 2.3 全局组件类（`src/styles/global.css` + `tokens.css`）

| 类 | 设计稿 | 规格 |
|---|---|---|
| `.btn-primary` | 篝火主按钮 | 渐变 `fire-hi → fire-lo`，字 `#2b1a08` 700，描边 `fire-edge`，`box-shadow: 0 0 18px rgba(227,166,72,.35), 0 3px 0 fire-shadow`；`:disabled` 变成 `background:#2a1d14; color:#6b5a44; border:1px dashed wood-edge; box-shadow:none` |
| `.btn-secondary` | 木牌次按钮 | 渐变 `wood-btn-hi → wood-btn-lo`，字 `#f1e6c8`，描边 `wood-btn-edge`，`inset 0 1px 0 rgba(255,220,160,.25), 0 3px 0 #2a1a0e` |
| `.btn-ghost` | 描边按钮 | 透明底、`1px solid wood-edge`、字 `text` |
| `.btn-danger` | 血色按钮 | 渐变 `wolf-btn-hi → wolf-btn-lo`，字 `#fbe0dc`，描边 `wolf`，下沿 `#3d1512` |
| `.btn-ok` | 解药绿 | 渐变 `ok-hi → ok-lo`，字 `#0c1a0c` |
| `.input` | 羊皮纸输入 | 底 `parch`，描边 `parch-edge`，`inset 0 2px 4px rgba(0,0,0,.18)`，字 `parch-ink`，placeholder `parch-muted`；在羊皮纸容器内（`.ah-parch .input`）底改 `parch-hi` |
| `.ah-wood` | 木牌卡 | 渐变木纹、`2px solid wood-edge`、`radius 8`、`0 10px 30px rgba(0,0,0,.5), inset 0 1px 0 rgba(255,220,160,.15)` |
| `.ah-parch` | 羊皮纸卡 | 底 `parch`、字 `parch-ink`、`radius 4`、`0 20px 50px rgba(0,0,0,.5), inset 0 0 80px rgba(120,90,40,.12)` |
| `.ah-panel` | 深色信息卡 | 底 `panel-glass`、`1px solid panel-edge`、`radius 6`、`padding 12px 14px`；标题行 `.ah-panel-head`（11px、`text-muted`、两端对齐） |
| `.ah-plaque` | 阶段木牌 | 木纹、`2px solid wood-edge`、`radius 4`、`0 6px 0 wood-shadow`，标题 heading 20px `gold`，副标 body 12px `text-muted` |
| `.tag-parch` / `.tag-wood` / `.tag-gold` | 羊皮纸签 / 木签 / 金签 | 3px 9px，radius 3 |
| `.seg` | 分段选择 | `1px solid wood-edge`，选中项底 `fire` 字 `#2b1a08` 700 |
| `.nav` | 木栏导航 | 56px，木纹渐变，`border-bottom: 2px solid wood-edge`，`0 6px 20px rgba(0,0,0,.5)`；品牌 heading 22px 字距 2px；链接居中、14px `text-dim`，当前项 `gold` + `2px solid fire` 下划线；右侧「用户名 · 离村」 |
| `.table-parch` | 羊皮纸表格 | 表头 11px 字距 2px `parch-muted`、底线 `2px solid wood-hi`；行底线 `1px dashed parch-edge` |
| `.dialog` | 木牌对话框 | `.ah-wood` + `padding 24px 26px`，标题 heading 22px `gold` |
| `.ah-rule-x/-y` | 保留 | 渐隐分隔线颜色换成 `rgba(232,223,202,.16)` |

### 2.4 角色徽记 `RoleToken`（`src/components/RoleToken/`）

- 七个角色的 24×24 SVG 路径来自设计稿 2a（`options/2a.html` 与原文件脚本里的 `ICON` 表）：WEREWOLF、SEER、WITCH、HUNTER、GUARD、IDIOT、VILLAGER。路径常量放 `src/lib/roleIcons.ts`，与 `RoleType` 一一对应。
- 阵营配色：狼 `wolf-*`，神（SEER / WITCH / HUNTER / GUARD / IDIOT）`god-*`，民 `villager-*`。
- Props：`role: RoleType | null`、`state: "known" | "unknown" | "dead"`、`size: number`、`variant: "seat" | "card" | "parch" | "outline"`、可选 `initial`（未知身份时显示名字首字）、可选 `avatar`（头像 id；有头像时圆内渲染 `<img>` 并把徽记缩成右下角 18px 小章，这样现有上传头像不丢）。
  - `seat`：圆形，径向渐变底 + `3px` 阵营环 + 徽记居中（占径 50%）。
  - `card`：84×112 圆角 6 的竖牌（HUD 身份牌、卡牌皮肤）。
  - `parch`：羊皮纸底、`parch-edge` 环、徽记用阵营色（剧本牌、羊皮纸里的小徽记）。
  - `outline`：透明底、`1.5px` 阵营色环。
  - `unknown`：木纹底、`wood-btn-edge` 环、显示 `initial` 或「?」。
  - `dead`：`dead-bg` 底、`2px dashed dead-edge`、字 ✕ `dead-fg`。
- 现有 `ROLE_ABBR` 文字缩写只保留给纯文本场景（事件流里的 `[狼]` 之类）。

## 3. 页面骨架与导航（设计稿 1b / 1c 顶栏 / 4f）

- `App.tsx` 外壳：`grid-template-rows: 56px minmax(0,1fr)`，导航用 `.nav`。导航项不变（新的一局 / 历史对局 / Agent 档案库 / 模型服务，admin 多一个「用户」），右侧 `用户名 · 离村`，匿名显示「登录」。
- **登录页**（1b）`LoginPage`：全屏 `radial-gradient(ellipse at 50% 0%, #1c2440, night 60%)`；顶部月亮（160px，`--ah-moon`，`0 0 80px 30px rgba(241,234,214,.18)`）；底部两层村庄剪影 + 一盏窗灯（纯 CSS，`LoginPage.module.css`）；中间品牌 heading 54px 字距 4px 与副标「狼 人 嚎 叫 · AI 狼 人 杀」；两根木柱吊着木牌表单，标题「入 村」/「落 户」/「对 暗 号」分别对应 login / register / verify，表单字段与现在相同，主按钮「登 录」/「注 册」/「验 证」，底部两条篝火色链接。错误文案显示在木牌内羊皮纸条上。
- **错误态**（4f）`ErrorState`：`notFound` → 月亮 + `4404` mono + heading「这局已随风散去」+ 说明 + 木牌按钮「回到村志」；`auth` / `forbidden` → 木牌「?」卡 + `4401 / 4403` + 「村口有人守着」+ 篝火按钮「去登录」（匿名）或「回到村志」（已登录但无权）。其余 kind（网络 / 未知）沿用「村口有人守着」的壳换文案。
- **分享对话框**（4f）`ShareDialog`：木牌对话框，标题「传 · 分享对局」，说明行，羊皮纸只读链接 + 木牌「复制」，底部「稍后」+ 篝火「进入对局 →」。
- `ConfirmDialog`、`Drawer`（壳）同步换成木牌 / 羊皮纸风格：`Drawer` 增加 `tone: "wood" | "parch"`，默认 `parch`（4e 的编辑器抽屉），左侧 14px 木轴条，标题区「招 募 告 示」类的 kicker 由调用方传 `kicker`。

## 4. 对局页（设计稿 3a / 3d / 4b–4d / 5a–5c / 7a–7d / 1i）

### 4.1 布局

```
┌──────────────────────── header 48px ────────────────────────┐
│ ┌plaque┐                                                    │
│ │      │   table area (square, flex 1)   │ rail 340 │ tab 28│
│ └──────┘                                 │          │       │
├──────────── bottom: HUD 150px (seat viewer) ────────────────┤
│             or rope bar 72px (GM / spectator / replay)      │
└─────────────────────────────────────────────────────────────┘
```

- `GamePage.module.css`：`grid-template-rows: 48px minmax(0,1fr) auto`；舞台 `grid-template-columns: minmax(0,1fr) 340px 28px`，背景 `radial-gradient(ellipse at 50% 40%, #1a1f30, night 70%)`；夜间阶段（`isNight(phase)`）根元素加 `data-night`，背景换 `radial-gradient(ellipse at 50% 0%, sky-night, #070910 65%)`，木牌 / 右栏卡 / 文字切到 `--ah-night-*`；遗言、PK、狼胜结算加 `data-blood`（`blood-sky`）；猎人开枪加 `data-amber`（`#2a1a10`）。
- 阶段木牌 `PhasePlaque` 绝对定位在舞台左上（24px, 16px），`z-index 2`：第一行 `第 {round} 轮 · {PHASE_ZH}`（夜间写「第 N 夜 · 狼人行动」，终局回放写阶段名不变），第二行副标按阶段：发言「{警长 N号|无警长} · {顺/逆时针} · {alive}/{n} 存活」；竞选「{ELECTION_STAGE_ZH} · {候选数} 人上警 / 逆序 …」；投票「已投 {cast}/{voters} · 警长 1.5 票 / {alive}/{n} 存活」；PK「平票 {a}号 / {b}号 · PK 双方不投票 · 已投 …」；遗言「{seat}号 被公投放逐 · {votes} 票」；夜间「天黑请闭眼 · {角色}请睁眼 / {alive}/{n} 存活」（所有视角都显示这句，因为阶段名本身公开）；回放追加「回放到 seq {cursor} / {total}」。
- 顶栏 `PhaseBar` 换皮：品牌 heading 20px、`game_id` mono、居中状态区（`● 直播 · seq N` 红字 / `▶ 回放 · N 条事件` / 终局「— 游戏结束：{WINNER_ZH} —」金线包围）、右侧视角分段标签（上帝 / 观众 / 玩家 N号，当前项篝火底，仅展示）、分享链接匿名观众多一个「登录」描边按钮、PR ⑤ 加「桌面：圆桌 ▾」。连接状态文案并入居中状态区（连接中… / 连接已断开）。

### 4.2 桌子区 `GameTable`（新组件，取代 `SeatCircle` 的渲染，复用其坐标公式）

- 容器正方形：`width = height = min(可用宽, 可用高)`，居中；桌面圆 `inset 12%`，`radial-gradient(circle at 50% 45%, #4a3524, #2a1d14 70%, #1a110a)`，`6px solid wood-edge`，`0 30px 80px rgba(0,0,0,.7), inset 0 0 60px rgba(0,0,0,.6)`；夜间换 `table-night`。桌心篝火（白天）/ 月亮（夜间）为装饰层。
- 座位：沿用 `positions()`（0 号顶部顺时针，半径 41%）；每个座位 64px `RoleToken variant="seat"` + 左上 22px 羊皮纸座位号角标（mono 700 11px）+ 下方名字 11px。状态：
  - `me`（`viewer === seat`）：环 `fire`，无发光；
  - `speaking`（`currentSpeaker`）：环 `gold`，`0 0 24px rgba(240,192,96,.6)`；
  - `dead`：`RoleToken state="dead"`，整体 `opacity .45`；
  - 夜间暗化：`isNight(phase)` 时，角色未知（`player.role === null`）的存活座位 `opacity .55`；角色已知保持 1。这是纯 state 规则：狼的 state 带狼队角色所以狼队亮、上帝全亮、观众全暗。
  - 徽章：候选人金签「警」（`sheriff_candidates` 且未退水，4b）；警长徽章「警长」金底（`sheriff_seat`）；票数角标（投票 / PK / 警下投票阶段，`voteTally` 的 target → 票数，右上 22px 篝火圆角标）；预言家已验签（`seer_log` 里本座位的记录 → 「好人」绿 / 「狼人」红，7a）；被刀 / 目标签（夜间 `pending_night.wolf_target` 或 `wolf_proposals` 多数目标 → 「目标 · N 票」/「被刀」红签，存在即显示）。
  - 可点击：当 `prompt` 存在且当前工具需要目标（`needsTarget` / vote / shoot）时，存活且合法（`aliveTargets`）的座位 `cursor:pointer`、hover 环 `fire`，点击等同于点 HUD 里的目标胶囊（受控：`selectedTarget` 提到 `GamePage`，`ActionBar` 与 `GameTable` 共享）。
- 桌心 `TableCenter`：由纯函数 `stageContent(state, events, viewer, prompt)` 决定渲染哪一种（§4.4）。

### 4.3 发言气泡 `SpeechBubble`

> **已取代**（2026-10-28）：座位气泡已删除，发言正文改在右栏「发言台」，见 `2026-10-28-speech-stage-game-log-design.md` §5。以下为历史记录。

- 白天发言 / 竞选发言 / 遗言阶段，`currentSpeaker !== null` 时渲染：羊皮纸卡 228–300px，锚在发言者座位朝桌心一侧（按座位角度决定箭头方向：上半圈箭头朝上贴座位下沿，下半圈朝下，左右同理），`z-index 2`。
- 内容：头行「{seat}号 {name} · 发言中 / 竞选发言 / 遗言」+ 右侧倒计时 mono（有 `prompt.deadline_ts` 且是本人回合时用真实倒计时；其他人发言时若 `speech_time_limit` 可得则显示剩余估算，不可得则不显示）；正文取 `speechItems(events)` 里该座位最新一条（直播时流式文本已随事件更新，末尾加闪烁光标 `▍`，字段来自现有 `SpeechItem`）；若本人回合且尚未发言，正文显示斜体占位「轮到你发言…」；底部 4px 进度条（有时限时）；语音播报播放中显示「语音播报 · 正在朗读」+ 四根跳动音柱（接 `useVoice` 的 playing 状态）。
- 旁听（3d）：Agent 长发言时气泡宽 300px、`line-height 1.75`，最多显示 8 行，超出内部滚动。

### 4.4 桌心内容 `stageContent`

纯函数，放 `src/lib/stageContent.ts`，返回判别联合；测试只喂 state / events。

| 条件（按顺序匹配） | 桌心 | 数据 |
|---|---|---|
| `phase === "GAME_OVER"` | 无（结算页覆盖，§4.8） | — |
| 夜间 && `wolf_proposals` 非空或 `wolf_proposal_history` 非空 | `wolfCouncil`：「狼 队 密 议 · 仅狼可见」+ 每个提案「{seat}号 提议刀 {target}号」+ 票数比 + 规则提示（5a） | `wolf_proposals`、`wolf_kill_round` |
| `phase === "NIGHT_WITCH"` && `pending_night.wolf_target !== null` | `witchTarget`：「今 夜 被 刀」+ 「{seat}号 {name}」+ 药瓶状态行（7b） | `pending_night`、`prompt.observation`（药瓶在观察里才有，没有就省略这一行） |
| `phase === "NIGHT_SEER"` && 本人有 check 目标选中 | `crystal`：水晶球「查 验 · {N}号 · 确认后天亮前揭晓」（7a） | `selectedTarget` |
| `phase === "NIGHT_HUNTER_CONFIRM"` 或 `pending_hunter !== null` 且本人是猎人回合 | `crosshair`：「准 星 · {N}号」（7c） | `selectedTarget` |
| 夜间其它情况 | `moon`：月亮 + 「天黑请闭眼」+ 副句（玩家：「请闭眼，等待其他角色行动」；GM 回放：GM 手记 §4.4a） | — |
| `VOTE` / `VOTE_PK` / 竞选 `vote` 子阶段 | `tally`：羊皮纸「实时票型 · 按被投者分组 {cast}/{voters}」+ 每行「{target}号 · {n} 票 ← {voters}」+ 「等待 …」（5b）；PK 阶段换 `pkStage`：PK 台两枚 72px 徽记 + VS + 票数 + 双色进度条（4c） | `voteTally` / `sheriffVoteTally`、`vote_candidates`、`tie_round` |
| 发言类阶段（`DAY_SPEECH` / `LAST_WORDS` / `SHERIFF_ELECTION speech` / `SHERIFF_PK`） | `bubble`（§4.3）+ 桌心下方「本轮票型（上轮）」一行（上一轮 `VOTE_RESULT` 的摘要，没有则不显示） | `speechItems`、events |
| GM 回放（`mode === "replay"` 且 `nightSummary(events, round)` 非空 且 夜间） | `gmNotes`：羊皮纸「GM 手记 · 第 N 夜」+ 逐行 `NightSummaryRow`（5c） | `nightSummary` |
| 其它（`LOBBY` / `DAY_ANNOUNCE` / `SHERIFF_ELECTION` 非发言子阶段） | `campfire`：只有篝火 + 一行阶段说明（如「上警报名中 · 已上警 N 人」） | state |

### 4.5 右栏信息卡 `InfoRail`

每张卡是 `.ah-panel`；`railCards(state, events, viewer)` 纯函数返回要显示的卡片 id 列表（最多 3 张，按下表顺序取），测试覆盖每个阶段。

| 卡片 | 组件 | 出现阶段 | 内容 |
|---|---|---|---|
| 村镇公告 `news` | 新 `TownNews`，选择器 `townNews(events, state)` | 白天各阶段、夜间（观众 / 玩家） | 「昨夜 / 今日」键值行：昨夜死亡（`NIGHT_RESULT`）、放逐（`PLAYER_EXILED`）、警长、存活 `alive/n`，上帝 / 回放追加「狼 k / 好人 m」（只有角色全知时） |
| 墓地 `graveyard` | 新 `Graveyard`，选择器 `graveyard(events, state)` | 任意阶段有死亡时 | 按出局顺序：26px `RoleToken`（已知角色显示徽记，否则 ✕）+ 「{seat} {name} {角色}」+ 「第 N 天放逐 / 第 N 夜死亡 / 自爆 / 被带走」 |
| 发言顺序 `order` | `PlayerStatusPanel` 换皮 | 发言类阶段 | 现有内容（顺序、警徽流、备注） |
| 警长竞选 `election` | `ElectionPanel` 换皮 | 竞选 / 警 PK | 六步进度点列 + 上警名单签 + 已公开警徽流 |
| 票型 `votes` | `VotePanel` 换皮 | 投票 / PK / 遗言 | 逐票记录 + 结果 |
| 夜晚流程 `nightFlow` | 新 `NightFlow` | 夜间 | 按 `config.night_order` 列出「狼人 · 行动中 / 已行动 / 待行动」，当前阶段高亮 |
| 验人记录 `seerLog` | 新 `SeerLog` | 夜间 / 任意（`seer_log` 非空即显示） | 「第 N 夜 · M号 → 好人 / 狼人」 |
| 药瓶 `potions` | 新 `Potions` | `NIGHT_WITCH` 且 `prompt.observation` 带药瓶字段 | 解药 / 毒药 两格 |
| 本夜行动 `nightActs` | `NightSummary` 换皮 | 回放 / 上帝直播夜间 | 现有 `NightSummaryRow` |
| PK 发言回顾 `pkRecap` | 新，取 `speechItems` 里 PK 双方最近一条 | PK | 两行摘要 |

### 4.6 事件流抽屉 `EventDrawer`

> **已取代**（2026-10-28）：宽屏右栏常驻「对局记录」（`GameLog`），抽屉与页签只在 <1100px 保留，见 `2026-10-28-speech-stage-game-log-design.md` §3 / §6。以下为历史记录。

- 舞台最右 28px 竖向页签（`writing-mode: vertical-rl`），文案「事件流 · 发言回顾 ▸」；点击从右滑出 400px 深色抽屉覆盖在右栏上，内容是 `SpeechFeed` 换皮（羊皮纸气泡改为深色行：座位徽记 26px + 名字 + 正文；GM / 系统行用 `text-muted` 斜体；夜间私有行带阵营色左边线）。Esc 或点页签收回。回放截断提示与未读胶囊逻辑不变。
- 1100px 以下右栏隐藏，页签改为「信息 · 事件流 ▸」，抽屉内上半是 `InfoRail` 的卡片、下半是事件流。

### 4.7 底部

**玩家 HUD**（`viewer` 为座位号）：150px，`grid-template-columns: 260px 1fr 320px`，木纹底 `linear-gradient(180deg, #24180f, #1a110a)`，`border-top: 2px solid wood-edge`（遗言 / PK `wolf`，猎人 `god`）。

- 左 `IdentityCard`：84×112 `RoleToken variant="card"`（角色来自 `myRole`；出局后 `state="dead"`）+ 「{seat}号 · {name}」+ 角色名 heading 22px `gold`（出局写「已出局」`parch-danger`）+ 两行说明：狼「队友 {seats}」+「目标：屠边 / 屠城」（`config.win_condition`）；预言家「已验 N 人 · K 狼」+「警徽流 …」（本人 `badge_flow_claims`）；女巫「解药 n · 毒药 m」+「不能自救」（按 `config.witch_self_save`）；猎人「可开枪」；守卫「上夜守 N号」（`pending_night` 历史不可得时省略）；民 / 白痴只写角色；竞选中追加「已上警 · 可退水」。
- 中 `ActionBar` 换皮，结构按 3a / 4b / 5a / 5b / 7a–7c：
  - 顶行页签（圆角 12 胶囊，选中篝火底）：按 `available_tools` 生成，文案沿用 `TOOL_ZH`，竞选阶段 `sheriff_action` 拆成「竞选发言 / 退水 / 上警 / 不上警」等现有子项；右侧「声明身份 ▾」`select`（羊皮纸）与「警徽流」mono 输入（现有字段）。
  - 发言类：羊皮纸 `textarea` 58px，placeholder 「轮到你发言… / 轮到你时在此陈述竞选理由…（草稿会保留）/ 写下遗言…」。
  - 选目标类：标题 heading 18px `gold`（「今夜，狼群要咬谁？」「把票投给谁？」「今夜查验谁？」「带走谁？」「救，还是毒？」）+ 副句「点圆桌上的座位选择 · 当前 N号」+ 48px 目标胶囊（选中篝火渐变 + 发光，已验 / 不合法不渲染），投票多一个虚线「弃票」；女巫是三个按钮「解药 · 救 N号」`.btn-ok` / 「毒药 · 选目标」`.btn-danger` / 「不用药」`.btn-ghost`，选毒药后出现目标胶囊。
  - 非本人回合：虚线卡「旁听中」/「等待裁决」/「天黑请闭眼」+ 一段说明（3d：「{seat}号 {name} 发言中 · 之后 … → 你」；4c：「PK 双方不能投票 …」），右侧保留「自爆」描边胶囊（狼且 `self_destruct` 可用时）。
  - `accepted`（同步窗口等待）与 `lastError` 文案样式沿用，放在卡片底部一行。
- 右：倒计时条 160×10（槽 `#2a1d14`，填充 `fire-lo → fire-hi` 发光；遗言 / 血色阶段换 `wolf`）+ mono 18px 秒数（现有 `now` 注入逻辑不变，超时后显示「可能已超时」）+ 主按钮（「发送发言」「确认投票 · N号」「刀 · N号」+「空刀」「查验 · N号」+「跳过」「开枪 · N号」+「不开枪」「留下遗言」`.btn-danger`「确认行动」）。不是本人回合时主按钮禁用态，文案「你是最后一位发言 · 约 N 分钟后 / 投票截止后自动计票」之类放按钮上方。

**绳索条**（GM / 观众 / 回放，7d / 5c）：72px，`#0a0d14` 底、`border-top: 1px solid panel-edge`。`ReplayBar` 换皮：左侧 ⏮ ◀ ▶ ▶▶；轨道 12px 麻绳纹理（`repeating-linear-gradient(135deg, wood-edge 0 6px, wood-hi 6px 12px)`），已播部分换篝火纹理，轮次刻度文字在轨道上方 9px，游标是 24px 火把光球；右侧 `seq a/b` mono、倍速「2× ▾」、「回到直播」描边篝火色、快捷键提示。观众多「语音播报 开/关」（`VoiceToggle` 换皮成描边胶囊）与「复制分享链接」。`VoiceToggle` 在玩家视角移到顶栏右侧。

### 4.8 终局结算 `GameOverScreen`（1i）

- `phase === "GAME_OVER"` 且处于直播尾声或回放游标在末尾时，覆盖整个舞台（顶栏保留）；狼胜 `blood-sky` + 血月（`#f3b3a3 → wolf → #6e1f18`），好人胜 `#1c2440` + 金月。
- 文案：「第 N 轮 · 游 戏 结 束」/ heading 84px 字距 14px「狼人阵营胜 / 好人阵营胜 / 平局」/ 「{winner} · {屠边成功 | 狼人出清} · {total} 条事件」。
- 揭晓网格：`repeat(min(n, 9), 1fr)`，每格 `RoleToken size 52` + 「{seat} {name}」+ 角色名（阵营色）+ 结局「存活 / 第 N 天放逐 / 第 N 夜死亡 / 自爆 / 被带走」。角色未知的座位显示 `unknown`（观众直播尾声尚未拿到角色时就是「?」；回放装入后自然翻牌，零过滤）。
- 按钮：篝火「查看全局回放」（现有逻辑：玩家视角切到 `/replay`）、木牌「再来一局」（`#/`）、描边「回到历史对局」（`#/history`）。回放模式下结算页不覆盖，只在顶栏显示「游戏结束：胜方」并允许拖绳索（5c）。

### 4.9 响应式

- ≥1200px：如上。
- 1100–1199px：右栏 300px。
- <1100px：右栏隐藏，内容并入抽屉（§4.6）。
- <900px：舞台改为纵向：桌子区正方形占满宽度（座位 48px、名字 10px），信息卡列表在其下，HUD 变 `position: sticky; bottom: 0`，三段改两行（身份牌 + 计时在一行，行动区在下）。绳索条同样 sticky。

### 4.10 零过滤与行为约束

- `GameTable`、`TableCenter`、`InfoRail`、`SpeechBubble`、`GameOverScreen` 的 props 只有 `state` / `events`（已按回放游标截断）/ `prompt` / `selectedTarget` / `avatars` / `mode`；`viewer` 只传给 `GamePage` 决定渲染 HUD 还是绳索条，以及顶栏标签。
- 不新增任何「viewer === GM 才显示 X」的分支；GM 看得多是因为服务端给的 state 多。
- 倒计时到 0 不锁提交（现有行为）；座位点击只改 `selectedTarget`，提交仍走 `ActionBar` 的 `onSubmit`。
- `NightOverlay` 删除；其测试迁到 `stageContent` 的 `moon` 分支。

## 5. 大厅（设计稿 1c / 1d / 4a）

- 外层 `grid-template-columns: 240px 1fr 300px; gap 40px; padding 40px 56px`（第 2 步左栏 360px）。
- **左栏** `建 局 三 步`（heading 14px 字距 3px `text-muted`）：三行步骤，圆形序号（当前篝火底、已完成木牌底、未到虚线），标题 15px `text-bright`，副标 12px `text-muted`，点击可跳转（现有行为）。第 3 步改为 4a 的顶部横向进度「① 选择剧本 ② 分配座位 ③ 点燃篝火」。
- **第 1 步**：标题 heading 30px「选择剧本」+ 说明；`PresetCard` 改成羊皮纸剧本牌（`3px` 描边，选中 `fire`，未选 `parch-edge`）：标题 heading 20px、右上木签「{num_players} 人 / 带警长」、副标（`description_zh`）、角色徽记一行（`RoleToken variant="parch" size 28`，按 `roles` 展开）、底部 mono preset id；seed 羊皮纸输入；木牌次按钮「下一步 · 分配座位 →」。
- **第 2 步**：标题「分配座位」+ 说明「从档案库把 Agent 放到座位上；留空即随机 bot。选「我自己」即亲自入座。」；左栏羊皮纸搜索框 + 两列迷你档案卡（40px 首字圆 + 名字 + 模型简称 + 战绩，选中描边 `fire`）；中间 `SeatRing`（新组件，复用 `positions()`）：480px 桌面 + 篝火 + n 个 56px 座位（`RoleToken unknown` 显示档案首字 / 「我」/ 「bot」，已分配实线环、空位虚线环），点击座位弹出木牌小菜单（当前选中的档案 / 我自己 / 随机 bot / 清空）；先点左栏档案再点座位即分配；底部工具行「全部随机 bot」「随机打乱」「填满其余座位：{档案名 | 不填} ▾」（现有 `fill` 语义）。`SeatAssignment` 保留为 <900px 的列表回退，`SeatSlot` 数据模型与 `lib/seats.ts` 不变。
- **右栏**「开局卷轴」木牌卡（三步都在）：汇总行「{n} 座位 · {agents} 个 Agent · 我在 N号 · {bots} 个随机 bot」、「{preset 中文} · seed {随机|值}」、语音播报 / 旁白两个复选、篝火按钮「点燃篝火 · 开局」（只有第 3 步且可开局时亮，否则禁用态）；第 2 步下方多一段 12px 说明（同一档案可放多个座位 / memory_id 限制 / 「我自己」限制）。
- **第 3 步**（4a）：中间 640px 羊皮纸卷轴（顶部木轴条），标题 heading 32px「开 局 卷 轴」、副标「你将以 N号 入座 · 创建后直接进入玩家页 · 对局结束前看不到上帝视角」（无「我自己」时写「全 AI 对局 · 创建后进入上帝视角」）；两列定义表：剧本 / 座位签（我自己金底、档案羊皮纸底、「其余 N 座随机 bot」）/ seed / 我的显示名 / 发言时限（「秒 · 一根蜡烛」）/ 行动时限 / 播报；底部「← 上一步 · 分配座位」+ heading 20px 篝火按钮「点燃篝火 · 开局」。创建中与错误文案放卷轴底部。创建成功后弹 `ShareDialog`（§3）。

## 6. 其余页面（设计稿 1j / 1k / 4e / 1l）

- **历史对局** `History`（1j）：标题「村志 · 历史对局」+ 统计副标；羊皮纸账本表格列：开始时间（粗体 + mono id）/ 剧本 / 人数 / 状态签 / 胜方（heading 15px 阵营色）/ 轮数 / 座位（省略号）/ 操作（木签「回放 / 观看」、描边「分享」、红字「删除」）。`HistoryTable` 换皮，排序与分页逻辑不变。
- **Agent 档案库** `AgentLibrary`（1k）：标题「村民名册 · Agent 档案库」+ 副标；右上分段「声望 / 最近更新」、描边「导入 JSON」「导出全部」（现有功能才渲染）、篝火「+ 招募」；六列角色牌 `AgentCard`：木牌，顶部篝火光晕 + 72px 头像圆（有头像用图，否则首字 + 按名字哈希的暖色渐变）+ heading 22px 名字 + 金色一行人格摘要（`personality` 的 MBTI / 风格短语，无则省略；档案没有「称号」字段，不新增）；羊皮纸条三行「声望 / 战绩 / 性情（MBTI 或人格摘要）」；技能 mono 小签；底部 mono「{model} · T={temperature}」；操作「编辑 / 复制 / 删除」。
- **Agent 编辑器** `AgentEditor`（4e）：`Drawer tone="parch" width 620 kicker="招 募 告 示"`，标题「编辑 Agent · {name}」+ mono id；分节 kicker「一 · 身份」（84px 头像 + 上传 / 移除 + 名字（称号字段不存在，去掉）；模型服务「药剂」下拉 + 模型 mono + 「↻ 拉取列表」；温度滑杆「沉稳 — 跳脱」；thinking 开关；记忆 mono）、「二 · 技艺 · 已选 N」（两列技能卡，选中 `rgba(227,166,72,.12)` 底 + `fire` 边 + ■）、「三 · 人格」（`PersonalityEditor` 换皮）；底部深羊皮纸条「名字与 memory_id 库内唯一 …」+「取消」+ 篝火「盖章保存」。
- **模型服务** `Providers`（1l 左）：标题「炼金工坊 · 模型服务」；`ProviderCard` 木牌：44px 药剂圆（按 `kind` 取色）+ heading 22px 名字 + 金色 kind 行 + 右上测试状态「● 未测试 / 已连通 / 失败」；羊皮纸信息条「地址 / 密钥 已配置 ····{tail} / 默认模型」mono；底部「被 N 个 Agent 引用」+「测试连接 / 编辑 / 删除」；列表末尾虚线木牌「+ 新建药剂（provider）」。`ProviderEditor` 用 `Drawer tone="parch" kicker="配 方"`。
- **用户管理** `AdminUsers`（1l 右）：标题「长老名册 · 用户管理」；羊皮纸表格：用户名 / 邮箱 mono / 身份（admin 金、user 墨）/ 状态 / 操作（禁用 红、提升 墨）。
- `ModelSelect`、`SkillPicker`、`PersonalityEditor`、`ConfirmDialog` 统一改羊皮纸 / 木牌样式，逻辑不动。

## 7. 卡牌皮肤（设计稿 6a / 6b / 7e）

- `src/store/prefs.ts`：`tableStyle: "round" | "cards"`，读写 `localStorage["agenthowl.tableStyle"]`（读写都 try/catch，缺省 `round`）。顶栏「桌面：圆桌 ▾」切换。
- `CardBoard`（新组件）替换 `GameTable` 的桌子区，共用同一份座位模型（`seatModel(state, prompt, selectedTarget)` 纯函数：no / name / role / dead / me / speaking / alpha / badge，圆桌与卡牌都从它渲染，PR ② 就按这个模型写）。
  - 牌阵 `repeat(4, 116px)`，牌 140px 高 `radius 7`，内嵌 1px 浅边框，左上羊皮纸座位号签；已知身份正面（阵营渐变 + 46px 徽记 + 角色名），未知牌背（木纹 + 44px 首字圆 + 「身份未翻」），出局灰牌（`#141821` + ✕ + 「出局」，上帝回放时灰牌仍显身份 + 右上 ✕ 章）。
  - 状态：发言者 `translateY(-8px)` + 金边 + `0 0 28px rgba(240,192,96,.55)`；本人 `fire` 边；夜间好人牌 `opacity .55`、目标牌抬起泛红 + 底部红签「目标 / 被刀」；投票票数挂牌底篝火签、领先者金边；竞选上警者右上金签「警」。
  - 发言气泡改为牌阵下方一条横向羊皮纸（左侧 44px 徽记 + 头行 + 正文 + 进度条），其余（右栏、HUD、绳索条）不变。
- 大厅第 2 步与结算页不受皮肤影响。

## 8. 分批与 PR

| PR | 分支 | 内容 | 验收 |
|---|---|---|---|
| ① | `feat/ui-gamified-1-foundation` | §2 token / 字体 / 全局类、`RoleToken`、`App` 导航、`LoginPage`、`ErrorState`、`ShareDialog`、`ConfirmDialog`、`Drawer` 壳；设计稿资产入库 | `npm run check`；登录 / 错误 / 导航截图对照 1b / 4f；旧页面在新 token 下仍可用（颜色变了但不破） |
| ② | `feat/ui-gamified-2-game` | §4 全部：`GamePage` 布局、`PhaseBar`、`PhasePlaque`、`GameTable`、`SpeechBubble`、`TableCenter` + `stageContent`、`InfoRail` + 新选择器、`EventDrawer`、HUD（`IdentityCard` + `ActionBar` 换皮）、绳索条 `ReplayBar`、`GameOverScreen`、响应式；删除 `NightOverlay`、`SeatCircle`、`SpeakerSpotlight` | `npm run check`；`frontend/e2e/play.mjs` 跑狼 / 预言家 / 女巫 / 猎人 / 民五种座位 + 上帝 + 观众直播与回放；截图入 `docs/design/ui-gamified-<日期>/` |
| ③ | `feat/ui-gamified-3-lobby` | §5 大厅三步、`SeatRing`、`PresetCard`、第 3 步卷轴 | `npm run check`；建局到开局全流程手测 |
| ④ | `feat/ui-gamified-4-pages` | §6 历史 / 档案库 / 编辑器 / 模型服务 / 用户管理 | `npm run check`；各页截图 |
| ⑤ | `feat/ui-gamified-5-cards` | §7 卡牌皮肤与偏好 | `npm run check`；`frontend/e2e/play.mjs` 切卡牌跑一遍四种状态；截图 |

每个 PR 独立 push，由用户在 GitHub 合并（不本地合并 main）。PR 之间不堆叠：③④ 基于 ① 合并后的 main，⑤ 基于 ② 合并后的 main；若 ② 未合并先做 ③④。

## 9. 测试

- 现有 277 个 vitest 保持通过；结构变化的测试（`GamePage.test`、`SeatCircle.test` → `GameTable.test`、`NightOverlay.test` → `stageContent.test`、`SpeakerSpotlight.test` → `SpeechBubble.test`、`PhaseBar`、`ActionBar`、`Lobby`、`LoginPage`、各页）按新 DOM 更新查询，断言的业务语义不变。
- 新增纯函数测试（无 DOM）：`roleIcons`（7 个角色都有路径、阵营映射）、`stageContent`（每个阶段 × 有无 prompt × 狼提案有无 → 期望分支）、`railCards`（每个阶段返回的卡片 id）、`townNews` / `graveyard`（基于金样 fixture 的事件流跑一遍，断言死亡顺序与原因）、`seatModel`（me / speaking / dead / 夜间暗化 / 徽章）、`prefs` store（localStorage 异常时回退）。
- 组件测试：`RoleToken` 四种 variant × 三种 state 渲染；`GameTable` 座位点击在 `needsTarget` 时回调、不需要时不回调；`GameOverScreen` 角色未知显示「?」；`EventDrawer` 开合与 Esc。
- 零过滤守卫：`GameTable` / `InfoRail` / `TableCenter` / `GameOverScreen` 的 props 类型里没有 `viewer`（tsc 保证）；`grep -n "viewer" src/components/GameTable src/components/InfoRail src/lib/stageContent.ts` 为空作为 PR ② 的检查项。
- 金样 parity 不受影响（engine 不动），`make fixtures` 不需要重跑。

## 10. 风险与取舍

- **Noto Serif SC 首屏字体闪动**：`display=swap`，fallback 用系统宋体，接受。
- ~~**Agent 长发言放进座位气泡**~~：已改为右栏发言台 + 对局记录（`2026-10-28-speech-stage-game-log-design.md`）。
- **夜间暗化规则**是「角色未知即暗」，守卫 / 女巫等单人神职在自己的夜里看到的桌面除了自己全暗，符合「只有自己睁眼」的意象。
- **观众在线人数**（7d）后端没有这个数据，不做。
- **`GameConfigLite` 只有 `num_players / sheriff / roles / win_condition` 是强类型**，`witch_self_save`、`night_order`、`speech_time_limit` 等通过索引签名读取，缺失时相应文案省略（夜晚流程卡退化为按固定顺序列出存在的神职）。
- **卡牌皮肤**只做桌子区，大厅与结算页不做卡牌版（设计稿也没有）。
