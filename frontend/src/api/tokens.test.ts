import { describe, expect, it } from "vitest";
import { parseHash, type ParsedHash } from "./tokens";

describe("parseHash", () => {
  const cases: [string, ParsedHash][] = [
    ["#/", { route: "lobby" }],
    ["#", { route: "lobby" }],
    ["", { route: "lobby" }],
    ["#/agents", { route: "agents" }],
    ["#/providers", { route: "providers" }],
    ["#/g/abc?gm=T", { route: "game", gameId: "abc", token: "T", viewer: "GM" }],
    ["#/g/abc?share=S", { route: "game", gameId: "abc", share: "S", viewer: "SPECTATOR" }],
    // gm 与 share 同时出现：gm 优先（上帝视角权限更高，不能被 share 参数降级）。
    ["#/g/abc?gm=T&share=U", { route: "game", gameId: "abc", token: "T", viewer: "GM" }],
    // 无法识别的路径：归为 lobby（不识别的路由没有对应页面，退回起点）。
    ["#/unknown/path", { route: "lobby" }],
  ];

  it.each(cases)("parseHash(%s)", (hash, expected) => {
    expect(parseHash(hash)).toEqual(expected);
  });

  it("history 路由", () => {
    expect(parseHash("#/history")).toEqual({ route: "history" });
  });

  it("auth 与 admin 路由", () => {
    expect(parseHash("#/login")).toEqual({ route: "login" });
    expect(parseHash("#/register")).toEqual({ route: "register" });
    expect(parseHash("#/verify")).toEqual({ route: "verify" });
    expect(parseHash("#/admin")).toEqual({ route: "admin" });
  });

  it("share 链接与裸 game 路由（issue #114）", () => {
    expect(parseHash("#/g/g_1?share=S")).toEqual({
      route: "game",
      gameId: "g_1",
      share: "S",
      viewer: "SPECTATOR",
    });
    // 裸路由：靠登录态走 GM 视角
    expect(parseHash("#/g/g_1")).toEqual({ route: "game", gameId: "g_1", viewer: "GM" });
    // gm 优先于 share
    expect(parseHash("#/g/g_1?gm=T&share=S")).toEqual({
      route: "game",
      gameId: "g_1",
      token: "T",
      viewer: "GM",
    });
    // 旧参数不再识别
    expect(parseHash("#/g/g_1?spec=T")).toEqual({ route: "game", gameId: "g_1", viewer: "GM" });
    expect(parseHash("#/g/g_1?replay=1")).toEqual({ route: "game", gameId: "g_1", viewer: "GM" });
  });
});
