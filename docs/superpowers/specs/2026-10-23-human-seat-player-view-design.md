# 真人入座与 Web 玩家视角 设计（issue #115 子项目一）

状态：已评审通过（2026-10-23）。实现计划见 `docs/superpowers/plans/`。

## 1. 目标与范围

用户在 Web 大厅建局时给自己留一个座位，建局后直接进入玩家视角亲自参与对局：看到的只有自己座位可见的信息，轮到自己时在页面上发言、投票、夜间行动、参与警长竞选。建局者在对局进行中**不能**查看上帝视角，信息隔离在服务端成立。

本期只做**单真人 + 多 Agent**（身份随机发牌）。不做的事：

- 阵营组队（座位阵营约束、建局选阵营、按阵营战报）：子项目二。
- 多真人同局、邀请他人入座、未满员等待大厅：留接口（join 指定座位、座位绑定账号），不做 UI。
- 引擎改动：零。`backend/app/engine` 零 diff，TS reducer fixtures 不变。

成功判据：登录用户在 Lobby 把某个座位设为「我自己」，点「开始」后落到玩家页；一整局内每个轮到自己的窗口都能在页面上完成行动；全程打不开本局的上帝视角；终局后能回放全局。

## 2. 现状与约束

- 后端数据面已齐：`POST /games/{id}/join` 建 `HumanPlayerPort`；`/state` `/events` `/my-turn` `/actions` 和 WS `your_turn` 都按 PLAYER token 裁剪（`observation.visible_events`）。缺的是 join 不能指定座位、不绑定账号的座位语义、建局者视角封锁。
- 前端只有 `GM | SPECTATOR` 两种视角；`api/ws.ts` 丢弃 `your_turn` / `action_result` 帧；没有 ActionBar。
- 硬约束（CLAUDE.md、#114 spec）：前端零信息过滤，可见性全由服务端按视角裁剪；`app/runtime` `app/api` `app/cli` 不在模块级 import litellm；密钥、password_hash、session_id 永不进响应或日志。

## 3. 后端

### 3.1 入座指定座位

- `JoinRequest` 增加 `seat: int | None = None`。
- `GameLobby` 内部由「按顺序追加的列表」改为「座位号 → RosterEntry 的字典」：
  - `join(display_name, player_type, seat=None) -> int`：`seat` 为 None 时取最小空位；指定座位越界（`< 0` 或 `>= num_players`）或已被占用 → `LobbyError`（API 409）。
  - `fill_with_bots(name_for)` 填所有空位；`roster()` 满员时按座位号 0..n-1 拼出元组。
  - `is_full` 语义不变。
- `GameRegistry.join(handle, display_name, player_type, *, seat=None, user_id=None) -> int`：
  - 同一 `user_id`（非 None）在同一局已有座位 → `LobbyError`（409「你已入座 N 号」）。
  - 成功后写 `handle.seat_users[seat] = user_id`，并照旧为该座位建 `HumanPlayerPort`。
- `GameHandle` 新增 `seat_users: dict[int, str | None]` 和方法 `owner_seat() -> int | None`（`seat_users` 中值等于 `owner_id` 的座位；`owner_id` 为 None 时恒为 None）。
- `registry.start` 行为不变：已 join 的座位不套用 `agents[seat]` 档案，其余空位按档案或随机 bot 填。
- `join_endpoint` 把登录用户的 `user_id` 传给 `registry.join`（host_token 入座的外部客户端仍为 None）；`JoinResponse` 不变。

### 3.2 视角解析与上帝视角封锁

定义「封锁中」：`handle.owner_seat() is not None` 且对局未结束（事件流末尾不是 `GAME_OVER`）。

- `_session_viewer(games, user, game_id)`：
  - 未登录 → 401；无权 → 404（不变）。
  - 登录者是 **owner** 且封锁中 → 返回 `TokenInfo(kind="PLAYER", seat=owner_seat, user_id=…)`。
  - 其他情况（admin、终局后的 owner）→ GM（不变）。
- `resolve_viewer`：对局 token 解析为 `kind="GM"` 且封锁中 → 403「建局者已入座，对局结束前不能查看上帝视角」。`gm_token` 在建局时照发，终局后自动可用。HOST / PLAYER / SPECTATOR / 分享 token 不受影响。
- WS `/ws`：三条入口复用上面两个函数，GM token 被拒 → 关闭码 4403；cookie 入口自然得到 PLAYER 视角并能提交行动（`info.kind == "PLAYER"` 且 `human_ports[seat]` 存在）。
- `/state`（`SpectatorView`）与 `/meta` 响应增加 `viewer: Literal["GM","SPECTATOR"] | int`，告诉前端本次请求被解析成了哪种视角。`/events` 不加。
- 封锁判断读的是运行中 `handle` 的事件流（`store.load_events` 或 runner 的 live state），不新增持久化字段；重启后对局已不在运行，`GAME_OVER` 判定沿用现有 `_finished`。

### 3.3 不变量

- 建局者入座后，本局任何 GM 视角读流（REST、WS、音频清单、头像以外的一切需要 viewer 的端点）在终局前统一 403；`/meta` `/replay` 本来就要求 GAME_OVER。
- 观察隔离：owner 以 PLAYER 视角拿到的 `/state` `/events` 与普通 PLAYER token 完全一致（现有隔离测试加一个 owner-as-player 用例）。

## 4. 前端

### 4.1 路由与视角

- `Viewer` 类型从 `"GM" | "SPECTATOR"` 扩为 `"GM" | "SPECTATOR" | number`（座位号）。
- `parseHash` 新增 `#/g/{id}?player=<token>` → `{route:"game", gameId, token}`，不带 `viewer` 提示。`ParsedHash.viewer` 降级为「URL 里的提示」：`?gm=` 给 `"GM"`、`?share=` 给 `"SPECTATOR"`、`?player=` 和裸 `#/g/{id}` 不给。GamePage 不再要求提示存在，一律以 `/state`（或终局时 `/meta`）响应里的 `viewer` 字段为准，服务端说了算。
- `useGameStore.load()` 的 `viewer` 来源改为 `/state.viewer`；`GameMeta`、`NightOverlay`、`NightSummary`、`SeatCircle` 等接收 `Viewer` 的组件按「是否数字」区分座位视角。

### 4.2 Lobby

- 座位槽 `SeatSlot.agentId: string | null` 扩为 `string | null | "me"`（`"me"` 表示我自己，全局至多一个；`lib/seats.ts` 的 `toAgentsPayload` 对 `"me"` 座位不写档案、不被 `"*"` 覆盖——即 `agents` 映射里不出现该座位键，且有 `"*"` 时后端填充只针对未 join 的座位，现有语义已满足）。
- 有「我自己」时：
  - 显示名输入框，默认当前用户名。
  - 建局 body 的 `config_override` 自动带 `speech_timeout_sec: 120`、`action_timeout_sec: 60`，两个数字在表单里可改；用户已填的 seed 等 override 合并保留。
  - 点「开始」后前端顺序执行 `createGame` → `joinGame(game_id, {seat, display_name})`（cookie）→ `startGame(game_id, host_token)`，成功后 `location.hash = "#/g/{id}?player=<player_token>"`。不展示 GM 链接卡片；玩家页不放分享对话框，真人入座对局的分享链接从 History 页（「观看」/「分享」）获取。
  - join 或 start 失败：展示错误，提供「删除这局」按钮（`DELETE /games/{id}`，已有），不留半成品。
- 没有「我自己」时行为完全不变（建局 → 开始 → GM 链接卡片）。
- `api/rest.ts` 新增 `joinGame(gameId, body): Promise<JoinResponse>`（`credentials: same-origin`）。

### 4.3 回合状态（store 切片 `turn`）

```ts
interface YourTurn { observation: PlayerObservation; available_tools: string[]; deadline_ts: number }
interface ActionResult { ok: boolean; event_id?: string; state_version?: number; rejected_reason?: string }
interface TurnSlice {
  prompt: YourTurn | null;      // 最新一条 your_turn；提交成功（ok=true）后清空
  pending: boolean;             // 已发送、等待 action_result
  lastResult: ActionResult | null;
  lastError: string | null;     // WS error 帧（NotYourTurn / ToolCallError / 超时）
}
```

- `api/ws.ts`：`your_turn` 帧 → `setPrompt`；`action_result` → `pending=false`，`ok` 则清 prompt，否则保留 prompt 并记 `rejected_reason`；`error` 帧 → `lastError`（现有 error 处理保留）。
- 提交：`useLiveEvents` 暴露 `send(call: ToolCall)`，直接 `ws.send(JSON.stringify(call))`，置 `pending=true`。不走 REST `/actions`（避免两条通道竞争）。
- 重连：服务端在连接建立时会重推当前 prompt；`turn` 切片以最新一条为准，连接断开时 `pending=false`。
- `PlayerObservation` 的 TS 类型按后端 `observation.py` 字段手写（`my_seat`、`my_role`、`my_status`、`phase`、`round`、`seats`、`sheriff_seat`、`private`、`election_stage`、`sheriff_candidates`、`vote_candidates`、`pk_speech_pending`、`badge_only`）。

### 4.4 ActionBar 组件

位置：`frontend/src/components/ActionBar/`。纯展示 + 一个 `onSubmit(call: ToolCall)` 回调；工具调用的构造放在 `lib/toolCalls.ts` 纯函数里便于单测。

渲染规则：仅当 `viewer` 为座位号。`prompt` 为空时折叠成一行状态文字（「等待其他玩家…」）。`prompt` 非空时按 `available_tools` 渲染，一次只展示一个主动作分组，多个工具可用时用 tab 切换：

| 工具 | 界面 | 产出 |
|---|---|---|
| `speak` | 多行文本；可选「声明身份」下拉（角色枚举 + 不声明）；警长相关阶段可填「警徽流」座位序列 | `{tool:"speak", arguments:{text, claim_role?, badge_flow?}}` |
| `vote` | 候选座位按钮（`vote_candidates` 非空用它，否则存活且非本人座位）+「弃票」 | `{tool:"vote", arguments:{target_seat}}` 或 `{abstain:true}` |
| `night_action` | 按 `my_role`：狼 `kill`/`skip`（显示 `private.teammates` 与 `tonight_kill_proposals`）；预言家 `check`；女巫 `save`/`poison`/`skip`（显示 `private` 里的今晚刀口与剩余药）；守卫 `guard`/`skip`；猎人 `shoot`/`skip`；目标为存活座位（女巫 save 的目标固定为刀口） | `{tool:"night_action", arguments:{action_type, target_seat?}}` |
| `sheriff_action` | `election_stage` 决定：竞选报名「上警 / 不上」；PK 或投票「投给候选人」（`sheriff_candidates`）；候选人「退水」；`badge_only` 时只有「移交警徽给某座位」「撕警徽」；当警长时「定发言方向 LEFT / RIGHT」 | `{tool:"sheriff_action", arguments:{action_type, target_seat?, direction?}}` |
| `self_destruct` | 红色按钮 + 二次确认 | `{tool:"self_destruct"}` |

- 倒计时条由 `deadline_ts - Date.now()/1000` 驱动，每秒刷新；到 0 禁用输入并显示「已超时，系统代为行动」，直到下一条 prompt 或 action_result。
- `pending` 时禁用提交；`lastResult.ok=false` 时在条内显示 `rejected_reason`，输入保留。
- 不做任何「这个动作合不合法」的本地裁决，只做输入形态校验（例如必须选目标）；合法性由引擎裁决并经 `action_result` 回传（#53 的拒绝原因）。

### 4.5 既有组件的座位视角适配

- `NightOverlay`：座位视角下，当前夜间阶段若是本人角色的行动阶段且 `turn.prompt` 非空 → 不遮罩；否则遮罩文案「请闭眼」。GM / SPECTATOR 行为不变。
- `SeatCircle`：高亮本人座位（「我」标记）。
- `GamePage` 头部：座位视角显示「我是 N 号 · 角色 X」（角色来自 `turn.prompt.observation.my_role`，没有 prompt 时从已 reduce 的可见事件取；两者都没有则不显示）；不显示 GM 链接入口，也不显示分享按钮（分享链接从 History 页的「观看」/「分享」获取）。
- 死亡后：页面保持座位视角，ActionBar 只在遗言、猎人开枪、警徽流窗口出现。

## 5. 错误处理与边界

| 场景 | 处理 |
|---|---|
| join 指定座位被占或越界 | 409，Lobby 展示并提供删除此局 |
| 同账号重复 join 同一局 | 409「你已入座 N 号」 |
| owner 入座后访问 `?gm=` | 403，前端 ErrorState 文案「建局者已入座，对局结束前不能查看上帝视角」，并给「以玩家身份进入」链接（裸 `#/g/{id}`） |
| owner 入座后裸 `#/g/{id}` | 服务端解析为 PLAYER，页面即玩家页 |
| 终局 | `_session_viewer` 恢复 GM；玩家页检测 `game_over` 后显示「查看全局回放」按钮跳 `#/g/{id}` |
| 真人超时 | 现有 runner 代打逻辑（随机行动或弃权），ActionBar 显示已超时 |
| 同账号开两个标签页 | 同一 token 多连接都收到 prompt，先提交者生效，后者收到 `error` 帧 |
| 服务重启 | token 丢失是既有限制（#118）；对局不再运行，只剩回放 |
| 语音与旁白 | 现有按视角过滤已覆盖；玩家视角只收自己可听的音频，不改 |

## 6. 测试

后端（`backend/tests`）：
- `GameLobby.join(seat=…)`：指定、顺序混用、占用冲突、越界、`roster()` 顺序。
- `registry.join`：同账号重复入座 409；`seat_users` 与 `owner_seat()`。
- `_session_viewer` / `resolve_viewer`：owner 入座后 cookie → PLAYER、`?gm=` → 403、admin → GM、终局后 owner → GM、SPECTATOR 与分享不受影响。
- WS：cookie 入口 owner-as-player 可收 `your_turn` 并提交；GM token → 4403。
- `/state.viewer` 与 `/meta.viewer` 字段三种取值。
- 隔离：owner-as-player 的 `/state` `/events` 与同座位 PLAYER token 响应逐字段一致。
- 引擎零 diff、`test_importing_registry_does_not_load_litellm`。

前端（vitest）：
- `parseHash` 的 `?player=`；`seats.ts` 的 `"me"` 映射与「至多一个我自己」；
- `lib/toolCalls.ts` 每种工具的 ToolCall 构造；
- `turn` 切片消费 `your_turn` / `action_result` / `error` 帧；
- ActionBar：按 `available_tools` 渲染分支、倒计时到期禁用、pending 禁用、拒绝原因展示；
- Lobby 三步编排成功跳转、join 失败展示错误与删除按钮（mock API）。

## 7. 与后续工作的衔接

- 子项目二（阵营组队）只需在 `GameConfig` 加座位阵营约束并在 Lobby 加选项，本期的「我自己」座位与 `seat_users` 直接复用。
- 多真人：`join(seat, user_id)` 已绑定账号；未来加「邀请链接」和 start 前的等待大厅即可，`owner_seat()` 推广为「任一入座账号」时封锁规则改为按账号判定。
- #123 积分：真人座位不计分；`seat_users` 可作为将来按用户记分的来源。
