# AgentHowl 本地 TTS 服务（issue #103）

发言配音的本地文字转语音服务：[mlx-audio](https://github.com/Blaizzy/mlx-audio) 跑 Qwen3-TTS，
暴露 OpenAI 兼容的 `POST /v1/audio/speech`，供后端 `app/runtime/tts.py` 调用。

**仅支持 macOS（Apple Silicon，arm64）**——mlx-audio 基于 Apple 的 MLX 框架，依赖 Metal。
Linux / NVIDIA 用户见文末替代方案。

## 启动

仓库根：

```bash
make tts          # = cd tts && uv run python -m mlx_audio.server --host 127.0.0.1 --port 8880
```

默认端口 `8880`（mlx-audio 的 CLI 默认端口 `8000` 与后端 `make serve` 冲突，故在这里改用 `8880`；
可用 `TTS_PORT=` 覆盖，如 `make tts TTS_PORT=9000`）。首次启动很快——模型按请求的 `model` 字段
**懒加载**，真正下载发生在第一次合成请求时。

## 后端侧配置

在仓库根 `.env`（见 `.env.example` 末尾的「发言配音」块）里打开：

```bash
AGENTHOWL_TTS_URL=http://host.docker.internal:8880   # 后端跑在 Docker 里；本机直跑用 http://127.0.0.1:8880
AGENTHOWL_TTS_KIND=mlx_audio
#AGENTHOWL_TTS_MODEL_PRESET=mlx-community/Qwen3-TTS-12Hz-1.7B-CustomVoice-6bit
#AGENTHOWL_TTS_MODEL_DESIGN=mlx-community/Qwen3-TTS-12Hz-1.7B-VoiceDesign-6bit
```

建局时勾选「语音播报」（或 `POST /games` 传 `voice: true`）前，后端会先探测 `GET /tts/status`；
mlx-audio 没启动或还在下载模型会直接 400，不会悄悄降级成不出声。

## 首次请求会下载模型

两份 6-bit 量化模型各约 2 GB，按首次用到哪种声线模式懒加载：

- `CustomVoice`（预置声线，5 个 speaker）：`mlx-community/Qwen3-TTS-12Hz-1.7B-CustomVoice-6bit`
- `VoiceDesign`（自由文本描述声线）：`mlx-community/Qwen3-TTS-12Hz-1.7B-VoiceDesign-6bit`

下载到 Hugging Face 缓存（`~/.cache/huggingface/`），之后复用。实测（Apple M2 Pro）：RTF（合成
耗时/音频时长）约 0.5–0.7，首句约 1–1.6 秒出声——边合成边播、不等整段发言合成完。

## 换模型

`AGENTHOWL_TTS_MODEL_PRESET` / `AGENTHOWL_TTS_MODEL_DESIGN` 可指向任意 mlx-audio 支持的
Qwen3-TTS 变体（如非 6-bit 量化版本，更准但更慢更占内存）。

## 非 Apple Silicon 的替代方案

Linux / NVIDIA 用户用不了 mlx-audio，可换任何暴露 OpenAI `/v1/audio/speech` 的服务（如
vLLM-Omni，或其它 OpenAI-speech 兼容网关），把 `AGENTHOWL_TTS_KIND` 设成 `generic`
（`generic` 只发 `model`/`input`/`voice`（预置 speaker，缺省 `"alloy"`）/`speed`/
`response_format`，不转发 `instruct`/`instructions` 之类的风格字段——声线描述（`style`）
会被直接丢弃；要让风格提示生效，用 `mlx_audio` 或 `openai` kind）：

```bash
AGENTHOWL_TTS_URL=http://your-host:port
AGENTHOWL_TTS_KIND=generic
```

## 依赖锁定

`tts/uv.lock` 已入库（`mlx-audio[server,tts]`，macOS arm64 下 `uv lock` 解析、`uv sync` 验证可装）。
