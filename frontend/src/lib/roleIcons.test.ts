import { describe, expect, it } from "vitest";
import type { RoleType } from "../engine/types";
import { CAMP_VARS, ROLE_ICON_PATH, roleCamp } from "./roleIcons";

const ROLES: RoleType[] = ["WEREWOLF", "VILLAGER", "SEER", "WITCH", "HUNTER", "GUARD", "IDIOT"];

describe("roleIcons（设计稿 2a）", () => {
  it.each(ROLES)("%s 有以 M 开头的路径", (r) => expect(ROLE_ICON_PATH[r]).toMatch(/^M[\d.]/));
  it("七条路径互不相同", () => expect(new Set(Object.values(ROLE_ICON_PATH)).size).toBe(7));
  it("阵营映射", () => {
    expect(roleCamp("WEREWOLF")).toBe("wolf");
    expect(roleCamp("VILLAGER")).toBe("villager");
    for (const r of ["SEER", "WITCH", "HUNTER", "GUARD", "IDIOT"] as const) {
      expect(roleCamp(r)).toBe("god");
    }
  });
  it("阵营色是 CSS 变量引用", () => {
    expect(CAMP_VARS.wolf.ring).toBe("var(--ah-wolf)");
    expect(CAMP_VARS.god.fg).toBe("var(--ah-god-fg)");
    expect(CAMP_VARS.villager.lo).toBe("var(--ah-villager-lo)");
  });
});
