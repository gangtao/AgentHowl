// REST 客户端：薄封装，零裁决（与后端 app/api/rest.py 对应，规格 §6）。
// 本文件不 import React 组件；错误统一转成 ApiError{status, detail}。

import type { Event, GameMeta } from "../engine/types";

export const API_BASE = "/api/v1";

/** REST 错误：非 2xx 响应统一转成本类型；detail 取响应体 `detail`
 * （FastAPI 校验失败时 detail 是数组，这里拍平成字符串，参见规格 §6）。 */
export class ApiError extends Error {
  status: number;
  detail: string;
  /** 机器可读原因（如登录 401 的 `unverified`）；后端没给就是 undefined。 */
  reason?: string;

  constructor(status: number, detail: string, reason?: string) {
    super(detail);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
    if (reason !== undefined) this.reason = reason;
  }
}

let onUnauthorized: (() => void) | null = null;
/** 401 回调（issue #114）：App 注册为「重新确认登录态」；避免 api 层 import store 造成环。 */
export function setUnauthorizedHandler(fn: (() => void) | null): void {
  onUnauthorized = fn;
}

interface ReqOptions {
  token?: string;
  body?: unknown;
  query?: Record<string, string>;
}

function stringifyDetail(detail: unknown): string {
  if (typeof detail === "string") return detail;
  if (detail === undefined || detail === null) return "";
  return JSON.stringify(detail);
}

/** 统一请求函数：`req<T>(method, path, {token, body})`。path 不含 `/api/v1` 前缀。 */
export async function req<T>(method: string, path: string, opts: ReqOptions = {}): Promise<T> {
  const headers: Record<string, string> = {};
  let body: string | undefined;
  if (opts.body !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(opts.body);
  }
  if (opts.token) {
    headers.Authorization = `Bearer ${opts.token}`;
  }
  let url = `${API_BASE}${path}`;
  if (opts.query) {
    const qs = new URLSearchParams(opts.query).toString();
    if (qs) url += `${url.includes("?") ? "&" : "?"}${qs}`;
  }
  const res = await fetch(url, { method, headers, body, credentials: "same-origin" });
  if (!res.ok) {
    let detail = res.statusText;
    let reason: string | undefined;
    try {
      const data: unknown = await res.json();
      if (data && typeof data === "object" && "detail" in data) {
        detail = stringifyDetail((data as { detail: unknown }).detail);
      }
      if (data && typeof data === "object" && "reason" in data) {
        const r = (data as { reason: unknown }).reason;
        if (typeof r === "string") reason = r;
      }
    } catch {
      // 响应体不是 JSON：退回 statusText
    }
    // 带对局 token 的 401 是 token 问题；/auth/* 的 401 是认证流程本身（避免回调递归）。
    if (res.status === 401 && !opts.token && !path.startsWith("/auth/") && onUnauthorized) onUnauthorized();
    throw new ApiError(res.status, detail, reason);
  }
  if (res.status === 204) {
    return undefined as T;
  }
  return (await res.json()) as T;
}

// ---- 建局 / 对局元数据（app/api/rest.py 的 /games 系） ----

export interface CreateGameRequest {
  preset?: string;
  config_override?: Record<string, unknown>;
  num_ai_players?: number | null;
  allow_spectators?: boolean;
  ai_model?: string | null;
  ai_model_speech?: string | null;
  agents?: Record<string, unknown>;
  /** 语音播报开关（issue #103）；TTS 探测失败时后端 400。 */
  voice?: boolean;
  /** GM 旁白（issue #110）；需 voice=true，否则后端 400。 */
  narration?: boolean;
}

export interface CreateGameResponse {
  game_id: string;
  host_token: string;
  /** 分享 token（issue #114，原 spectator_token）；关闭观众时为 null。 */
  share_token: string | null;
  gm_token: string;
  config: Record<string, unknown>;
  agents: Record<string, unknown>;
  voice: boolean;
  narration: boolean;
}

export interface StartResponse {
  ok: boolean;
  num_players: number;
}

export function createGame(body: CreateGameRequest = {}): Promise<CreateGameResponse> {
  return req<CreateGameResponse>("POST", "/games", { body });
}

export function startGame(
  gameId: string,
  hostToken: string,
  fillWithBots = true,
): Promise<StartResponse> {
  return req<StartResponse>("POST", `/games/${gameId}/start`, {
    token: hostToken,
    body: { fill_with_bots: fillWithBots },
  });
}

export interface JoinRequest {
  display_name: string;
  /** 指定座位（issue #115）；不传顺序分配。 */
  seat?: number;
  player_type?: "HUMAN" | "AGENT";
}

export interface JoinResponse {
  player_token: string;
  seat: number;
  ws_url: string;
}

/** 入座（issue #115）：登录会话（cookie）即可，座位绑定当前账号。 */
export function joinGame(gameId: string, body: JoinRequest): Promise<JoinResponse> {
  return req<JoinResponse>("POST", `/games/${gameId}/join`, { body });
}

/** 服务端解析出的视角（issue #115）：`/state` 与 `/meta` 响应顶层的 `viewer`。 */
export type ViewerValue = "GM" | "SPECTATOR" | number;

export function viewerFrom(raw: Record<string, unknown>): ViewerValue | null {
  const v = raw.viewer;
  if (v === "GM" || v === "SPECTATOR" || typeof v === "number") return v;
  return null;
}

export type MetaResponse = GameMeta & { viewer?: ViewerValue };

/** 对局读端点的凭据（issue #114）：对局 token（Bearer）或分享 token（?share=）；都没有 → 只靠 cookie 会话。 */
export interface GameAuth {
  token?: string;
  share?: string;
}

function gameOpts(auth: GameAuth | undefined, extra: ReqOptions = {}): ReqOptions {
  const o: ReqOptions = { ...extra };
  if (auth?.token) o.token = auth.token;
  else if (auth?.share) o.query = { ...(o.query ?? {}), share: auth.share };
  return o;
}

/** 终局后开放；终局前 403（页面退回 /state）。 */
export function getMeta(gameId: string, auth?: GameAuth): Promise<MetaResponse> {
  return req<MetaResponse>("GET", `/games/${gameId}/meta`, gameOpts(auth));
}

/**
 * 直播期的状态快照（GET /games/{id}/state）。
 *
 * 为什么需要它：后端的 `/meta` 与 `/replay` 同一门槛——终局后才开放（rest.py::meta_endpoint），
 * 所以对局进行中拿不到 GameMeta。GamePage 用本端点补出 `initialState()` 所需的
 * `{game_id, config, roster}`：GM 凭据返回完整 GameState（含 config/players），
 * 观众凭据返回 SpectatorView（只有 seats）。返回体按视角不同，调用方自行判别。
 */
export function getState(gameId: string, auth?: GameAuth): Promise<Record<string, unknown>> {
  return req<Record<string, unknown>>("GET", `/games/${gameId}/state`, gameOpts(auth));
}

export function getReplay(gameId: string, auth?: GameAuth): Promise<Event[]> {
  return req<Event[]>("GET", `/games/${gameId}/replay`, gameOpts(auth));
}

export function getEvents(gameId: string, auth: GameAuth | undefined, fromSeq = 0): Promise<Event[]> {
  return req<Event[]>(
    "GET",
    `/games/${gameId}/events`,
    gameOpts(auth, { query: { from_seq: String(fromSeq) } }),
  );
}

/** 座位 → 头像 id（issue #102）：直播中需本局凭据；终局公开策略同 /replay。 */
export function getGameAvatars(gameId: string, auth?: GameAuth): Promise<Record<string, string>> {
  return req<Record<string, string>>("GET", `/games/${gameId}/avatars`, gameOpts(auth));
}

// ---- 配音（issue #103，app/runtime/tts.py + /tts/status、/games/{id}/audio） ----

/** TTS 服务探测状态：响应绝不含 api key。 */
export interface TtsStatus {
  enabled: boolean;
  ok: boolean;
  url: string | null;
  detail: string | null;
  supports_style: boolean;
}

export function getTtsStatus(): Promise<TtsStatus> {
  return req<TtsStatus>("GET", "/tts/status");
}

export interface VoiceDesignResult {
  anchor_id: string;
  url: string;
}

/** 按描述生成一个锚点声线样本（每次都是重新设计，不满意再点一次）；TTS 不可用 → 503。 */
export function designVoice(style: string): Promise<VoiceDesignResult> {
  return req<VoiceDesignResult>("POST", "/voices/design", { body: { style } });
}

export function voiceAnchorUrl(anchorId: string): string {
  return `${API_BASE}/voices/${anchorId}`;
}

export interface AudioPartInfo {
  part: number;
  duration: number;
}

/** 发言音频清单 {seq: [{part, duration}]}；权限同 /replay（终局前需本局 token）。 */
export function getAudioManifest(
  gameId: string,
  auth?: GameAuth,
): Promise<Record<string, AudioPartInfo[]>> {
  return req<Record<string, AudioPartInfo[]>>("GET", `/games/${gameId}/audio`, gameOpts(auth));
}

/** 给不能带 Authorization 头的 URL（<audio>、WS 帧里的音频地址）拼凭据：
 * token → `?token=`，share → `?share=`，都没有原样返回（浏览器带 cookie）。 */
export function withAuth(url: string, auth?: GameAuth): string {
  const sep = url.includes("?") ? "&" : "?";
  if (auth?.token) return `${url}${sep}token=${encodeURIComponent(auth.token)}`;
  if (auth?.share) return `${url}${sep}share=${encodeURIComponent(auth.share)}`;
  return url;
}

/** 音频分段文件地址（不经 req：浏览器 <audio>/<source> 直接拉取，发不出 Authorization 头）。 */
export function audioUrl(gameId: string, seq: number, part: number, auth?: GameAuth): string {
  return withAuth(`${API_BASE}/games/${gameId}/audio/${seq}/${part}`, auth);
}
