import { afterEach, describe, expect, it, vi } from "vitest";
import { TABLE_STYLE_KEY, readTableStyle, usePrefs } from "./prefs";

afterEach(() => {
  vi.restoreAllMocks();
  localStorage.clear();
  usePrefs.setState({ tableStyle: "round" });
});

describe("prefs.tableStyle（规格 §7）", () => {
  it("缺省 round；写入后持久化到 localStorage", () => {
    expect(readTableStyle()).toBe("round");
    usePrefs.getState().setTableStyle("cards");
    expect(usePrefs.getState().tableStyle).toBe("cards");
    expect(localStorage.getItem(TABLE_STYLE_KEY)).toBe("cards");
    expect(readTableStyle()).toBe("cards");
  });

  it("坏值回退 round", () => {
    localStorage.setItem(TABLE_STYLE_KEY, "triangle");
    expect(readTableStyle()).toBe("round");
  });

  it("localStorage 抛异常：读回退 round，写不崩且内存态仍更新", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("denied");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("denied");
    });
    expect(readTableStyle()).toBe("round");
    expect(() => usePrefs.getState().setTableStyle("cards")).not.toThrow();
    expect(usePrefs.getState().tableStyle).toBe("cards");
  });
});
