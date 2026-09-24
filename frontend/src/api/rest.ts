// REST 客户端：薄封装，零裁决（与后端 app/api/rest.py 对应，规格 §6）。
// 本文件不 import React 组件；错误统一转成 ApiError{status, detail}。

import type { Event, GameMeta } from "../engine/types";

const API_BASE = "/api/v1";

/** REST 错误：非 2xx 响应统一转成本类型；detail 取响应体 `detail`
 * （FastAPI 校验失败时 detail 是数组，这里拍平成字符串，参见规格 §6）。 */
export class ApiError extends Error {
  status: number;
  detail: string;

  constructor(status: number, detail: string) {
    super(detail);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

interface ReqOptions {
  token?: string;
  body?: unknown;
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
  const res = await fetch(`${API_BASE}${path}`, { method, headers, body });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const data: unknown = await res.json();
      if (data && typeof data === "object" && "detail" in data) {
        detail = stringifyDetail((data as { detail: unknown }).detail);
      }
    } catch {
      // 响应体不是 JSON：退回 statusText
    }
    throw new ApiError(res.status, detail);
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
}

export interface CreateGameResponse {
  game_id: string;
  host_token: string;
  spectator_token: string | null;
  gm_token: string;
  config: Record<string, unknown>;
  agents: Record<string, unknown>;
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

export function getMeta(gameId: string, token: string): Promise<GameMeta> {
  return req<GameMeta>("GET", `/games/${gameId}/meta`, { token });
}

/**
 * 直播期的状态快照（GET /games/{id}/state）。
 *
 * 为什么需要它：后端的 `/meta` 与 `/replay` 同一门槛——终局后才开放（rest.py::meta_endpoint），
 * 所以对局进行中拿不到 GameMeta。GamePage 用本端点补出 `initialState()` 所需的
 * `{game_id, config, roster}`：GM token 返回完整 GameState（含 config/players），
 * 观众 token 返回 SpectatorView（只有 seats）。返回体按视角不同，调用方自行判别。
 */
export function getState(gameId: string, token: string): Promise<Record<string, unknown>> {
  return req<Record<string, unknown>>("GET", `/games/${gameId}/state`, { token });
}

export function getReplay(gameId: string, token: string): Promise<Event[]> {
  return req<Event[]>("GET", `/games/${gameId}/replay`, { token });
}

export function getEvents(gameId: string, token: string, fromSeq = 0): Promise<Event[]> {
  return req<Event[]>("GET", `/games/${gameId}/events?from_seq=${fromSeq}`, { token });
}
