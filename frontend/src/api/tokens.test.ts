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
    ["#/g/abc?spec=T", { route: "game", gameId: "abc", token: "T", viewer: "SPECTATOR" }],
    // 无 token：仍是 game 路由，但不带 token/viewer——页面自行展示错误（规格 §6）。
    ["#/g/abc", { route: "game", gameId: "abc" }],
    // gm 与 spec 同时出现：gm 优先（上帝视角权限更高，不能被 spec 参数降级）。
    ["#/g/abc?gm=T&spec=U", { route: "game", gameId: "abc", token: "T", viewer: "GM" }],
    // 无法识别的路径：归为 lobby（不识别的路由没有对应页面，退回起点）。
    ["#/unknown/path", { route: "lobby" }],
  ];

  it.each(cases)("parseHash(%s)", (hash, expected) => {
    expect(parseHash(hash)).toEqual(expected);
  });

  it("history 路由与 replay=1 无 token 回放", () => {
    expect(parseHash("#/history")).toEqual({ route: "history" });
    expect(parseHash("#/g/g_abc?replay=1")).toEqual({
      route: "game",
      gameId: "g_abc",
      replay: true,
      viewer: "GM",
    });
    // gm 与 replay 同时出现：有 token 走原路径
    expect(parseHash("#/g/g_abc?gm=T&replay=1")).toEqual({
      route: "game",
      gameId: "g_abc",
      token: "T",
      viewer: "GM",
    });
  });
});
