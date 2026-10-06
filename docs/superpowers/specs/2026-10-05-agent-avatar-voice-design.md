# Agent 头像与语音设计（issue #102 头像、#103 语音）

## 1. 背景与目标

每个座位目前只有「角色缩写圆片 + 名字」，发言纯文字。目标是让 agent 更像"人"：
有一张脸（头像），发言时用自己的声线实时念出来，且对局节奏等语音说完再轮到下一位。

决策（brainstorm 结论）：

- 头像：用户本地生成后**上传**，不接任何图像生成 API。
- 语音：**本地实时**推理，越快越好。本机 M2 Pro / 16 GB 实测 Qwen3-TTS（mlx-audio，6-bit）
  RTF 0.45–0.74（1.4–2.3× 实时），按句切分后首句 1.0–1.6 s 出声。
- 后端只说 OpenAI `POST /v1/audio/speech` 这一种协议（本版标准，其他私有协议以后再扩展）。
- 节奏：**同步**（发言窗口至少停留到语音播完）。
- 方言：v1 只有北京话 / 四川话（预置声线）。spike 用 Whisper 检测：开源权重的方言表只有
  `beijing_dialect / sichuan_dialect`，VoiceDesign 写"用粤语"出的是普通话，"上海话"出乱音。
  粤语等以后用克隆（参考音频）或云端 TTS 另立 issue。
- v1 只给玩家发言配音（`PLAYER_SPOKE` / `LAST_WORDS`），不做系统旁白。

拆两步交付：**头像**（issue #102，小）→ **语音**（issue #103，大）。本文档覆盖两者；各自单独出实现计划。

### 非目标

- 图像生成、头像裁剪/缩放（前端用 `object-fit: cover`）、孤儿头像清理。
- 粤语/上海话等方言、声音克隆（`mode="clone"` 预留，不实现）、系统旁白、口型/动画。
- 阿里百炼 / 火山 / MiniMax 等非 OpenAI 协议的 TTS。
- 前端"自己合成"（浏览器 `speechSynthesis`）。

## 2. 档案数据模型（两步共用）

`AgentProfile`（`backend/app/agent/profile.py`，`frozen`、`extra="forbid"`）加两个可选字段，默认 `None`，
旧 JSON 兼容。两者都**不进 LLM 上下文**：`to_agent_config` 不读它们，observation / prompt 不含。

```python
class VoiceSpec(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    mode: Literal["preset", "design"]
    speaker: str | None = None   # preset：PRESET_SPEAKERS 之一
    style: str | None = None     # preset：情绪/语速指令（可空）；design：声线描述（必填）
    speed: float = 1.0           # [0.5, 2.0]

PRESET_SPEAKERS = ("vivian", "serena", "uncle_fu", "dylan", "eric")  # dylan=北京话 eric=四川话

class AgentProfile(BaseModel):
    ...
    avatar: str | None = None   # 头像资源 id，形如 "3f9a1c0b7e2d4a66.png"
    voice: VoiceSpec | None = None
```

校验（pydantic `model_validator`）：

- `mode="preset"`：`speaker` 必填且 ∈ `PRESET_SPEAKERS`；`style` ≤ 200 字。
- `mode="design"`：`style` 必填、1–200 字；`speaker` 必须为 `None`。
- `speed` ∈ [0.5, 2.0]。
- `avatar` 匹配 `^[0-9a-f]{16}\.(png|jpg|webp)$`（路径穿越防护；不校验文件是否存在，缺图前端退占位）。

用**内容 id** 而不是 agent_id 做头像引用的原因：`GameMeta.agents` 原样落盘 `AgentProfile`，回放时按
`meta.agents[seat].avatar` 就能取图；复制档案共享同一文件；同一张图多次上传不重复存。

## 3. 头像（issue #102）

### 3.1 存储与端点

- 目录 `data/avatars/`（`create_app(avatars_dir=...)`，默认 `Path("data/avatars")`，首次上传时惰性创建）。
- `PUT /api/v1/avatars`：**raw body**（`Content-Type: image/png | image/jpeg | image/webp`），
  不用 multipart（避免 `python-multipart` 依赖）。
  - 上限 512 KB（读 body 前先看 `Content-Length`，超限 413；无长度则读到上限 + 1 字节判定）。
  - 按**魔数**判类型（PNG `89 50 4E 47`、JPEG `FF D8 FF`、WebP `RIFF....WEBP`），忽略 `Content-Type`
    （只信字节）；不认识 → 415。
  - `avatar_id = sha256(bytes)[:16] + "." + ext`；已存在则不重写（幂等）；原子写（tmp + `os.replace`），
    不需要 0600（非敏感）。
  - 响应 `200 {"avatar_id": "...", "bytes": n}`。无鉴权——头像随 `/meta` 对已结束对局公开，本就不是秘密。
- `GET /api/v1/avatars/{avatar_id}`：id 正则校验（不匹配 404），`FileResponse`，`Cache-Control: public, max-age=31536000, immutable`
  （内容寻址，可永久缓存）；不存在 404。
- 不提供 DELETE：档案移除头像只是把字段置 `None`，文件留着（回放可能还引用）。

### 3.2 前端

- `src/api/avatars.ts`：`uploadAvatar(file: File) -> {avatar_id}`（`fetch` PUT，body 为 `File`，
  `Content-Type` 取 `file.type`）、`avatarUrl(id) = /api/v1/avatars/${id}`。
- `components/Avatar/Avatar.tsx`：`{avatar: string|null, name: string, seat?: number, size}` —— 有 id 渲染 `<img>`
  （`object-fit: cover`、圆形、`onError` 退占位），否则占位：名字首字（空名用座位号）+ 座位色背景
  （复用 `seatColor.ts`）。
- `AgentEditor`：头像区（当前头像/占位、「上传」文件选择 `accept="image/png,image/jpeg,image/webp"`、
  「移除」）；前端先检查大小 ≤ 512 KB，超限直接提示不发请求；上传成功写入 `form.avatar`。
  JSON 导入/导出原样带 `avatar` 字段。
- 显示位置：`SeatCircle` 圆片用 `<Avatar>` 替换角色缩写，缩写缩成左下角标（未知角色仍显示 `?`，
  保持零过滤——角色来自服务端视角数据）；`SpeechFeed` 发言卡头部；`SeatAssignment` 与档案列表行首小头像。
  头像 id 来源：对局页调 `GET /api/v1/games/{id}/avatars`（座位 → id；直播中需本局任意 token，终局公开策略
  同 `/replay`；来源为已开局的 `GameMeta.agents`，未开局为 `handle.agents`；快照里无头像的座位按档案名在当前档案库回退），直播/回放同一条路，取不到只是没图；发言时左栏座位环下方有「发言者聚光牌」放大显示头像与名字；
  档案页用 `profile.avatar`。

### 3.3 测试

- 后端：上传 PNG/JPEG/WebP 各一 → id 形如 `<16hex>.<ext>`、文件落盘、重传同内容 id 相同且不重写
  （mtime 不变）；超 512 KB → 413；伪造 Content-Type（body 是文本）→ 415；读取 404/200 + 缓存头；
  `avatar` 字段正则（`../x.png`、`abc.gif` → ValidationError）；`to_agent_config` 不受影响；
  `GameMeta` 往返保留 `avatar`。
- 前端：`Avatar` 有/无 id、`onError` 退占位；`AgentEditor` 上传流程（mock fetch）与超限提示；
  `SeatCircle` 有头像时渲染 `<img>`、无头像渲染首字。

## 4. 语音（issue #103）

### 4.1 TTS 客户端（后端，不引入 MLX）

配置（环境变量 / `create_app` 参数）：

| 变量 | 默认 | 说明 |
|---|---|---|
| `AGENTHOWL_TTS_URL` | 空 = 语音关闭 | OpenAI-speech 兼容服务根地址，如 `http://127.0.0.1:8880` |
| `AGENTHOWL_TTS_KIND` | `mlx_audio` | `mlx_audio` / `openai` / `generic`：决定扩展字段映射 |
| `AGENTHOWL_TTS_MODEL_PRESET` | `mlx-community/Qwen3-TTS-12Hz-1.7B-CustomVoice-6bit` | `mode=preset` 用的 `model` |
| `AGENTHOWL_TTS_MODEL_DESIGN` | `mlx-community/Qwen3-TTS-12Hz-1.7B-VoiceDesign-6bit` | `mode=design` 用的 `model` |
| `AGENTHOWL_TTS_API_KEY` | 空 | `openai` 类服务的 Bearer；永不回传、不落日志 |

`app/runtime/tts.py`：

```python
class TtsClient(Protocol):
    async def synthesize_sentences(self, text: str, voice: VoiceSpec) -> AsyncIterator[AudioPart]: ...
    async def probe(self) -> TtsStatus: ...

class AudioPart(BaseModel): index: int; wav: bytes; duration_sec: float
class TtsStatus(BaseModel): enabled: bool; ok: bool; url: str | None; detail: str | None; supports_style: bool
```

- 分句：按 `。！？；\n` 切，保留标点；连续短句合并到 ≥ 8 字；空白句丢弃；上限 40 句（更长截断并 WARNING）。
- 每句一个 `POST {url}/v1/audio/speech`，请求体：

  | 字段 | `mlx_audio` | `openai` | `generic` |
  |---|---|---|---|
  | `model` | 按 mode 选模型 | `AGENTHOWL_TTS_MODEL_PRESET` | 同左 |
  | `input` | 句子 | 句子 | 句子 |
  | `voice` | preset：`speaker`；design：**不发**（服务端按 `instruct` 设计声线） | `speaker or "alloy"` | `speaker or "alloy"` |
  | `speed` | `speed` | `speed` | `speed` |
  | `response_format` | `wav` | `wav` | `wav` |
  | 扩展 | `instruct=style`、`lang_code="chinese"` | `instructions=style` | 无（style 丢弃） |

  单句超时 20 s；非 2xx / 超时 / 非 WAV（头不是 `RIFF`）→ 抛 `TtsError`。`duration_sec` 从 WAV 头算
  （`data` 块字节 / 字节率），不引入音频库。
- `probe()`：`GET {url}/v1/models`，2 s 超时；成功 → `ok=True`；`enabled=False` 当 URL 为空。
- `httpx` 补进 `pyproject` 主依赖（目前只在 dev）。
- `GET /api/v1/tts/status` → `TtsStatus`（无鉴权；不含 api key）。

本地服务：仓库新增 `tts/`（独立 uv 项目：`pyproject.toml` 依赖 `mlx-audio`，仅 macOS arm64），
`make tts` = `cd tts && uv run python -m mlx_audio.server --host 127.0.0.1 --port 8880`，
首次调用时按 `model` 懒加载并自动下载。`.env.example` / `docker-compose.yml` 注释示例
`AGENTHOWL_TTS_URL=http://host.docker.internal:8880`。README 写明：无 Apple Silicon 可指向任何
OpenAI-speech 兼容服务（vLLM-Omni、Kokoro-FastAPI 等，`AGENTHOWL_TTS_KIND=generic`）。

### 4.2 节奏同步（引擎零改动）

- `CreateGameRequest.voice: bool = False`；`GameHandle.voice_enabled`。建局时 `voice=True` 但
  `tts.probe().ok` 为假 → 400「TTS 服务不可用」。`CreateGameResponse` 回显 `voice`。
- `GameRunner` 新增可选依赖 `speech_audio: SpeechAudioSink | None`（runtime 层注入；引擎不知道）。
  `_drive_seat` 中，提交的行动产生 `PLAYER_SPOKE` 或 `LAST_WORDS` 事件且 `_commit` 完成后：

  ```
  if sink and profile_for(seat).voice:
      await sink.speak(game_id, event, text, voice)   # 内部：逐句合成→落盘→推帧→等待
  ```
  `speak()` 的停留时间 = 从**第一句推送**起累计 `Σ duration_sec` + 0.3 s；生成快于播放，所以等待由
  音频长度主导。合成失败（`TtsError`）→ WARNING，已推的句子照常等待，未推的跳过，对局继续。
  随机 bot、真人、无 `voice` 档案的座位不等待（现状）。
- 音频落盘 `data/audio/<game_id>/<seq>-<k>.wav`（`create_app(audio_dir=...)`，默认 `data/audio`）。
- WS 帧（经 `ConnectionManager.broadcast`，**不是**游戏事件：不进事件日志、不进 reducer、不进
  golden fixtures）：

  ```json
  {"type": "speech_audio", "seq": 57, "part": 0, "url": "/api/v1/games/g_x/audio/57/0",
   "duration": 2.3, "last": false}
  ```
  `last=true` 标记最后一句。观众/玩家/GM 都收（发言本就公开）。
- `GET /api/v1/games/{id}/audio` → `{"<seq>": [{"part": 0, "duration": 2.3}, ...]}`（扫目录 + 读 WAV 头）；
  `GET /api/v1/games/{id}/audio/{seq}/{part}` → WAV 文件。两者权限策略**同 `/replay`**
  （`_finished_or_handle`，`require_finished=False`：直播中持 token 也能取，匿名只在终局 + 开关开）。
- `DELETE /games/{id}` 连带 `rmtree(data/audio/<id>)`；`list_history` 不受影响。

### 4.3 前端播放

- `src/store/voice.ts`（zustand）：`enabled`（默认 `false`；用户点 🔊 后 `true` 并 `localStorage` 记住；
  浏览器 autoplay 策略要求首次有手势）、`queue: SpeechAudio[]`、`playing: {seq, part} | null`、
  `enqueue()`、`clear()`。播放用单个 `HTMLAudioElement`，`ended` 后播下一条；`enabled=false` 时帧照常入队但不播，
  开启时从队尾最新 seq 开始（不补播历史）。
- 直播：`api/ws.ts` 识别 `speech_audio` 帧 → `useVoice.enqueue`。`SeatCircle` 当前 `playing.seq` 对应的发言座位
  加 `data-voicing` 动效。
- 回放：`load(mode="replay")` 时拉 `/audio` 清单；`makeTick` 推进到有音频的发言事件时：暂停定时器，
  按 part 顺序播放，播完恢复；`enabled=false` 则按原 speed 推进不等待。拖动游标 / 暂停 → `clear()` 停止播放。
- 零过滤：只播服务端推来的 url。

### 4.4 测试

- `VoiceSpec` 校验矩阵；分句函数（标点、合并、上限）；`TtsClient` 用 `httpx.MockTransport`：三种 kind 的请求体字段、
  超时/非 WAV 抛错、WAV 时长计算、`probe()`。
- runner：注入假 sink（固定每句 0.2 s、两句）→ 发言窗口耗时 ≥ 0.4 s 且无 voice 座位不等待；sink 抛错不影响终局；
  `app/engine` 零 diff、fixtures 不变。
- API：`/tts/status` 开/关；建局 `voice=True` 探测失败 400；音频清单与文件端点权限（复用 history 测试的
  重启/开关/匿名矩阵）；删局清理目录；WS 帧形状（用 `_build_event_frames` 旁路，断言不进 `/replay`）。
- 前端：voice store 队列顺序与 `enabled` 切换；`ws.ts` 帧分发；回放暂停-播放-继续（mock `Audio`）；
  `AgentEditor` 的 voice 表单（preset 下拉 + style、design 描述必填、speed 滑块）。

## 5. 安全与信息隔离

- 头像、音频都只承载**公开**内容（发言本就全员可见）；音频端点权限与 `/replay` 完全一致，不新增泄露面。
- `AGENTHOWL_TTS_API_KEY` 永不出现在响应、日志、`GameMeta`。
- `avatar` id 与音频路径都经正则/整数校验后再触盘；`data/avatars`、`data/audio` 不整目录挂 `StaticFiles`。
- TTS 请求只发发言正文，不带私聊、角色或任何隐藏信息。

## 6. 兼容

- 旧档案 JSON 无新字段 → `None`。旧对局无音频目录 → 清单空，回放按原 speed。
- `voice=False`（默认）的对局与现状逐字一致；未配置 `AGENTHOWL_TTS_URL` 时 `/tts/status.enabled=False`，建局页不显示语音开关。
