import { describe, expect, it } from "vitest";
import { EMPTY_RATING, type StoredAgent } from "../api/agents";
import {
  presetTag,
  scrollSubtitle,
  seatGlyph,
  seatTags,
  summaryMain,
  summarySub,
} from "./lobbyText";
import { ME, assignmentSummary } from "./seats";

const lib: StoredAgent[] = [
  {
    agent_id: "a_fox",
    profile: { name: "狐语", model: "m" },
    created_at: "",
    updated_at: "",
    rating: EMPTY_RATING,
  },
  {
    agent_id: "a_abacus",
    profile: { name: "算盘", model: "m", memory_id: "mem1" },
    created_at: "",
    updated_at: "",
    rating: EMPTY_RATING,
  },
];
const assignment = [
  { seat: 0, agentId: ME },
  { seat: 1, agentId: null },
  { seat: 2, agentId: "a_fox" },
  { seat: 3, agentId: "a_ghost" },
  { seat: 4, agentId: null },
];

describe("summaryMain / summarySub", () => {
  // assignmentSummary 不看库：a_ghost 也算「已分配」。这里用不含幽灵 id 的表。
  const known = assignment
    .filter((s) => s.agentId !== "a_ghost")
    .concat({ seat: 3, agentId: null });
  it("有我自己与 bot", () => {
    expect(summaryMain(5, assignmentSummary(known, null), null)).toBe(
      "5 座位 · 1 个 Agent · 我在 0号 · 3 个随机 bot",
    );
  });
  it("无我自己、有 fill", () => {
    const a = known.map((s) => (s.agentId === ME ? { ...s, agentId: null } : s));
    expect(summaryMain(5, assignmentSummary(a, "a_fox"), "狐语")).toBe(
      "5 座位 · 1 个 Agent · 其余 4 座由「狐语」填满",
    );
  });
  it("未选剧本", () => {
    expect(summaryMain(null, assignmentSummary([], null), null)).toBe(
      "未选剧本 · 0 个 Agent · 0 个随机 bot",
    );
  });
  it("summarySub", () => {
    expect(summarySub("12 人预女猎白", " 42 ")).toBe("12 人预女猎白 · seed 42");
    expect(summarySub(null, "")).toBe("seed 随机");
  });
});

describe("scrollSubtitle", () => {
  it.each([
    [3, "你将以 3号 入座 · 创建后直接进入玩家页 · 对局结束前看不到上帝视角"],
    [null, "全 AI 对局 · 创建后进入上帝视角"],
  ])("%s", (me, text) => expect(scrollSubtitle(me)).toBe(text));
});

describe("seatGlyph", () => {
  it.each([
    [ME, null, { text: "我", kind: "me" }],
    ["a_fox", null, { text: "狐", kind: "agent" }],
    ["a_ghost", null, { text: "bot", kind: "bot" }],
    [null, null, { text: "bot", kind: "bot" }],
    [null, "狐语", { text: "狐", kind: "fill" }],
  ])("%s / fill %s", (id, fillName, want) => expect(seatGlyph(id, lib, fillName)).toEqual(want));
});

describe("seatTags", () => {
  it("签按座号升序，库里查不到的 id 不算", () => {
    expect(seatTags(assignment, lib, null)).toEqual({
      tags: [
        { seat: 0, kind: "me", text: "我自己" },
        { seat: 2, kind: "agent", text: "狐语" },
      ],
      rest: 3,
      fillName: null,
    });
  });
  it("fill 时 fillName 带出", () => {
    expect(seatTags(assignment, lib, "a_fox").fillName).toBe("狐语");
  });
});

describe("presetTag", () => {
  it.each([
    [12, true, "12 人 / 带警长"],
    [9, false, "9 人"],
  ])("%s %s", (n, s, t) => expect(presetTag(n, s)).toBe(t));
});
