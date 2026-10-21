# 多用户登录与资源归属 设计（issue #114）

> 状态：待评审。实现计划见 `docs/superpowers/plans/2026-10-21-multi-user-auth.md`（待写）。

## 0. 目标与边界

**目标**：平台从「本机单用户」变为**公网开放注册的多用户站点**。

- 任何人可注册（用户名 + 邮箱 + 密码，邮箱验证码），登录后使用平台。
- 两级角色：`admin` 拥有全部功能，可见可管所有人的对局 / Agent / Provider；`user` 只能看到并操作**自己创建的**对局、Agent、Provider。
- Provider 完全 BYOK：每个用户填自己的 key，Agent 只能引用自己的 Provider。平台（管理员）不替用户付 LLM 费用。
- 对局默认私有；拿到分享链接（带 share token）的任何人可匿名观战 / 回放。全局开关 `AGENTHOWL_PUBLIC_HISTORY` 废除。

**不在本期**（已记入 issue，见 §12）：密码找回邮件流、Provider 密钥加密落盘、会话设备管理、对局「公开」标记与公开大厅、多用户同场对战（#115 前置条件是本 issue，但本 issue 只为它留字段）。

**硬约束（沿用项目）**：引擎 `app/engine` 零改动；`app/runtime`、`app/api`、`app/cli` 不得模块级 import litellm；信息隔离只在服务端（`visible_events`）；前端零过滤；密钥永不回传、永不入日志。零新依赖：用户库用标准库 `sqlite3`，密码用 `hashlib.scrypt`，邮件用 `smtplib`。

## 1. 用户模型与存储

新模块 `app/runtime/users.py`。

```python
class User(BaseModel):
    model_config = ConfigDict(frozen=True)
    user_id: str                 # "u_" + 8 hex（secrets.token_hex(4)）
    username: str                # 3–32 位 ^[a-z0-9_]+$，入库前小写
    email: str                   # 小写归一；唯一
    password_hash: str           # 见 §2
    role: Literal["admin", "user"] = "user"
    status: Literal["active", "disabled"] = "active"
    email_verified_at: str | None = None   # ISO 秒级 UTC；None = 未验证
    created_at: str

class UserPublic(BaseModel):    # API 响应；永不含 password_hash
    user_id: str; username: str; email: str; role: ...; status: ...
    email_verified: bool; created_at: str

class Session(BaseModel):
    session_id: str              # secrets.token_urlsafe(32)
    user_id: str
    created_at: str
    expires_at: str              # created_at + 30 天（绝对过期；登录即新会话）

class EmailCode(BaseModel):
    user_id: str
    code_hash: str               # sha256(code)，6 位数字码
    expires_at: str              # 15 分钟
    attempts: int = 0            # 校验失败次数；≥ 5 作废
```

`UserStore` Protocol（同步方法，与现有 `AgentLibraryStore` 风格一致）：

```python
class UserStore(Protocol):
    def get(self, user_id: str) -> User | None: ...
    def get_by_username(self, username: str) -> User | None: ...
    def get_by_email(self, email: str) -> User | None: ...
    def list(self) -> list[User]: ...
    def put(self, user: User) -> None: ...          # 插入或整体替换；唯一键冲突抛 UserConflictError
    def count(self) -> int: ...
    def create_session(self, s: Session) -> None: ...
    def get_session(self, session_id: str) -> Session | None: ...   # 已过期返回 None 并顺手删除
    def delete_session(self, session_id: str) -> None: ...
    def delete_sessions_of(self, user_id: str) -> None: ...
    def put_email_code(self, c: EmailCode) -> None: ...             # 每用户只保留最新一条
    def get_email_code(self, user_id: str) -> EmailCode | None: ...
    def delete_email_code(self, user_id: str) -> None: ...
```

两个实现：`InMemoryUserStore`（测试）与 `SqliteUserStore(path)`（默认 `data/users.db`，三张表 `users` / `sessions` / `email_codes`，`username`、`email` 唯一索引，`PRAGMA journal_mode=WAL`，每次调用开关连接，`check_same_thread=False` 不需要）。两个实现跑同一套契约测试（参数化 fixture）。

`UserConflictError(ValueError)`：用户名或邮箱已存在；API 层映射 409。

## 2. 密码与密钥

- `hash_password(pw) -> str`：格式 `scrypt$<n>$<r>$<p>$<salt_b64>$<hash_b64>`，`n=2**14, r=8, p=1, dklen=32`，salt 16 字节。`verify_password(pw, stored) -> bool` 用 `hmac.compare_digest`，解析失败返回 False（不抛）。
- 密码规则：8–128 个字符，不做复杂度要求。
- 站点密钥 `app/runtime/secret.py`：`load_secret(data_dir, env="AGENTHOWL_SECRET_KEY") -> bytes`。环境变量存在则用其 UTF-8 字节；否则读 `data/secret.key`；都没有则 `secrets.token_bytes(32)` 写入该文件（0600）并打 INFO。密钥只用于 §6 的 share token；泄漏或轮换只影响分享链接。

## 3. 注册、验证、登录（`app/api/auth.py`，前缀 `/api/v1/auth`）

| 方法 路径 | 请求 | 成功 | 失败 |
|---|---|---|---|
| POST `/register` | `{username, email, password}` | 201 `{user: UserPublic, verification: "email" \| "auto"}` | 422 格式；409 用户名/邮箱已存在；429 限流 |
| POST `/verify` | `{email, code}` | 200 `{ok: true}` 并**自动登录**（设 cookie） | 400 码错/过期/超次（统一文案「验证码无效或已过期」）；404 邮箱不存在 → 也回 400 同文案 |
| POST `/resend` | `{email}` | 200 `{ok: true}`（邮箱不存在或已验证**同样返回 200**，不泄露存在性） | 429 |
| POST `/login` | `{identifier, password}`（用户名或邮箱） | 200 `{user: UserPublic}` + cookie | 401 `{detail:"用户名或密码错误"}`（统一）；401 `{detail:"邮箱未验证", reason:"unverified"}`；403 账号已禁用；429 |
| POST `/logout` | — | 204，删会话、清 cookie | — |
| GET `/me` | — | 200 `UserPublic` | 401 未登录 |

- 注册：`SmtpMailer` 可用（§4）→ 生成 6 位码、存 `EmailCode`、发邮件，`verification="email"`；`NullMailer` → 直接 `email_verified_at=now`，`verification="auto"`，不自动登录（前端引导去登录页）。
- 验证成功：写 `email_verified_at`，删码，建会话。
- 登录：先查用户名再查邮箱；密码错 / 用户不存在同一文案；未验证 401 带 `reason`；禁用 403。成功建会话。
- 会话 cookie：名 `agenthowl_session`，`HttpOnly`，`SameSite=Lax`，`Path=/`，`Max-Age=30 天`，`Secure` 由 `AGENTHOWL_COOKIE_SECURE`（默认 `1`；本地 http 调试设 `0`）决定。
- 依赖注入（同文件）：

```python
def current_user(request) -> User | None     # cookie → session → user；会话过期/用户禁用 → None（并删会话）
def require_user(...) -> User                 # None → 401 {"detail":"未登录"}
def require_admin(...) -> User                # 非 admin → 403 {"detail":"需要管理员权限"}
```

- 限流 `app/runtime/ratelimit.py`：`RateLimiter(rules: dict[str, tuple[int, float]])` 内存滑动窗口，键 `(rule, ip)`；规则 `register 5/3600s`、`login 10/60s`、`resend 3/3600s`、`verify 10/60s`。超限 429 `{"detail":"请求过于频繁，请稍后再试"}`。IP 取 `request.client.host`；`AGENTHOWL_TRUST_PROXY=1` 时取 `X-Forwarded-For` 第一个。测试用 `RateLimiter.disabled()`。
- 管理员引导：`create_app` 启动时若 `AGENTHOWL_ADMIN_USERNAME` / `AGENTHOWL_ADMIN_EMAIL` / `AGENTHOWL_ADMIN_PASSWORD` 三者齐全且该用户名不存在 → 创建 `role=admin`、已验证；三者只配了部分 → 启动 `ValueError`（fail-loud）。启动后用户表里没有任何 admin → `logger.warning`。

CSRF：cookie `SameSite=Lax` + 所有写操作为 JSON body + 无 CORS 中间件，跨站表单与跨站 fetch 都到不了；不另加 CSRF token。

## 4. 邮件（`app/runtime/mailer.py`）

```python
class Mailer(Protocol):
    async def send(self, to: str, subject: str, body: str) -> None: ...
class NullMailer:   # 未配置 SMTP：send 只打 DEBUG；create_app 打 WARNING「未配置 SMTP，注册免邮箱验证」
class SmtpMailer:   # smtplib，在 asyncio.to_thread 里发；STARTTLS 可选
class MailConfig:   # from_env：AGENTHOWL_SMTP_HOST / PORT(587) / USER / PASSWORD / FROM / STARTTLS(1)
```

`MailConfig.from_env()`：`HOST` 为空 → `None`（用 NullMailer）；`HOST` 有而 `FROM` 空 → `ValueError`。验证码邮件正文固定中文模板：「您的 AgentHowl 验证码：123456，15 分钟内有效。」发送失败（`smtplib` 异常）→ 注册仍成功，响应 `verification: "email"`，日志 ERROR；用户可 `/resend`。

## 5. 归属模型

三个实体新增 `owner_id: str | None = None`：

| 实体 | 落点 | 旧数据 |
|---|---|---|
| 对局 | `GameMeta.owner_id`（`store/event_store.py`，JSONL 首行） | `None` |
| Agent | `StoredAgent.owner_id`（`runtime/agent_library.py`） | `None` |
| Provider | `Provider.owner_id`（`agent/provider.py`；`ProviderPublic` 不带） | `None` |

规则函数 `can_access(user: User, owner_id: str | None) -> bool`（`app/api/auth.py`）：`admin` 恒 True；否则 `owner_id == user.user_id`。`owner_id is None` 的旧数据只有 admin 可见。

- **Agent 库**：`GET /agents` 普通用户只回自己的，admin 回全部（`StoredAgent` 本就带 `owner_id`，前端按需显示）。POST 写 `owner_id=user.user_id`。GET/PUT/DELETE `/agents/{id}`：不可访问 → **404**（不泄露存在性）。名称与 `memory_id` 唯一性改为**按 owner**（`_check_profile` 的遍历只看同 owner）。`profile.provider` 必须是本人（或 admin 时任意）可访问的 Provider，否则 400。
- **Provider**：同上。`test` / `models` 端点同样按归属 404。
- **对局**：`POST /games` 需登录，`GameMeta.owner_id = user.user_id`；`agents` 里引用的 provider 按同规则校验。`GET /games` 普通用户只列自己的；admin 列全部。`GameSummary` 新增 `owner_id: str | None` 与 `owner_name: str | None`（admin 列表显示用；普通用户看到的是自己）。`DELETE /games/{id}` 需登录且 `can_access`，否则 404；仍保留「进行中不可删 409」。`POST /start` 不变（host_token）。
- **跨局记忆**：目录按 owner 分：`data/agent_memory/<owner_id>/<memory_id>.json`。`GameRegistry` 的 `experience_store` 参数改为工厂 `experience_store_for: Callable[[str | None], ExperienceStore]`；默认实现 `owner_id is None → JsonFileExperienceStore(memory_dir)`（CLI / 旧数据），否则 `JsonFileExperienceStore(memory_dir / owner_id)`。`create(...)` 新增 `owner_id` 参数。`opponent_notes` 的键是对手 memory_id，同一局里全部档案同 owner，命名空间自洽。
- **头像、声线锚点、旁白缓存**：内容寻址，全局共享，不加 owner。`PUT /avatars`、`POST /voices/design` 需登录；两个 GET 保持公开（id 不可猜，且 `<img>`/`<audio>` 本来也会带 cookie）。
- **只读元数据** `GET /skills`、`GET /presets`：需登录。`GET /tts/status`：需登录。
- 新增 `GET /api/v1/health` → `{"ok": true}`，无鉴权；Dockerfile healthcheck 改打它。

迁移 CLI `app/cli/claim.py`：`python -m app.cli.claim --user <username> [--data-dir data] [--dry-run]`。把全部 `owner_id is None` 的对局（重写 JSONL 首行，先写 `.tmp` 再 `os.replace`）、Agent、Provider 划给该用户；把 `data/agent_memory/*.json` 根目录文件移入 `<owner_id>/`。输出每类数量。

## 6. 对局 token、分享与视角

`TokenInfo` 新增 `user_id: str | None = None`（建局者的 host/gm token 与登录入座的 player token 带上；外部 Agent 入座为 None）。内存 `TokenRegistry` 不变。

**分享 token**（替代内存里的 spectator token）：

```python
def share_token(secret: bytes, game_id: str) -> str:
    return hmac.new(secret, f"share:{game_id}".encode(), "sha256").hexdigest()[:32]
def verify_share_token(secret, game_id, token) -> bool   # compare_digest
```

- `CreateGameResponse.spectator_token` 改名 `share_token: str | None`（`allow_spectators=False` → None，但终局后分享 token 仍可回放）。`GameSummary` 新增 `share_token: str`（列表里的局本人都可访问，直接给）。
- 视角解析统一为 `resolve_viewer(request, game_id) -> TokenInfo`（`app/api/rest.py`，替换现有 `_viewer_for` 与 ws 内联逻辑），按顺序：
  1. `Authorization: Bearer` 或 `?token=` 的**对局 token**（HOST/PLAYER/GM）→ 原语义；
  2. `?share=` 合法 → `kind="SPECTATOR"`，直播期间要求 `handle.allow_spectators`，否则 403；终局一律放行；
  3. 会话 cookie 且 `can_access(user, meta.owner_id)` → `kind="GM"`；
  4. 都没有 → 401。
- 受影响端点：`/state`、`/events`、`/speeches`、`/replay`、`/meta`、`/avatars`、`/audio`、`/audio/{seq}/{part}` 全部改走 `resolve_viewer`；`_finished_or_handle` 与 `_require_history_access`、`public_history` 删除。
- WS `/api/v1/ws`：参数 `token`（对局 token，原样）或 `game_id` + `share`，或 `game_id` + cookie（Starlette `websocket.cookies`）。解析失败关闭码不变（4401/4403/4404/4409）。
- `POST /games/{id}/join`：需 **登录会话** 或 **Bearer host_token**。登录入座 → `TokenInfo.user_id` 记录；host_token 入座（外部 Agent 客户端）→ `user_id=None`。两者都没有 → 401。`JoinRequest` 不变。

## 7. 管理员（`app/api/admin.py`，前缀 `/api/v1/admin`，全部 `require_admin`）

| 方法 路径 | 说明 |
|---|---|
| GET `/users` | 全部 `UserPublic`，按 `created_at` 升序 |
| PATCH `/users/{id}` | body `{role?: "admin"\|"user", status?: "active"\|"disabled"}`。禁用 → 同时 `delete_sessions_of`。守卫：不能改自己的 role/status（400）；不能把最后一个 active admin 降级或禁用（400） |
| POST `/users/{id}/verify` | 手工标记邮箱已验证（SMTP 故障兜底） |

## 8. 前端

- 路由（`api/tokens.ts`）：新增 `login`、`register`、`verify`、`admin`；`#/g/{id}?gm=` 不变；`?spec=` 改为 `?share=`（`viewer: "SPECTATOR"`）；删除 `?replay=1`；裸 `#/g/{id}` → `viewer: "GM"`、`token: undefined`（靠登录态）。`Viewer` 类型不变。
- `store/auth.ts`（zustand）：`{user: UserPublic | null, status: "loading" | "anon" | "authed", load(), login(), logout(), register(), verify()}`。`App.tsx` 启动 `load()`（`GET /auth/me`）；`status === "loading"` 显示空白加载；受保护路由（lobby / history / agents / providers / admin）在 `anon` 时渲染 `LoginPage`（登录后回到原路由）；`game` 路由不强制登录（分享链接）。
- `api/rest.ts` `req()`：`credentials: "same-origin"`；收到 401 且当前 `authed` → `auth.load()` 重新确认（会话过期则自动回到登录页）。`ApiError` 新增 `reason?: string`（登录未验证跳验证页）。
- 新页面 `pages/LoginPage.tsx`（登录 / 注册 / 验证码三个 tab 或三段）、`pages/AdminUsers.tsx`（表格 + 角色/状态切换 + 手工验证）。导航右侧：用户名、`admin` 标签、「登出」；admin 多「用户」入口。
- History：admin 多一列「创建者」；行点击 → `#/g/{id}`（登录态 GM）；「分享」按钮用 `share_token` 生成 `#/g/{id}?share=`。ShareDialog 改用 share 链接；Lobby 建局后跳 `#/g/{id}?gm=` 不变。
- GamePage：无 token 且 `viewer="GM"` 时 REST/WS 不带 token（cookie）；WS url 改为 `wsUrl({token} | {gameId, share} | {gameId})`。未登录又无 token → 现有错误态文案改为「请登录或使用分享链接」。
- 前端零过滤原则不变：所有列表、视角数据仍由服务端裁剪。

## 9. 配置、部署、文档

新增环境变量（`.env.example` + README「多用户」小节）：`AGENTHOWL_SECRET_KEY`、`AGENTHOWL_USERS_DB`（默认 `data/users.db`）、`AGENTHOWL_COOKIE_SECURE`、`AGENTHOWL_TRUST_PROXY`、`AGENTHOWL_ADMIN_USERNAME/EMAIL/PASSWORD`、`AGENTHOWL_SMTP_HOST/PORT/USER/PASSWORD/FROM/STARTTLS`。删除 `AGENTHOWL_PUBLIC_HISTORY`。README 写清：零配置启动 = 免邮箱验证 + 无管理员（需配 ADMIN 三件套或用 `claim`）；公网部署必须反代 HTTPS + `COOKIE_SECURE=1` + `TRUST_PROXY=1`。

`create_app` 新增参数：`user_store: UserStore | None`、`users_db: Path | None`、`mailer: Mailer | None`、`secret: bytes | None`、`rate_limiter: RateLimiter | None`、`memory_dir` 语义改为根目录。`app.state` 新增 `users`、`mailer`、`secret`、`rate_limiter`。

PRD `docs/specs/requirements.md`：§5.4 改为「认证、用户与会话」（对局 token + 会话 cookie + share token 三层）；§4.4.5 删去「单用户本地部署假设」句，改为「Provider 按用户归属（BYOK），密钥仍明文 0600，加密落盘见后续 issue」。

## 10. 安全要点（实现与评审清单）

- `password_hash`、`session_id`、验证码明文永不进响应、日志、异常文案；`User.__repr__` 不含 hash（`Field(repr=False)`）。
- 登录失败文案统一；`/resend` 不泄露邮箱存在性；跨 owner 访问一律 404。
- `data/secret.key`、`data/users.db` 0600；sqlite 目录与 providers 同策略。
- `Secure` cookie 默认开；文档明示本地 http 需关。
- 旧的 `?token=` 访问日志脱敏（`main.py`）扩展到 `share=`（不敏感但统一）与 cookie 不入日志（uvicorn 默认不打 cookie）。
- 限流只防暴力，不替代验证码；admin 守卫防止自锁。

## 11. 测试

- 单元：`test_users_store.py`（InMemory / Sqlite 参数化契约：唯一键、会话过期、验证码次数）、`test_password.py`、`test_secret.py`（生成/读取/权限/HMAC 稳定）、`test_ratelimit.py`、`test_mailer.py`（NullMailer、MailConfig.from_env 的三种情况）。
- API：`test_api_auth.py`（注册→验证→登录→me→登出全流程；auto 模式；错误文案；限流 429；禁用 403）、`test_api_ownership.py`（两个用户 + admin：agents/providers/games 列表隔离、跨 owner 404、名称按 owner 唯一、provider 引用校验、旧无主数据只 admin 可见）、`test_api_share.py`（share 直播/终局/allow_spectators=False；cookie GM；裸访问 401；WS 三种入口）、`test_api_admin.py`（守卫）、`test_cli_claim.py`。
- 现有测试：`tests/` 新增 `conftest.py` 夹具 `app_factory`（InMemoryUserStore + NullMailer + RateLimiter.disabled()）、`admin_client`、`user_client(name)`（已登录的 TestClient，cookie 自动携带）；现有无认证建局的测试统一改用 `user_client`。e2e 外部 Agent 入座改带 host_token。
- 前端：`store/auth.test.ts`、`api/tokens.test.ts`（新路由、share、裸 game）、`pages/LoginPage.test.tsx`、`pages/AdminUsers.test.tsx`、`History.test.tsx`（创建者列、分享链接）、`GamePage.test.tsx`（cookie 模式）。
- 全套门禁：后端 pytest（`--ignore=tests/test_api_e2e.py` 按 #74 惯例另跑）、ruff、mypy strict、litellm 守卫、引擎零改动；前端 `npm run check`。

## 12. 后续 issue（本 spec 定稿时创建）

1. 密码找回：邮件重置链接流（复用 Mailer 与 EmailCode）。
2. Provider 密钥加密落盘（`cryptography` Fernet，密钥派生自 `AGENTHOWL_SECRET_KEY`），含迁移。
3. 会话管理：查看 / 踢出设备，密码修改。
4. 对局「公开」标记 + 公开大厅列表。
