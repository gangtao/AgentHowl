# 历史对局与无 token 回放（issue #98）设计

## 1. 问题与判据

前端只有「新的一局 / Agent 档案库 / 模型服务」三个入口，没有历史对局菜单；回放一局必须保留建局时带 token 的链接，后端一重启（`make serve`、`docker compose`）这些链接全部 404——尽管 `backend/data/games/*.jsonl` 完整。根因（已核对）：

1. 没有对局列表接口（`JsonFileEventStore.list_games()` 存在但未暴露）。
2. 所有读接口经 `_handle_for()` 走内存 `GameRegistry`，启动不回载已结束对局。
3. token 只在内存（`TokenRegistry._tokens`），重启即失效，而 `/replay` 要求 token。

**完成判据**：后端重启后，前端「历史对局」页能列出 `data/games/` 里全部对局并逐局回放到终局；进行中的对局显示「直播中」；现有 token 流程（建局、直播、GM/观众链接）行为不变；全部测试与 lint 通过。

**访问策略（已决策：A）**：已结束对局**公开回放**——终局后观众视角本就拿全量事件流（M3 规格 §2 授权矩阵），无新泄露面。开关 `AGENTHOWL_PUBLIC_HISTORY`（默认开）供多用户场景关闭。进行中的对局一切不变。

## 2. 后端

### 2.1 对局摘要 `app/runtime/history.py`（纯函数 + 读 store，零网络）

```python
class GameSummary(BaseModel):
    model_config = ConfigDict(frozen=True)
    game_id: str
    preset: str                 # config.config_id
    num_players: int
    status: Literal["finished", "live", "aborted"]
    started_at: str | None      # 首条事件 meta.wall_ts（ISO）；无事件 → None
    ended_at: str | None        # GAME_OVER 事件 wall_ts；未终局 → None
    winner: str | None          # GameOverPayload.winner（"GOOD"/"WOLF"/None）
    rounds: int                 # max ROUND_STARTED.round；无 → 0
    seats: list[SeatSummary]    # {seat, display_name, agent: bool}  agent = str(seat) in meta.agents
    seq: int                    # 最后一条事件 seq

def summarize_game(meta: GameMeta, events: Sequence[Event], live: bool) -> GameSummary
def list_history(store: EventStore, registry: GameRegistry) -> list[GameSummary]
```

- `status`：事件流末条为 `GAME_OVER` → `finished`；否则 registry 里有 handle 且 `handle.task` 未完成 → `live`；否则 `aborted`（重启丢掉的中途局）。
- `list_history` 遍历 `store.list_games()`，损坏/无法解析的文件**跳过并 warning**（不让一局坏文件拖垮列表）；按 `started_at` 倒序（None 排最后），同值按 `game_id`。
- `store.list_games()` 对 `JsonFileEventStore` 已存在；`InMemoryEventStore` 同名方法已存在（测试用）。

### 2.2 端点（`app/api/rest.py`）

| 端点 | 变化 |
|---|---|
| `GET /api/v1/games` | 新增，返回 `list[GameSummary]`。开关开：无需 token；开关关：需任意有效 token（`require_token`），否则 401。 |
| `GET /games/{id}/replay`、`/meta`、`/speeches` | registry 无 handle 时**退回 store**：`store.load_meta` 可读且事件流末条为 `GAME_OVER` → 按原逻辑返回；否则 404。开关开：已结束对局不要求 token（有 token 也接受）；开关关：行为完全同现状。进行中的对局（有 handle）：行为完全同现状。 |
| `/state`、`/events`、WS | 不变（只服务进行中的对局）。 |

实现要点：

- 新依赖 `optional_token(creds, tokens) -> TokenInfo | None`（`HTTPBearer(auto_error=False)` 已有）；已结束对局的三个端点改用它：`info is None` 且开关关 → 401；`info` 非空则仍走 `require_kind`。
- 新 helper `_finished_meta_from_store(games, game_id) -> GameMeta`：`LookupError`（404）如果文件不存在；若存在但末条非 `GAME_OVER` → `HTTPException(403, "对局未结束…")`（与现状文案一致）。`_handle_for` 先试 registry：有 handle 走原路径；`LookupError` 时再走 store 回退。
- `/speeches` 的扫描函数 `games_store_events` 不依赖 handle，回退后直接复用。
- `create_app(..., public_history: bool | None = None)`；`None` 时读环境变量 `AGENTHOWL_PUBLIC_HISTORY`（`"0"/"false"/"no"` 为关，其余为开）；存 `app.state.public_history`。

### 2.3 安全边界

- 开关开时公开的只有**已结束**对局的全量事件流与 meta（含档案名、模型名、技能名；不含 Provider 密钥——meta 从不含密钥，#26 已验证）。
- 进行中对局的 `/state` `/events` WS 仍按 token 裁剪；`/replay` `/meta` 对进行中对局仍 403。
- 列表接口不返回 token、不返回 Provider 信息。

## 3. 前端

- `parseHash`：新增 `#/history` → `{route: "history"}`；`#/g/{id}?replay=1` → `{route: "game", gameId, replay: true, viewer: "GM"}`（无 token；`gm=` 存在时优先走原 token 路径）。
- `src/api/rest.ts`：`listGames(): Promise<GameSummary[]>`；`getMeta(id, token?)`、`getReplay(id, token?)` token 可选（无 token 不发 `Authorization`）。
- `src/store/history.ts`：`useHistory` → `{items, loading, error, refresh()}`（与 `useProviders` 同形）。
- `src/pages/History.tsx` + `components/HistoryTable`：表格列：开始时间（本地时区 `MM-DD HH:mm`）、板子（`PRESET_ZH` 名或 id）、人数、状态（已结束 / 直播中 / 中断）、胜方（好人胜 / 狼人胜 / —）、轮数、座位（档案名逗号串，Bot 显示 `Bot`）、操作：已结束 →「回放」链接 `#/g/{id}?replay=1`；直播中 →「用建局时的上帝/观众链接观看」提示文字；中断 → 「回放」（能放到中断处）。空态「还没有对局，去建一局」链到 `#/`。顶部「刷新」。
- `App.tsx`：导航加「历史对局」（`aria-current` 同规则）；路由 `history` → `History` 页。
- `GamePage` 引导：`replay === true` ⇒ 跳过 `/meta`→`/state` 探测，直接 `getMeta(id)` + `getReplay(id)`（无 token）→ `load(meta, {gameId, token: "", viewer: "GM", mode: "replay"})` → `appendEvents`；错误：404 →「对局不存在」，403 →「对局未结束，暂不可回放」，其它原文。顶栏模式文案「回放 · 上帝视角」。中断局（无 GAME_OVER）也能装入（后端按 `aborted` 仍开放？——**否**：后端只对 `GAME_OVER` 开放回放；中断局列表里「回放」按钮禁用并提示「中断于第 N 轮，无法回放」。保持服务端规则简单。）

## 4. 文档

- README「前端」小节加「历史对局」一段 + `AGENTHOWL_PUBLIC_HISTORY` 说明；「Docker 运行」里把「文件里的事件流可回放」改为指向历史页。
- PRD `docs/specs/requirements.md` §5.2 端点表加 `GET /games`，备注已结束对局公开回放策略与开关。

## 5. 测试

后端（零网络、`InMemoryEventStore` / `tmp_path`）：
- `summarize_game`：finished / live / aborted 三态、`winner`、`rounds`、`seats.agent`、时间戳；坏文件被跳过且 warning。
- `GET /games`：两局（一已结束、一进行中）→ 两行、状态正确、倒序；开关关 → 401。
- 回退：建局并打完后 **换一个新的 registry（模拟重启）** 共用同一 store → `/replay` `/meta` `/speeches` 无 token 200；进行中对局无 token → 401；开关关 → 已结束无 token 401、有 token 200。
- 现有 token 路径测试全部不变。

前端（vitest）：`parseHash` 新路由；History 页用假 `fetch` 渲染三种状态行与排序；GamePage `replay=1` 走无 token 引导（可用现有 bootstrap 测试模式）。

## 6. 范围外

删除对局、分页/搜索、token 持久化、进行中对局的无 token 观看、WS token 改首帧（#79）。
