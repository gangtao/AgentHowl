# UI 改版截图基线（2026-10-28，PR ① 视觉基础 + PR ② 对局页 + PR ③ 大厅）

对照设计稿：`docs/design/gamified-2026-10-27/options/`。桌面 1440×900，手机 390×844。
后续 PR（对局页、大厅、其余页面、卡牌皮肤）完成后在本目录追加对应截图。

| 文件 | 画面 | 设计稿 |
|---|---|---|
| `01-auth-login.png` | 登录「入村」 | 1b |
| `01-auth-register.png` | 注册「落户」 | 1b |
| `01-auth-verify.png` | 验证码「对暗号」 | 1b |
| `01-auth-login-390.png` | 手机宽登录（无横向滚动） | — |
| `02-nav-lobby.png` | 木栏导航 + 大厅（PR ① 时的旧大厅，PR ③ 见下） | 1c 顶栏 |
| `06-history-share-dialog.png` | 「传 · 分享对局」木牌对话框（历史页本体待 PR ④） | 4f |
| `07-agents-editor.png` | 羊皮纸「招募告示」抽屉壳（表单内容待 PR ④） | 4e |
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
| `02-lobby-2-seats-390.png` | 390 宽：圆桌与迷你档案卡隐藏，`SeatAssignment` 列表回退 | — |
