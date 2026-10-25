// WS hook：直播事件订阅（规格 §6，对应 backend/app/api/ws.py）。
// URL：/api/v1/ws?token=…&from_seq=… | ?game_id=…&share=…&from_seq=… | ?game_id=…&from_seq=…（cookie）；帧：{type:"game_event", seq, event}
// / {type:"phase_change", to, round} / {type:"game_over", winner} / {type:"error", detail}
// / {type:"your_turn", observation, available_tools, deadline_ts} / {type:"action_result", ok, event_id, state_version, rejected_reason}（issue #115：写入 useTurn，供 ActionBar）
// / {type:"speech_audio", seq, part, url, duration, kind}（配音分段，issue #103；`kind` 为 `speech|narration`（issue #110，缺省按 speech）：转给 useVoice.enqueue，
// 不进 appendEvents——零信息过滤原则下也不代表任何游戏状态变化；url 会拼上本连接的 ?token=，
// 因为直播期间 /audio/{seq}/{part} 匿名必 401，而 <audio> 元素发不出 Authorization 头，fix round 1）
// / {type:"speech_audio_end", seq, parts}（本 hook 不消费，仅服务端用来标记某句配音已出完）。
// 关闭码：4401 token 无效、4403 无权、4404 对局不存在、4409 对局尚未开始——均为终局，不重连；
// 其余意外关闭（如 1006）且未收到 game_over → 指数退避重连，从 lastSeq+1 补发。

import { useCallback, useEffect, useRef } from "react";
import { useGameStore } from "../store/game";
import { useVoice } from "../store/voice";
import { useTurn } from "../store/turn";
import { withAuth } from "./rest";
import type { GameAuth } from "./rest";
import type { Event } from "../engine/types";
import type { ActionResult, PlayerObservation, ToolCall } from "./player";

/** 关闭码 → 中文提示（规格 §6）。 */
export const CLOSE_TEXT: Record<number, string> = {
  4401: "token 无效",
  4403: "该 token 无权观战",
  4404: "对局不存在",
  4409: "对局尚未开始",
};

const TERMINAL_CODES = new Set(Object.keys(CLOSE_TEXT).map(Number));

/** 重连退避表（毫秒）：第 N 次意外断线用 BACKOFF_MS[min(N, len-1)]。 */
export const BACKOFF_MS = [1000, 2000, 4000, 8000];

/** 每个 rAF 批次最多刷入 store 的事件数（规格 §6：每帧最多 200 条）。 */
const MAX_BATCH = 200;

interface WsFrame {
  type: string;
  seq?: number;
  event?: Event;
  to?: string;
  round?: number;
  winner?: string | null;
  detail?: string;
  part?: number;
  url?: string;
  duration?: number;
  kind?: "speech" | "narration";
  observation?: PlayerObservation;
  available_tools?: string[];
  deadline_ts?: number;
  ok?: boolean;
  event_id?: string | null;
  state_version?: number | null;
  rejected_reason?: string | null;
}

export interface UseLiveEventsArgs {
  gameId: string | null;
  auth: GameAuth;
  enabled: boolean;
}

export interface LiveEventsHandle {
  /** 经当前 WS 连接提交工具调用（issue #115）；socket 未打开返回 false，不入队。 */
  send(call: ToolCall): boolean;
}

/** 三种形式（issue #114）：对局 token / 分享 token / cookie 会话。 */
export function wsUrl(fromSeq: number, gameId: string, auth: GameAuth): string {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const host = location.host || "localhost";
  const base = `${proto}://${host}/api/v1/ws`;
  if (auth.token) return `${base}?token=${encodeURIComponent(auth.token)}&from_seq=${fromSeq}`;
  const g = `game_id=${encodeURIComponent(gameId)}`;
  if (auth.share) return `${base}?${g}&share=${encodeURIComponent(auth.share)}&from_seq=${fromSeq}`;
  return `${base}?${g}&from_seq=${fromSeq}`;
}

/** 直播事件订阅：把 WS 帧转成对 useGameStore 的 appendEvents 调用。
 * StrictMode 双挂载安全：socket 存在 ref 里，effect 清理时关闭旧连接。 */
export function useLiveEvents({ gameId, auth, enabled }: UseLiveEventsArgs): LiveEventsHandle {
  const socketRef = useRef<WebSocket | null>(null);
  const bufferRef = useRef<Event[]>([]);
  const rafRef = useRef<number | null>(null);
  const lastSeqRef = useRef<number>(0);
  const attemptRef = useRef<number>(0);
  const gameOverRef = useRef<boolean>(false);
  const closingForCleanupRef = useRef<boolean>(false);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (!enabled || !gameId) return;

    gameOverRef.current = false;
    closingForCleanupRef.current = false;
    attemptRef.current = 0;
    // 从 store 已有事件的最大 seq 续接（重进对局页时避免从 0 全量拉取）。
    const existing = useGameStore.getState().events;
    lastSeqRef.current = existing.length > 0 ? (existing[existing.length - 1] as Event).seq : 0;

    const flush = (): void => {
      rafRef.current = null;
      if (bufferRef.current.length === 0) return;
      const batch = bufferRef.current.splice(0, MAX_BATCH);
      useGameStore.getState().appendEvents(batch);
      const gap = useGameStore.getState().gap;
      if (gap !== null) {
        // store 记录了缺口：清掉本地已知的 lastSeq，从缺口起点重新拉取补发。
        // 同时清空剩余缓冲——残留的都是断线前的陈旧事件，留着会在补发帧之前被下一次
        // flush 消费，重新触发同一个缺口，白白多打几轮重连（review Minor-1）。
        useGameStore.getState().clearGap();
        bufferRef.current = [];
        lastSeqRef.current = gap.expected - 1;
        reconnect();
        return;
      }
      if (bufferRef.current.length > 0) {
        scheduleFlush();
      }
    };

    const scheduleFlush = (): void => {
      if (rafRef.current !== null) return;
      rafRef.current = requestAnimationFrame(flush);
    };

    const cleanupSocket = (): void => {
      const ws = socketRef.current;
      socketRef.current = null;
      if (ws !== null) {
        ws.onopen = null;
        ws.onmessage = null;
        ws.onclose = null;
        ws.onerror = null;
        try {
          ws.close();
        } catch {
          // 已关闭/关闭中，忽略
        }
      }
    };

    const connect = (): void => {
      useGameStore.getState().setConnection("connecting");
      const url = wsUrl(lastSeqRef.current + 1, gameId, auth);
      const ws = new WebSocket(url);
      socketRef.current = ws;

      ws.onopen = () => {
        attemptRef.current = 0;
        useGameStore.getState().setConnection("open");
      };

      ws.onmessage = (ev: MessageEvent<string>) => {
        let frame: WsFrame;
        try {
          frame = JSON.parse(ev.data) as WsFrame;
        } catch {
          return;
        }
        if (frame.type === "game_event" && frame.event) {
          lastSeqRef.current = frame.event.seq;
          bufferRef.current.push(frame.event);
          scheduleFlush();
        } else if (frame.type === "game_over") {
          gameOverRef.current = true;
        } else if (frame.type === "error" && frame.detail) {
          useGameStore.getState().setError(frame.detail);
          useTurn.getState().fail(frame.detail);
        } else if (frame.type === "your_turn" && frame.observation) {
          useTurn.getState().setPrompt({
            observation: frame.observation,
            available_tools: frame.available_tools ?? [],
            deadline_ts: frame.deadline_ts ?? 0,
          });
        } else if (frame.type === "action_result") {
          const result: ActionResult = {
            ok: frame.ok === true,
            event_id: frame.event_id ?? null,
            state_version: frame.state_version ?? null,
            rejected_reason: frame.rejected_reason ?? null,
          };
          useTurn.getState().resolve(result);
        } else if (frame.type === "speech_audio" && frame.url !== undefined) {
          // 直播期间该文件端点匿名必 401（fix round 1）：<audio> 发不出 Authorization 头，
          // 这里把本连接的凭据（?token= / ?share=，cookie 模式不拼）拼到 URL 上。
          const url = withAuth(frame.url, auth);
          useVoice.getState().enqueue({
            seq: frame.seq as number,
            part: frame.part as number,
            url,
            duration: frame.duration ?? 0,
            kind: frame.kind ?? "speech",
          });
        }
        // phase_change：仅用于轻提示，状态一律来自 reduce，这里不处理。
        // speech_audio_end：仅服务端自用的分段计数标记，本 hook 忽略。
      };

      ws.onclose = (ev: CloseEvent) => {
        if (closingForCleanupRef.current) return; // effect 清理主动关闭，不视为断线
        useTurn.getState().disconnected();
        socketRef.current = null;
        if (TERMINAL_CODES.has(ev.code)) {
          useGameStore.getState().setConnection("error");
          useGameStore.getState().setError(CLOSE_TEXT[ev.code] ?? `连接已关闭（${ev.code}）`);
          return;
        }
        useGameStore.getState().setConnection("closed");
        if (gameOverRef.current) return; // 终局后正常关闭：不重连
        reconnect();
      };

      ws.onerror = () => {
        // 具体处理交给 onclose（浏览器 WS 在 error 后总会触发 close）
      };
    };

    function reconnect(): void {
      cleanupSocket();
      const delay = BACKOFF_MS[Math.min(attemptRef.current, BACKOFF_MS.length - 1)] as number;
      attemptRef.current += 1;
      reconnectTimerRef.current = setTimeout(() => {
        reconnectTimerRef.current = null;
        connect();
      }, delay);
    }

    connect();

    return () => {
      closingForCleanupRef.current = true;
      if (reconnectTimerRef.current !== null) {
        clearTimeout(reconnectTimerRef.current);
        reconnectTimerRef.current = null;
      }
      if (rafRef.current !== null) {
        cancelAnimationFrame(rafRef.current);
        rafRef.current = null;
      }
      bufferRef.current = [];
      cleanupSocket();
      useTurn.getState().reset();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [gameId, auth.token, auth.share, enabled]);

  const send = useCallback((call: ToolCall): boolean => {
    const ws = socketRef.current;
    // 1 === WebSocket.OPEN；不用静态属性，测试里的假 WebSocket 没有它
    if (ws === null || ws.readyState !== 1) return false;
    ws.send(JSON.stringify(call));
    useTurn.getState().markPending();
    return true;
  }, []);

  return { send };
}
