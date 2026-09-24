// buildAgentsPayload / memoryConflicts：覆盖设计稿 2a 的示例分配。

import { describe, expect, it } from "vitest";
import type { StoredAgent } from "../api/agents";
import {
  assignmentSummary,
  buildAgentsPayload,
  emptyAssignment,
  memoryConflicts,
  toProfilePayload,
  type SeatSlot,
} from "./seats";

function agent(
  id: string,
  name: string,
  extra: Partial<StoredAgent["profile"]> = {},
): StoredAgent {
  return {
    agent_id: id,
    profile: { name, model: "qwen2.5:14b", temperature: 0.3, skills: [], ...extra },
    created_at: "2026-09-20T00:00:00+00:00",
    updated_at: "2026-09-20T00:00:00+00:00",
  };
}

const LIBRARY: StoredAgent[] = [
  agent("a_owl", "夜枭", { memory_id: "night-owl" }),
  agent("a_iron", "铁齿", { memory_id: "iron-teeth" }),
  agent("a_fox", "狐语", { memory_id: "fox" }),
  agent("a_nice", "老好人"),
  agent("a_mute", "沉默者", { memory_id: "mute" }),
];

// 设计稿 2a：0 夜枭 / 1 铁齿 / 3 狐语 / 4、5 老好人 / 8 沉默者 / 其余由「老好人」填满（*）
const MOCKUP_ASSIGNMENT: SeatSlot[] = emptyAssignment(12).map((slot) => {
  const byId: Record<number, string> = {
    0: "a_owl",
    1: "a_iron",
    3: "a_fox",
    4: "a_nice",
    5: "a_nice",
    8: "a_mute",
  };
  return { seat: slot.seat, agentId: byId[slot.seat] ?? null };
});

describe("buildAgentsPayload", () => {
  it("座位专属 → \"{seat}\"、填满 → \"*\"、随机 bot 不写入", () => {
    const payload = buildAgentsPayload(MOCKUP_ASSIGNMENT, "a_nice", LIBRARY);
    expect(Object.keys(payload).sort()).toEqual(["*", "0", "1", "3", "4", "5", "8"]);
    expect(payload["0"]?.name).toBe("夜枭");
    expect(payload["*"]?.name).toBe("老好人");
    // 2、6、7、9、10、11 号没有显式档案，不出现在映射里
    expect(payload["2"]).toBeUndefined();
  });

  it("无 fill 时不写 \"*\"", () => {
    const payload = buildAgentsPayload(MOCKUP_ASSIGNMENT, null, LIBRARY);
    expect(payload["*"]).toBeUndefined();
    expect(Object.keys(payload)).toHaveLength(6);
  });

  it("全随机 bot → 空映射", () => {
    expect(buildAgentsPayload(emptyAssignment(9), null, LIBRARY)).toEqual({});
  });

  it("只发 AgentProfile 字段，不带库字段", () => {
    const payload = buildAgentsPayload([{ seat: 0, agentId: "a_owl" }], null, LIBRARY);
    const profile = payload["0"] as unknown as Record<string, unknown>;
    expect(Object.keys(profile).sort()).toEqual([
      "memory_id",
      "model",
      "name",
      "skills",
      "temperature",
    ]);
    expect(profile.agent_id).toBeUndefined();
    expect(profile.updated_at).toBeUndefined();
  });

  it("库里查不到的 id 视为未分配", () => {
    expect(buildAgentsPayload([{ seat: 2, agentId: "a_gone" }], "a_gone", LIBRARY)).toEqual({});
  });
});

describe("toProfilePayload", () => {
  it("保留 null（显式清空），丢掉 undefined", () => {
    const out = toProfilePayload({ model: "m", model_speech: null, provider: undefined });
    expect(out).toEqual({ model: "m", model_speech: null });
  });
});

describe("memoryConflicts", () => {
  it("同 memory_id 的档案记到首个占用座位", () => {
    const conflicts = memoryConflicts(MOCKUP_ASSIGNMENT, LIBRARY);
    expect(conflicts.get("a_fox")).toBe(3);
    expect(conflicts.get("a_owl")).toBe(0);
    expect(conflicts.get("a_mute")).toBe(8);
    // 老好人没有 memory_id：可以放多个座位，不进冲突表
    expect(conflicts.has("a_nice")).toBe(false);
  });

  it("未分配时无冲突", () => {
    expect(memoryConflicts(emptyAssignment(9), LIBRARY).size).toBe(0);
  });

  it("同 memory_id 的另一个档案也被禁用", () => {
    const library = [...LIBRARY, agent("a_fox2", "狐语副本", { memory_id: "fox" })];
    const conflicts = memoryConflicts([{ seat: 3, agentId: "a_fox" }], library);
    expect(conflicts.get("a_fox2")).toBe(3);
  });
});

describe("assignmentSummary", () => {
  it("统计 Agent 座位与其余座位", () => {
    expect(assignmentSummary(MOCKUP_ASSIGNMENT, "a_nice")).toEqual({
      agentSeats: 6,
      restSeats: 6,
      filled: true,
    });
    expect(assignmentSummary(MOCKUP_ASSIGNMENT, null).filled).toBe(false);
  });
});
