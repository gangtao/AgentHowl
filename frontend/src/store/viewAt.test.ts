// viewAt(seq)：直播开语音时展示游标落后于 head（issue #193），按 seq 从最近检查点重放，与 cursor 回放同源。

import { describe, expect, it } from "vitest";
import fixture from "../engine/__fixtures__/std_9_kill_all-3.json";
import type { Event, GameMeta, GameState } from "../engine/types";
import { useGameStore } from "./game";

const meta = fixture.meta as unknown as GameMeta;
const events = fixture.events as unknown as Event[];
const states = fixture.states as unknown as GameState[];

describe("useGameStore.viewAt", () => {
  it("等于金样里该 seq 的状态；同一 (seq, events.length) 返回同一对象；越界取 head", () => {
    useGameStore.getState().reset();
    useGameStore.getState().load(meta, { gameId: "g", token: "t", viewer: "GM", mode: "live" });
    useGameStore.getState().appendEvents(events);
    const i = Math.floor(events.length / 2);
    const seq = (events[i] as Event).seq;
    const v = useGameStore.getState().viewAt(seq);
    expect(v).toEqual(states[i]);
    expect(useGameStore.getState().viewAt(seq)).toBe(v);
    expect(useGameStore.getState().viewAt(999999)).toBe(useGameStore.getState().head);
    useGameStore.getState().reset();
  });
});
