// 回合 store（issue #115）：承接 WS 的 your_turn / action_result / error 帧，供 ActionBar 渲染。
// 零裁决：prompt 原样来自服务端；清不清 prompt 只看 action_result.ok，且只清它所回应的那条 prompt
// （服务端 out_q 里下一窗口的 your_turn 可能排在上一动作的 action_result 之前，e2e 实测）。不 import React 组件。

import { create } from "zustand";
import type { ActionResult, YourTurn } from "../api/player";

interface TurnState {
  /** 最新一条 your_turn；提交成功（ok=true）后清空。 */
  prompt: YourTurn | null;
  /** 已发送、等待 action_result。 */
  pending: boolean;
  /** 发送时所针对的 prompt 的 state_version；action_result 只清这一版 prompt。 */
  submittedVersion: number | null;
  /** 服务端已受理但尚未裁决（同步窗口要等全体行动者到齐）：隐藏表单，等 action_result。 */
  accepted: boolean;
  lastResult: ActionResult | null;
  /** WS error 帧（NotYourTurn / ToolCallError / 超时）。 */
  lastError: string | null;

  setPrompt(prompt: YourTurn): void;
  markPending(): void;
  accept(): void;
  resolve(result: ActionResult): void;
  /** error 帧；closesWindow（NOT_YOUR_TURN / STALE_PROMPT）表示该窗口对本连接已结束，连 prompt 一起清。 */
  fail(detail: string, closesWindow?: boolean): void;
  /** window_closed 帧（issue #125）：窗口被其它连接提交或超时关闭；本连接若未提交该窗口则清掉残留 prompt。 */
  windowClosed(stateVersion: number): void;
  disconnected(): void;
  reset(): void;
}

export const useTurn = create<TurnState>((set) => ({
  prompt: null,
  pending: false,
  submittedVersion: null,
  accepted: false,
  lastResult: null,
  lastError: null,

  setPrompt(prompt) {
    set({ prompt, pending: false, accepted: false, lastResult: null, lastError: null });
  },
  accept() {
    set({ pending: false, accepted: true });
  },
  markPending() {
    set((s) => ({
      pending: true,
      lastError: null,
      submittedVersion: s.prompt?.observation.state_version ?? null,
    }));
  },
  resolve(result) {
    set((s) => {
      // 只清被回应的那条 prompt：若其间已收到新窗口的 your_turn（state_version 不同），新 prompt 必须保留
      const answered = s.prompt !== null && s.prompt.observation.state_version === s.submittedVersion;
      return {
        pending: false,
        accepted: false,
        lastResult: result,
        submittedVersion: null,
        prompt: result.ok && answered ? null : s.prompt,
      };
    });
  },
  fail(detail, closesWindow = false) {
    set((s) => ({
      pending: false,
      accepted: false,
      lastError: detail,
      prompt: closesWindow ? null : s.prompt,
      submittedVersion: closesWindow ? null : s.submittedVersion,
    }));
  },
  windowClosed(stateVersion) {
    set((s) => {
      if (s.prompt === null || s.prompt.observation.state_version !== stateVersion) return {};
      // 本连接提交过这一窗口：结果由 action_accepted / action_result 收尾，这里不动
      if (s.submittedVersion === stateVersion) return {};
      return { prompt: null, pending: false, accepted: false, lastError: "本窗口已结束（其他连接已提交或已超时）" };
    });
  },
  disconnected() {
    set({ pending: false });
  },
  reset() {
    set({
      prompt: null,
      pending: false,
      submittedVersion: null,
      accepted: false,
      lastResult: null,
      lastError: null,
    });
  },
}));
