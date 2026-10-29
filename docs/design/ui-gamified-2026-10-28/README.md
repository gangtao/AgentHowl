# UI 改版截图基线（2026-10-28，PR ① 视觉基础 + PR ② 对局页 + PR ③ 大厅 + PR ④ 其余页面 + PR ⑤ 卡牌皮肤）

对照设计稿：`docs/design/gamified-2026-10-27/options/`。桌面 1440×900，手机 390×844。
后续 PR（对局页、大厅、其余页面、卡牌皮肤）完成后在本目录追加对应截图。

| 文件 | 画面 | 设计稿 |
|---|---|---|
| `01-auth-login.png` | 登录「入村」 | 1b |
| `01-auth-register.png` | 注册「落户」 | 1b |
| `01-auth-verify.png` | 验证码「对暗号」 | 1b |
| `01-auth-login-390.png` | 手机宽登录（无横向滚动） | — |
| `02-nav-lobby.png` | 木栏导航 + 大厅（PR ① 时的旧大厅，PR ③ 见下） | 1c 顶栏 |
| `06-history-share-dialog.png` | 「传 · 分享对局」木牌对话框（历史页本体见 PR ④） | 4f |
| `07-agents-editor.png` | 羊皮纸「招募告示」抽屉（PR ④ 重拍：四节表单） | 4e |
| `07-agents-editor-personality.png` | 同一抽屉滚到「3 · 人格」：羊皮纸上的分段选择与 kicker 可读性 | 4e |
| `09-error-not-found.png` | 4404「这局已随风散去」 | 4f |
| `09-error-forbidden.png` | 匿名 4401「村口有人守着」 | 4f |

## PR ② 对局页（全景圆桌 3a 骨架）

玩家视角截图来自 `frontend/e2e/play.mjs`（真人坐 0 号 + 随机 bot，12 人预女猎白）；上帝 / 观众截图来自
`frontend/e2e/screens.mjs` 对已结束对局 `g_026044d2` 的回放。

| 文件 | 画面 | 设计稿 |
|---|---|---|
| `03-game-night-wolf-turn.png` | 玩家 · 狼刀夜：月光桌面、选中座位金环、HUD「刀 · N号 / 空刀」 | 5a |
| `03-game-night-seer-turn.png` | 玩家 · 预言家查验 | 7a |
| `03-game-night-witch-turn.png` | 玩家 · 女巫用药（解药 / 毒药 / 不用药） | 7b |
| `03-game-hunter-shoot.png` | 玩家 · 猎人开枪：准星、墓地翻牌 | 7c |
| `03-game-day-speech-turn.png` | 玩家 · 白天发言轮到我：气泡 + 羊皮纸输入 | 3a |
| `03-game-sheriff-candidacy.png` / `03-game-sheriff-pk.png` | 警长竞选 / 警长 PK | 4b |
| `03-game-vote-turn.png` / `03-game-vote-pk.png` | 投票（桌心实时票型）/ PK 投票 | 5b / 4c |
| `03-game-last-words.png` | 遗言（血色） | 4d |
| `03-game-badge-window.png` | 警徽处置窗口 | — |
| `03-game-over.png` | 玩家视角结算（血月，身份未知者「?」） | 1i |
| `05-gm-replay-{night,sheriff,speech,vote,over,drawer}.png` | 上帝回放：各阶段 + 结算 + 事件流抽屉 | 5c / 3a |
| `05-spectator-replay-{speech,end}.png` | 匿名分享链接观众 | 7d |
| `10-game-1100.png` / `10-game-390.png` | 1100 宽（右栏入抽屉）/ 390 宽（纵向堆叠，无横向滚动） | — |

## PR ③ 大厅三步

截图来自 `frontend/e2e/lobby-shots.mjs`（登录 `e2e_player`，档案库为空，seed 42，不点「点燃篝火」）。
建局到开局的全流程由 `play.mjs`（村民 seed 3）走通：`finished: true`、`rejected: []`、`mismatches: 0`。

| 文件 | 画面 | 设计稿 |
|---|---|---|
| `02-lobby-1-preset.png` | 第 1 步：左栏「建 局 三 步」、羊皮纸剧本牌（选中篝火描边、木签、角色徽记）、seed、右栏「开局卷轴」木牌卡 | 1c |
| `02-lobby-2-seats.png` | 第 2 步：左栏迷你档案列（空库提示）、480px 圆桌入座（0 号「我」、其余虚线 bot）、工具行 | 1d |
| `02-lobby-2-seats-menu.png` | 第 2 步：点 5 号座位弹出木牌菜单（「我自己」因已在 0 号而禁用） | 1d |
| `02-lobby-3-scroll.png` | 第 3 步：顶部横向进度、640px 羊皮纸「开 局 卷 轴」（座位签 / 时限「秒 · 一根蜡烛」）、两处「点燃篝火 · 开局」 | 4a |
| `02-lobby-1-preset-1100.png` / `02-lobby-2-seats-1100.png` | 1100 宽（≤1280 断点）：剧本牌单列；档案列上移成整行，圆桌保持 480px | — |
| `02-lobby-2-seats-390.png` | 390 宽：圆桌与迷你档案卡隐藏，`SeatAssignment` 列表回退 | — |

## PR ④ 其余页面

截图来自 `frontend/e2e/pages-shots.mjs`（登录 `e2e_player`，空库时临时造 3 个档案 + 1 个 provider，截完删除）。

| 文件 | 画面 | 设计稿 |
|---|---|---|
| `06-history.png` | 「村志 · 历史对局」羊皮纸账本：时间 + mono id、剧本、状态签、阵营色胜方、座位省略、木签回放 / 描边分享 / 红字删除 | 1j |
| `07-agents.png` | 「村民名册 · Agent 档案库」：声望 / 最近更新分段、导入 / 导出、篝火「+ 招募」、角色牌（首字渐变圆、金色人格行、羊皮纸三行、技能签、模型行） | 1k |
| `07-agents-editor.png` | 「招募告示」抽屉：一 · 身份（84px 立绘 / 名字 / 药剂下拉 / 温度「沉稳 — 跳脱」/ thinking / 记忆）、二 · 技艺 技能卡 ■、盖章保存 | 4e |
| `08-providers.png` | 「炼金工坊 · 模型服务」药剂木牌：药剂圆、kind 行、测试状态、羊皮纸信息条、引用数、虚线「+ 新建药剂（provider）」 | 1l 左 |
| `08-admin-users.png` | 「长老名册 · 用户管理」羊皮纸表：用户名 / mono 邮箱 / 身份着色 / 状态 / 操作（管理员会话截取） | 1l 右 |
| `07-agents-390.png` | 390 宽档案库：两列角色牌 | — |

## PR ⑤ 卡牌皮肤

顶栏「桌面：圆桌 ▾ / 卡牌 ▾」切换并记在 `localStorage["agenthowl.tableStyle"]`。玩家视角截图来自
`AH_TABLE=cards RUN=cards-wolf AH_SEED=2 RUN_SHERIFF=1 node play.mjs`（狼视角，g_0a185b1b：`finished: true / rejected: [] / mismatches: 0 / stalls: 0`）；
上帝回放截图来自 `AH_TABLE=cards AH_GAME=g_16fe9066 node screens.mjs`。

| 文件 | 画面 | 设计稿 |
|---|---|---|
| `11-cards-night-wolf-turn.png` | 玩家 · 狼刀夜：狼队正面、好人牌背沉入阴影，选中的目标牌篝火边 | 7e |
| `11-cards-sheriff-candidacy.png` | 警长竞选：上警者右上金签「警」，发言者抬牌金边 | 7e |
| `11-cards-vote-turn.png` | 投票：票数挂牌底篝火签，领先者金边；桌心票型在牌阵下方 | 7e |
| `11-cards-day-speech-turn.png` | 白天发言：牌阵下方横向羊皮纸发言条（44px 徽记 + 头行 + 正文 + 进度条） | 6b |
| `11-cards-gm-replay-{night,sheriff,speech,vote,over,drawer}.png` | 上帝回放：已知身份正面朝上、出局灰牌仍显身份 + ✕ 章 | 6a / 6b |
| `11-cards-game-1100.png` / `11-cards-game-390.png` | 1100 / 390 宽：牌阵顶对齐、放不下时纵向滚动（无横向溢出） | — |
