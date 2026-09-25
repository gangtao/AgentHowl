// WS hook：直播事件订阅（规格 §6，对应 backend/app/api/ws.py）。
// URL：/api/v1/ws?token=…&from_seq=…；帧：{type:"game_event", seq, event}
// / {type:"phase_change", to, round} / {type:"game_over", winner} / {type:"error", detail}
// / {type:"action_result", ...} / {type:"your_turn", ...}（后两者本 hook 不消费，观战/上帝视角只读）。
// 关闭码：4401 token 无效、4403 无权、4404 对局不存在、4409 对局尚未开始——均为终局，不重连；
// 其余意外关闭（如 1006）且未收到 game_over → 指数退避重连，从 lastSeq+1 补发。

import { useEffect, useRef } from "react";
import { useGameStore } from "../store/game";
import type { Event } from "../engine/types";

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
}

export interface UseLiveEventsArgs {
  gameId: string | null;
  token: string | null;
  enabled: boolean;
}

function wsUrl(fromSeq: number, token: string): string {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const host = location.host || "localhost";
  return `${proto}://${host}/api/v1/ws?token=${encodeURIComponent(token)}&from_seq=${fromSeq}`;
}

/** 直播事件订阅：把 WS 帧转成对 useGameStore 的 appendEvents 调用。
 * StrictMode 双挂载安全：socket 存在 ref 里，effect 清理时关闭旧连接。 */
export function useLiveEvents({ gameId, token, enabled }: UseLiveEventsArgs): void {
  const socketRef = useRef<WebSocket | null>(null);
  const bufferRef = useRef<Event[]>([]);
  const rafRef = useRef<number | null>(null);
  const lastSeqRef = useRef<number>(0);
  const attemptRef = useRef<number>(0);
  const gameOverRef = useRef<boolean>(false);
  const closingForCleanupRef = useRef<boolean>(false);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (!enabled || !gameId || !token) return;

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
      const url = wsUrl(lastSeqRef.current + 1, token);
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
        }
        // phase_change：仅用于轻提示，状态一律来自 reduce，这里不处理。
      };

      ws.onclose = (ev: CloseEvent) => {
        if (closingForCleanupRef.current) return; // effect 清理主动关闭，不视为断线
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
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [gameId, token, enabled]);
}
