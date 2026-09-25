// suggestMemoryId：结果必须满足后端 MEMORY_ID_PATTERN，且不同名字不撞 id。

import { describe, expect, it } from "vitest";
import { isValidMemoryId, suggestMemoryId } from "./memoryId";

describe("suggestMemoryId", () => {
  it("拉丁 / 数字保留（转小写、空格转短横）", () => {
    expect(suggestMemoryId("Night Owl")).toBe("night-owl");
    expect(suggestMemoryId("agent_7")).toBe("agent_7");
  });

  it("中文 → agent- + 6 位十六进制", () => {
    const id = suggestMemoryId("夜枭");
    expect(id).toMatch(/^agent-[0-9a-f]{6}$/);
    expect(suggestMemoryId("铁齿")).not.toBe(id);
  });

  it("混合名保留拉丁部分并追加哈希", () => {
    expect(suggestMemoryId("夜枭 Owl")).toMatch(/^owl-[0-9a-f]{6}$/);
  });

  it("结果始终合法且 ≤ 64 字符", () => {
    for (const name of ["", "   ", "夜枭", "A".repeat(200), "!!!", "沐阳-Agent 02"]) {
      const id = suggestMemoryId(name);
      expect(isValidMemoryId(id)).toBe(true);
      expect(id.length).toBeLessThanOrEqual(64);
    }
  });

  it("同一名字稳定", () => {
    expect(suggestMemoryId("婉清")).toBe(suggestMemoryId("婉清"));
  });
});

describe("isValidMemoryId", () => {
  it("拒绝空串与非法字符", () => {
    expect(isValidMemoryId("")).toBe(false);
    expect(isValidMemoryId("夜枭")).toBe(false);
    expect(isValidMemoryId("night.owl")).toBe(false);
    expect(isValidMemoryId("night-owl_2")).toBe(true);
  });
});
