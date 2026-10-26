import { beforeEach, describe, expect, it } from "vitest";
import type { YourTurn } from "../api/player";
import { useTurn } from "./turn";

const prompt = (v: number): YourTurn =>
  ({
    observation: { my_seat: 1, state_version: v, phase: "DAY_SPEECH" },
    available_tools: ["speak"],
    deadline_ts: 1000,
  }) as unknown as YourTurn;

beforeEach(() => useTurn.getState().reset());

describe("useTurn", () => {
  it("setPrompt 覆盖旧 prompt 并清掉上一次结果与错误", () => {
    useTurn.getState().fail("x");
    useTurn.getState().setPrompt(prompt(1));
    useTurn.getState().setPrompt(prompt(2));
    const s = useTurn.getState();
    expect(s.prompt?.observation.state_version).toBe(2);
    expect(s.lastError).toBeNull();
    expect(s.pending).toBe(false);
  });

  it("markPending → resolve(ok) 清 prompt；resolve(!ok) 保留 prompt 并记拒因", () => {
    useTurn.getState().setPrompt(prompt(1));
    useTurn.getState().markPending();
    expect(useTurn.getState().pending).toBe(true);
    useTurn.getState().resolve({ ok: false, event_id: null, state_version: null, rejected_reason: "夜里不能发言" });
    expect(useTurn.getState().pending).toBe(false);
    expect(useTurn.getState().prompt).not.toBeNull();
    expect(useTurn.getState().lastResult?.rejected_reason).toBe("夜里不能发言");
    useTurn.getState().markPending();
    useTurn.getState().resolve({ ok: true, event_id: "evt_1", state_version: 5, rejected_reason: null });
    expect(useTurn.getState().prompt).toBeNull();
    expect(useTurn.getState().lastResult?.ok).toBe(true);
  });

  it("action_result 晚于下一条 your_turn 到达：只清它所回应的那条 prompt，不清新 prompt（e2e 实测竞态）", () => {
    // 服务端 out_q 里 your_turn（新窗口）可能排在上一动作的 action_result 之前：
    // 投票 → 引擎立刻开遗言窗口（your_turn sv=199）→ 投票的 action_result(sv=187) 才入队。
    useTurn.getState().setPrompt(prompt(186));
    useTurn.getState().markPending();
    useTurn.getState().setPrompt(prompt(199));
    useTurn.getState().resolve({ ok: true, event_id: "evt_187", state_version: 187, rejected_reason: null });
    const s = useTurn.getState();
    expect(s.prompt?.observation.state_version).toBe(199); // 新窗口必须还在
    expect(s.pending).toBe(false);
    expect(s.lastResult?.ok).toBe(true);
  });

  it("正常顺序：action_result 回应当前 prompt → 清 prompt", () => {
    useTurn.getState().setPrompt(prompt(186));
    useTurn.getState().markPending();
    useTurn.getState().resolve({ ok: true, event_id: "evt_187", state_version: 187, rejected_reason: null });
    expect(useTurn.getState().prompt).toBeNull();
  });

  it("accept：已受理 → pending 清、accepted 置位、prompt 保留；action_result 到达后 accepted 清", () => {
    useTurn.getState().setPrompt(prompt(10));
    useTurn.getState().markPending();
    useTurn.getState().accept();
    expect(useTurn.getState().pending).toBe(false);
    expect(useTurn.getState().accepted).toBe(true);
    expect(useTurn.getState().prompt?.observation.state_version).toBe(10);
    useTurn.getState().resolve({ ok: true, event_id: "evt_11", state_version: 11, rejected_reason: null });
    expect(useTurn.getState().accepted).toBe(false);
    expect(useTurn.getState().prompt).toBeNull();
    // 新窗口的 your_turn 也清 accepted
    useTurn.getState().setPrompt(prompt(20));
    useTurn.getState().accept();
    useTurn.getState().setPrompt(prompt(21));
    expect(useTurn.getState().accepted).toBe(false);
  });

  it("fail / disconnected 只清 pending，不动 prompt", () => {
    useTurn.getState().setPrompt(prompt(1));
    useTurn.getState().markPending();
    useTurn.getState().fail("不是你的回合");
    expect(useTurn.getState().pending).toBe(false);
    expect(useTurn.getState().lastError).toBe("不是你的回合");
    expect(useTurn.getState().prompt).not.toBeNull();
    useTurn.getState().markPending();
    useTurn.getState().disconnected();
    expect(useTurn.getState().pending).toBe(false);
  });
});
