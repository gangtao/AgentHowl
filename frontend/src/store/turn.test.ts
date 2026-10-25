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
