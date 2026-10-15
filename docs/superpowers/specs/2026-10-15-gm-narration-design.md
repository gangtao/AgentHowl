# GM 旁白 / 游戏进程统一配音 设计（issue #110）

> 依赖：#106 发言配音（已合并）、#112 终审跟进（已合并）。
> 相关：#107 方言、#109 CPU TTS。

## 1. 目标与边界

- GM / 系统播报出声：阶段切换、夜间结算、死亡宣告、竞选与投票结果、终局等，用**一条固定旁白声线**（环境变量配置，默认 `uncle_fu`），全部对局共用。
- 旁白与玩家发言走**同一套** `speech_audio` 帧、同一个落盘目录、同一套前端播放队列与回放门控；runner 在事件提交后等旁白播完再推进（节奏同发言）。
- 旁白句子**整句缓存**（用户决策 A）：模板渲染出的每个完整句子按哈希缓存在 `data/narration/`，首次出现合成一次，跨对局复用。不做片段拼接。
- 信息隔离**按视角过滤**（用户决策 A）：旁白帧只投递给能看到对应事件的视角；直播期间音频清单与文件端点同样按视角过滤。过滤仍只经 `app.engine.observation.visible_events`，不自造逻辑。
- 默认播报事件白名单见 §3，环境变量可改（用户决策：默认这样，后面可配置）。

不在本期：
- 旁白声线在建局页可选（只有环境变量）。
- 批量预合成模板句（缓存随对局自然填满；只预热旁白声线以装载模型）。
- 为旧对局补配旁白（与 #106 一致：回放只播当时录下的音频）。
- 引擎可见性调整（夜间阶段切换是 `GM_ONLY`，本期照此过滤，不改引擎）。

## 2. 现状要点（设计依据）

- `SpeechAudioSink.speak()`：逐句合成 → `data/audio/<game_id>/<seq>-<k>.wav` → `broadcast_frame({"type":"speech_audio", seq, part, url, duration})` → `speech_audio_end` → 等到预计播完时刻 + 0.3 s。
- `ConnectionManager.subscribe_frames(cb)` / `broadcast_frame(frame)`：帧订阅不带 viewer、不过滤——目前只承载公开发言。
- `GameRunner._maybe_speak(seat, events)` 在 `_commit` 之后调用，只看 `PLAYER_SPOKE` / `LAST_WORDS`。
- 一局真实日志（9 人局）里各事件可见性：`PHASE_CHANGED` 夜间子阶段 / `ROUND_STARTED` / `NIGHT_RESOLVED` / `ROLES_ASSIGNED` / `WOLF_KILL_DECIDED` 为 `GM_ONLY`；`WOLF_KILL_PROPOSED` 为 `WOLVES`；`SEER_CHECKED` 为 `ROLE_SELF`；白天阶段切换与其余进程事件为 `PUBLIC`。
- 音频端点权限同 `/replay`：终局且公开历史开时任意访客全量；直播期间需 token（文件端点另认 `?token=`）。`/replay` 终局后返回全量 GM 视角事件。
- 前端：`useVoice` 按 `(seq, part)` 排队播放；GamePage 用 `voicingSeq` 反查事件的 `actor_seat` 决定聚光牌；回放时 `replayGate(seq)` 命中清单里的 seq 就等 `playSeq` 播完。

## 3. 旁白模板

### 3.1 默认白名单（`AGENTHOWL_NARRATION_EVENTS`）

```
ROUND_STARTED,PHASE_CHANGED,NIGHT_RESOLVED,DEATH_ANNOUNCED,
ELECTION_STAGE_CHANGED,SHERIFF_VOTE_STARTED,SHERIFF_ELECTED,BADGE_PASSED,
VOTE_STARTED,VOTE_RESULT,PLAYER_EXILED,HUNTER_SHOT,WOLF_SELF_DESTRUCT,GAME_OVER
```

不在默认名单（高频或重复）：`VOTE_CAST`、`SHERIFF_VOTE_CAST`、`SHERIFF_CANDIDACY`、`WOLF_KILL_PROPOSED/DECIDED/REVOTE`、`SEER_CHECKED`、`WITCH_*`、`GUARD_PROTECTED`、`ROLE_SKIPPED`、`SHERIFF_DIRECTION_SET`、`SHERIFF_WITHDREW`、`SHERIFF_BADGE_LOST`、`IDIOT_REVEALED`、`WITCH_POTION_CONSUMED`、`GAME_CREATED`、`GAME_STARTED`、`ROLES_ASSIGNED`、`PLAYER_SPOKE`、`LAST_WORDS`（后两者走发言配音）。

规则：
- 白名单里的每个类型必须在 §3.2 有模板；`NarrationConfig` 构造时校验，缺模板或未知类型名 → `ValueError`（fail-loud，启动即炸）。
- 不在白名单的事件 `narrate()` 返回 `[]`，不是错误。
- 名单里允许 `PLAYER_SPOKE` / `LAST_WORDS` 出现但被忽略（它们由发言配音负责，避免双播）。

### 3.2 模板（事件 → 句子列表）

座位统一读作「N号」；多个座位用「、」连接。句尾统一「。」。`seats(xs)` = `"、".join(f"{s}号")`。

| 事件 | 条件 | 句子 |
|---|---|---|
| `ROUND_STARTED` | | `第{round}轮，天黑请闭眼。` |
| `PHASE_CHANGED` | `to=NIGHT_GUARD` | `守卫请睁眼。` |
| | `to=NIGHT_WEREWOLF` | `狼人请睁眼。` |
| | `to=NIGHT_WITCH` | `女巫请睁眼。` |
| | `to=NIGHT_SEER` | `预言家请睁眼。` |
| | `to=NIGHT_HUNTER_CONFIRM` | `猎人请确认状态。` |
| | `to=SHERIFF_ELECTION` | `天亮了，进入警长竞选。` |
| | `to=SHERIFF_PK` | `警长竞选进入PK。` |
| | `to=DEATH_ANNOUNCE` | `天亮了。` |
| | `to=LAST_WORDS` | `请发表遗言。` |
| | `to=DAY_SPEECH`，`speech_order` 非空 | `进入发言环节，顺序：{seats(speech_order)}。` |
| | `to=DAY_SPEECH`，无顺序 | `进入发言环节。` |
| | `to=VOTE` | `进入放逐投票。` |
| | `to=VOTE_PK`，`speech_order` 非空 | `平票PK，发言顺序：{seats(speech_order)}。` |
| | `to=VOTE_PK`，无顺序 | `平票PK。` |
| | `to=HUNTER_SHOOT` | `猎人请开枪。` |
| | `to=IDIOT_FLIP` | `白痴翻牌。` |
| | 其余（`EXILE`、`WIN_CHECK`、`LOBBY`、`ROLE_ASSIGN`、`GAME_OVER`） | 不播（返回 `[]`；终局由 `GAME_OVER` 播） |
| `NIGHT_RESOLVED` | `deaths` 非空 | `本夜结算，出局：{seats(deaths)}。` |
| | 空 | `本夜结算，平安夜。` |
| `DEATH_ANNOUNCED` | `seats` 非空 | `昨夜出局的是{seats(seats)}。` |
| | 空 | `昨夜是平安夜，无人出局。` |
| `ELECTION_STAGE_CHANGED` | `stage=candidacy` | `上警报名开始。` |
| | `stage=speech`，`speech_order` 非空 | `上警发言，顺序：{seats(speech_order)}。` |
| | `stage=speech`，无顺序 | `上警发言。` |
| | `stage=withdraw` | `退水确认。` |
| | `stage=vote` | `警下投票开始。` |
| | `stage=direction` | `请警长决定发言方向。` |
| | `stage=announce` | `公布竞选结果。` |
| | `stage=""`（NONE） | `竞选环节结束。` |
| `SHERIFF_VOTE_STARTED` | | `警长开票，候选人：{seats(candidates)}。` |
| `SHERIFF_ELECTED` | | `{seat}号当选警长。` |
| `BADGE_PASSED` | `to_seat` 非空 | `{from_seat}号把警徽移交给{to_seat}号。` |
| | 空 | `{from_seat}号撕毁警徽。` |
| `VOTE_STARTED` | `tie_round=0` | `投票开始。` |
| | `tie_round>0` | `PK投票开始。` |
| `VOTE_RESULT` | `exiled` 非空 | `{exiled}号得票最高。` |
| | 平票 | `平票：{seats(tie_seats)}。` |
| `PLAYER_EXILED` | `seat` 非空 | `{seat}号被放逐出局。` |
| | 空 | `本轮无人出局。` |
| `HUNTER_SHOT` | `victim` 非空 | `{shooter}号猎人开枪，带走{victim}号。` |
| | 空 | `{shooter}号猎人没有开枪。` |
| `WOLF_SELF_DESTRUCT` | | `{seat}号狼人自爆。` |
| `GAME_OVER` | `winner=GOOD` | `游戏结束，好人阵营获胜。` |
| | `winner=WOLF` | `游戏结束，狼人阵营获胜。` |
| | 其他 | `游戏结束，平局。` |

说明：
- 模板是**口播**文案，不复用 `app/cli/render.py`（后者带 `【】[GM]` 等终端装饰）。两者各自独立，不互相 import。
- 每条模板一个句子，`narrate()` 返回 `list[str]` 以兼容将来多句模板；`SpeechAudioSink` 对每个句子各出一个 part（不再走 `split_sentences`，模板本身已是句子）。
- `ElectionStage` 子阶段名与模板一一对应；新增枚举值而未加模板 → 单测「模板覆盖」失败（§7）。

## 4. 后端组件

### 4.1 `app/runtime/narration.py`（新）

无 litellm、无网络；只依赖 `app.engine.events/phases`、`app.agent.profile.VoiceSpec/PRESET_SPEAKERS`、hashlib、pathlib。

```python
DEFAULT_NARRATION_EVENTS: frozenset[EventType]   # §3.1 名单
NARRATOR_WARM_TEXT = "大家好。"                   # 复用 speech_audio.WARM_TEXT 的文案

@dataclass(frozen=True)
class NarrationConfig:
    speaker: str                 # ∈ PRESET_SPEAKERS
    events: frozenset[EventType]
    cache_dir: Path

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None, *, data_dir: Path) -> NarrationConfig:
        # AGENTHOWL_NARRATOR_VOICE（默认 uncle_fu）、AGENTHOWL_NARRATION_EVENTS（逗号分隔，默认 DEFAULT）、
        # AGENTHOWL_NARRATION_DIR（默认 data_dir / "narration"）
        # speaker 不在 PRESET_SPEAKERS / 事件名未知 / 白名单事件缺模板 → ValueError

    @property
    def voice(self) -> VoiceSpec:   # VoiceSpec(mode="preset", speaker=self.speaker)

def narrate(event: Event, events: frozenset[EventType]) -> list[str]:
    """白名单内 → 按 §3.2 渲染；否则 []。白名单内但模板对该 payload 分支返回空（如 PHASE_CHANGED→EXILE）也 []。"""

class NarrationCache:
    def __init__(self, cache_dir: Path) -> None
    @staticmethod
    def key(speaker: str, text: str) -> str          # sha256(f"{speaker}\n{text}").hexdigest()[:16]
    def get(self, speaker: str, text: str) -> bytes | None   # 文件不存在 / 不是合法 WAV（wav_duration 抛） → None
    def put(self, speaker: str, text: str, wav: bytes) -> Path  # 写 <key>.wav.tmp 再 os.replace
```

`cache_dir` 不存在时 `put` 自动创建（`mkdir(parents=True)`）。缓存键不含 game_id，所有对局共用。

### 4.2 `SpeechAudioSink` 改造（`app/runtime/speech_audio.py`）

把「落盘 + 推帧 + 等待」抽成内核，发言与旁白共用：

```python
@dataclass(frozen=True)
class AudioPart:
    index: int
    wav: bytes
    duration_sec: float

class SpeechAudioSink:
    def __init__(self, audio_dir, tts, anchors=None, *, narration: NarrationConfig | None = None,
                 narration_cache: NarrationCache | None = None) -> None

    async def speak(self, game_id, seq, text, voice, connections, event: Event) -> None
        # 现有逻辑；parts 流来自 tts.synthesize_sentences；kind="speech"

    async def narrate(self, game_id, event: Event, connections) -> None
        # sentences = narrate(event, self._narration.events)；空 → 直接返回，不推帧不等待
        # 逐句：cache.get → 命中直接作为 part；未命中 → tts.synthesize_sentences(sentence, narrator_voice)
        #   取全部 part 合并为一段 wav（一句模板通常只产一段；多段时按 tts.concat 顺序拼接 data 块）→ cache.put
        # kind="narration"；单句失败（TtsError）跳过该句继续，全部失败只告警

    async def _emit(self, game_id, seq, parts: AsyncIterator[AudioPart], connections, event, kind) -> None
        # 现 speak() 的循环主体：写 <seq>-<k>.wav、broadcast_frame(frame, event)、expected_finish、end 帧、sleep
```

帧格式（新增 `kind`，其余不变）：

```json
{"type":"speech_audio","seq":37,"part":0,"url":"/api/v1/games/g_x/audio/37/0","duration":2.1,"kind":"narration"}
{"type":"speech_audio_end","seq":37,"parts":1,"kind":"narration"}
```

`warm(voices)`：若配置了旁白，把 `narration.voice` 追加进去（preset 去重逻辑已有），只合成一句短话装模型。

旁白多段合并：`tts.synthesize_sentences` 对单句一般只产一段；若模板句被 `split_sentences` 切成多段（模板里没有中间标点，正常不会），按顺序把各段 PCM data 拼成一个 WAV（同 fmt 头；`tts.py` 增 `concat_wav(parts: list[bytes]) -> bytes`，要求采样率/声道/位宽一致，否则 `TtsError`）。这样缓存里一句恒一个文件。

### 4.3 `ConnectionManager`（`app/runtime/connection.py`）

```python
FrameSubscriber = Callable[[dict[str, Any]], Awaitable[None]]

def subscribe_frames(self, viewer: Viewer, callback: FrameSubscriber) -> None
def unsubscribe_frames(self, viewer: Viewer, callback: FrameSubscriber) -> None
async def broadcast_frame(self, frame: dict[str, Any], event: Event) -> None:
    """对每个订阅者：visible_events(state, [event], viewer) 非空才投递。"""
```

`event` 必填：帧必须声明来源事件，没有「无来源的公开帧」这种例外。`ws.py` 订阅时传入连接的 viewer（与事件订阅同一个值）。

### 4.4 Runner（`app/runtime/game_runner.py`）

`_maybe_speak(seat, events)` → `_voice(events)`，在**每次** `_commit` 之后调用（`run()` 开局提交、`_drive_seat`、`_drive_window`、`_apply_default`）：

```python
async def _voice(self, events: list[Event]) -> None:
    if self._speech_audio is None:
        return
    for e in events:                      # 按 seq 顺序：先发言后阶段切换
        try:
            if e.type in (EventType.PLAYER_SPOKE, EventType.LAST_WORDS):
                seat = e.actor_seat if e.type == EventType.PLAYER_SPOKE else e.payload.seat
                profile = profile_for(self._agents, seat)
                if profile is not None and profile.voice is not None:
                    await self._speech_audio.speak(self._game_id, e.seq, e.payload.content, profile.voice, self.connections, e)
            elif self._narration_enabled:
                await self._speech_audio.narrate(self._game_id, e, self.connections)
        except Exception:
            logger.warning("seq=%d 配音异常，跳过等待", e.seq, exc_info=True)
```

构造参数增 `narration_enabled: bool = False`。`_commit` 本身不变（落库与广播先于任何音频）。

### 4.5 Registry / 建局（`app/runtime/registry.py`、`app/api/rest.py`、`app/main.py`）

- `GameHandle.narration_enabled: bool`；`create()` 增 `narration: bool = False`。
- `POST /games`：`CreateGameRequest.narration: bool = False`；`narration=True` 且 `voice=False` → 400「旁白需要先开启语音播报」；`voice=True` 时仍走现有 TTS 探测。
- `GET /games/{id}` 回显 `narration`。
- `main.py`：`NarrationConfig.from_env(data_dir=...)` 失败 → 启动即抛（fail-loud）；`SpeechAudioSink(..., narration=cfg, narration_cache=NarrationCache(cfg.cache_dir))`。
- `.env.example` 增三个变量说明。`docker-compose.yml` 不需改（`./backend/data` 已挂载）。

### 4.6 音频端点视角过滤（`app/api/rest.py`）

两个端点在 `_finished_or_handle` 通过后：
- 若「终局且公开历史开」或 `info.kind == "GM"` → 不过滤（与 `/replay` 全量一致）。
- 否则 viewer = `_viewer_for(info)`（`HOST` → `SPECTATOR`），`visible = {e.seq for e in visible_events(state, store.load_events(game_id), viewer)}`：
  - 清单：只保留 `seq ∈ visible`。
  - 文件：`seq ∉ visible` → 404「音频不存在」（不区分不存在/不可见）。

`state` 取 `handle.live_state()`；无 handle（重启后仅 store）时按终局公开路径处理（`_finished_or_handle` 已保证只有终局公开才到这里）。

注意：终局后非公开（`public_history` 关）且持 SPECTATOR token 的访客，`/replay` 也是全量（`require_kind` 通过即返回 `load_events` 全量）。音频端点此时同样全量，保持一致。

## 5. 前端

- `api/ws.ts`：`speech_audio` 帧多出的 `kind` 原样放进 `enqueue()`（`AudioQueueItem.kind?: "speech" | "narration"`），不做其他判断。
- `pages/GamePage.tsx`：`voicingSeat` 改为 `voicingActor: number | "GM" | null`——`voicingSeq` 对应事件为 `PLAYER_SPOKE`/`LAST_WORDS` → 该座位；其它任何事件（含带 `actor_seat` 的 `HUNTER_SHOT`/`BADGE_PASSED`/`WOLF_SELF_DESTRUCT`）→ `"GM"`；找不到事件 → null 回退 `turnSpeaker`。判断只看事件类型与 `actor_seat`，不看 `kind`。`speaking`（座位高亮）只在 actor 为数字时取它，`"GM"` 时为 `null`。
- `components/SpeakerSpotlight`：`seat: number | "GM" | null`。`"GM"` 渲染 🎙️ 占位（`Avatar` 的 fallback 样式，灰色环）+ 名字「GM」+ 标签「旁白中 🔊」；`aria-label`「GM 旁白中」。
- `pages/LobbyPage`（建局页）：「语音播报」下缩进一个「旁白」复选框；语音关时禁用并自动取消勾选；提交 `narration`。
- 回放：`replayGate` 不改——清单里旁白 seq 与发言 seq 同列，游标命中即等播完。
- 零过滤：前端收到什么播什么；判断 GM 只看事件类型与 `actor_seat`，不看 `kind`（`kind` 仅作调试/样式用途）。

## 6. 错误处理

- 旁白某句合成失败：WARNING，跳过该句，其余照播；全部失败：不推帧、不等待。
- 缓存文件损坏（`wav_duration` 抛）：视为未命中，重新合成并覆盖。
- 写缓存失败（OSError）：WARNING，本次仍用合成结果播放，不中断。
- `NarrationConfig` 校验失败：启动时 `ValueError`。
- 任何旁白异常都不能让对局陪葬：runner `_voice` 外层兜底与现 `_maybe_speak` 相同。

## 7. 测试

后端（`backend/tests/`）：
- `test_narration.py`
  - 模板覆盖：4 个 preset × 固定 seed 用引擎跑完整局（随机合法行动），对 GM 视角全部事件调用 `narrate(e, DEFAULT)`，白名单事件（除 §3.2 明示返回空的分支）必须非空且以「。」结尾；每个 `Phase` / `ElectionStage` 枚举值都有对应分支（参数化）。
  - `NarrationConfig.from_env`：默认值；非法 speaker / 未知事件名 → ValueError；自定义名单。
  - `NarrationCache`：put/get 往返；坏文件 → None；key 随 speaker 变化。
- `test_speech_audio.py` 追加：
  - `narrate()` 用假 TTS 计数：第一局（固定事件序列）调用次数 = 去重句数；用同一 cache 再跑一遍 → 0 次。
  - 单句失败跳过、全部失败不推帧。
  - 帧带 `kind`；`broadcast_frame` 收到来源事件。
- `test_connection.py` 追加：SPECTATOR 帧订阅收不到 `GM_ONLY` 事件的帧、GM 收到、`WOLVES` 事件只有狼座位收到。
- `test_game_runner.py` 追加：一次提交含 `[PLAYER_SPOKE, PHASE_CHANGED]` 时 sink 调用顺序为 speak → narrate；`narration_enabled=False` 不调 narrate。
- `test_api_voice.py` 追加：`narration=true, voice=false` → 400；直播期间 SPECTATOR token 的清单不含夜间 seq、文件端点 404，GM token 能取到；终局公开后匿名全量。
- 守卫：`test_importing_registry_does_not_load_litellm` 仍过。

前端（vitest）：
- `SpeakerSpotlight` 的 `"GM"` 渲染；GamePage `voicingActor` 三种分支（有座位 / GM / 找不到事件）。
- 建局页子开关联动与提交体。
- `npm run check` 全绿；无事件形状变化，fixtures 不需重生成。

## 8. 安全

- 旁白文本只含座位号与固定文案，不含玩家发言、档案、模型名；TTS 请求只带该文本。
- 帧投递、清单、文件三处都按 `visible_events` 过滤；GM 视角全量，其余只见公开（狼队/本角色事件不在默认名单，若用户加进名单，过滤同样生效）。
- `AGENTHOWL_TTS_API_KEY` 策略不变。
