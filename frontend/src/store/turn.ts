// 回合 store（issue #115）：承接 WS 的 your_turn / action_result / error 帧，供 ActionBar 渲染。
// 零裁决：prompt 原样来自服务端；清不清 prompt 只看 action_result.ok。不 import React 组件。

import { create } from "zustand";
import type { ActionResult, YourTurn } from "../api/player";

interface TurnState {
  /** 最新一条 your_turn；提交成功（ok=true）后清空。 */
  prompt: YourTurn | null;
  /** 已发送、等待 action_result。 */
  pending: boolean;
  lastResult: ActionResult | null;
  /** WS error 帧（NotYourTurn / ToolCallError / 超时）。 */
  lastError: string | null;

  setPrompt(prompt: YourTurn): void;
  markPending(): void;
  resolve(result: ActionResult): void;
  fail(detail: string): void;
  disconnected(): void;
  reset(): void;
}

export const useTurn = create<TurnState>((set) => ({
  prompt: null,
  pending: false,
  lastResult: null,
  lastError: null,

  setPrompt(prompt) {
    set({ prompt, pending: false, lastResult: null, lastError: null });
  },
  markPending() {
    set({ pending: true, lastError: null });
  },
  resolve(result) {
    set((s) => ({ pending: false, lastResult: result, prompt: result.ok ? null : s.prompt }));
  },
  fail(detail) {
    set({ pending: false, lastError: detail });
  },
  disconnected() {
    set({ pending: false });
  },
  reset() {
    set({ prompt: null, pending: false, lastResult: null, lastError: null });
  },
}));
