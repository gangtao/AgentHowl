import { describe, expect, it } from "vitest";
import { agentLine } from "./agentLine";

describe("agentLine（规格 R7）", () => {
  it("无档案 / 空对象 / seat 为 null → null", () => {
    expect(agentLine(undefined, 3)).toBeNull();
    expect(agentLine({}, 3)).toBeNull();
    expect(agentLine({ "3": { model: "x" } }, null)).toBeNull();
    expect(agentLine({ "3": { voice: null } }, 3)).toBeNull();
  });

  it("model 去掉 provider 前缀", () => {
    expect(agentLine({ "3": { model: "openai/gpt-4o" } }, 3)?.model).toBe("gpt-4o");
    expect(agentLine({ "3": { model: "claude-sonnet" } }, 3)?.model).toBe("claude-sonnet");
  });

  it("声线：preset → speaker；design → 定制；无 → 不配音", () => {
    expect(agentLine({ "3": { model: "m", voice: { mode: "preset", speaker: "低沉" } } }, 3)?.voice).toBe(
      "低沉",
    );
    expect(agentLine({ "3": { model: "m", voice: { mode: "design", style: "x" } } }, 3)?.voice).toBe(
      "定制",
    );
    expect(agentLine({ "3": { model: "m", voice: null } }, 3)?.voice).toBe("不配音");
    expect(agentLine({ "3": { model: "m" } }, 3)?.voice).toBe("不配音");
  });
});
