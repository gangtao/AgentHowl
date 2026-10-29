# 对局页浏览器回归（e2e）

两段 Playwright 脚本，独立于 `frontend` 主包安装（`cd frontend/e2e && npm i`），需要本地后端（`:8000`）与
`npm run dev`（`:5173`，代理 `/api`）都在跑，以及一个测试账号。不进 CI；用于 UI 改版各 PR 的人工验收。

| 脚本 | 作用 |
|---|---|
| `play.mjs` | 真人坐 0 号 + 随机 bot 打完一整局：登录 → 建局 → 按角色策略行动（狼刀 / 查验 / 救毒 / 守护 / 开枪 / 上警 / 投票 / 遗言 / 自爆）→ 赛后检查；每局输出一行 `SUMMARY` JSON，`finished: true` 且 `rejected` 为空即通过 |
| `screens.mjs` | 用一局已结束的对局，以上帝 / 观众视角打开回放，拖到夜晚 / 竞选 / 发言 / 投票 / 终局截图，并截 1100 / 390 宽 |
| `lobby-shots.mjs` | 走完大厅三步（不开局）截第 1 / 2 / 3 步与打开木牌菜单的第 2 步，再截 390 宽的列表回退（UI 改版 PR ③） |
| `pages-shots.mjs` | 历史 / 档案库（含打开编辑器）/ 模型服务 / 用户管理（需管理员会话 `AH_SESSION` + `PAGES=admin`）截图；空库时临时造数据并清理（UI 改版 PR ④） |

```bash
cd frontend/e2e
AH_BASE_URL=http://localhost:5173 AH_USER=e2e_player AH_PASS=… AH_SEED=2 RUN=wolf SPEECH_SEC=15 ACTION_SEC=15 node play.mjs
AH_BASE_URL=http://localhost:5173 AH_USER=e2e_player AH_PASS=… AH_GAME=g_xxxxxxxx SHOT_DIR=../../docs/design/ui-gamified-2026-10-28 node screens.mjs
AH_BASE_URL=http://localhost:5173 AH_USER=e2e_player AH_PASS=… SHOT_DIR=../../docs/design/ui-gamified-2026-10-28 node lobby-shots.mjs
AH_BASE_URL=http://localhost:5173 AH_USER=e2e_player AH_PASS=… SHOT_DIR=../../docs/design/ui-gamified-2026-10-28 node pages-shots.mjs
AH_BASE_URL=http://localhost:5173 AH_SESSION=<管理员会话 cookie> PAGES=admin SHOT_DIR=… node pages-shots.mjs
```

大厅段（PR ③ 起）只靠这些控件：剧本牌文本 → `#lobby-seed` → 「下一步 · 分配座位 →」→ `button[aria-label="入座 0号"]` →
木牌菜单 `[role=menuitem]`「我自己」→ 「下一步 · 开局卷轴 →」→ 卷轴里的 `我的显示名 / 发言时限 / 行动时限` 输入 →
`section.ah-parch` 内的「点燃篝火 · 开局」。

发牌只看 seed（`std_12_yn_hunter_idiot`，seat 0 的角色 → seed）：IDIOT 1 / WEREWOLF 2 / VILLAGER 3 / WITCH 4 / HUNTER 9 /
SEER 22；`std_12_yn_hunter_guard` 同表但 seed 1 = GUARD；`std_9_*`：VILLAGER 1 / SEER 2 / HUNTER 4 / WEREWOLF 5 / WITCH 13。

真实 agent 对局：`AH_AGENTS=1` 把当前账号档案库里的档案按顺序放到 1..n-1 号；`AH_FILL=<档案名>` 用「填满其余座位」
让其余座位都是同一个无 memory_id 的档案（普通用户的档案须挂自己的 provider）。agent 要思考时间，时限用
`SPEECH_SEC=120 ACTION_SEC=60 MAX_MIN=60`；并发跑多局时错开登录，后端对 `/auth/login` 有限流（429）。
`AH_TABLE=cards` 让 `play.mjs` / `screens.mjs` 进对局页后把顶栏「桌面」切成卡牌（UI 改版 PR ⑤）；座位契约
`button[data-seat]` 两种皮肤相同，玩局循环不变，`screens.mjs` 此时只截上帝回放与窄屏，前缀 `11-cards-*`。
脚本只用页面上的控件行动（座位胶囊 / 桌上座位 / HUD 主按钮），WebSocket 帧只用来决定「点哪个」；
`RUN_SHERIFF=1` 上警、`SELF_DESTRUCT=1` 第 2 轮自爆、`AH_SESSION` 可代替账号密码直接注入会话 cookie。
Chromium 路径缺省取 `~/Library/Caches/ms-playwright/chromium-1148/...`，可用 `CHROMIUM` 覆盖。
