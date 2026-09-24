// Hash 路由解析：token 只放在 URL hash（规格 §6），不写 localStorage。
// 支持：#/、#/agents、#/providers、#/g/{gameId}?gm=…、#/g/{gameId}?spec=…

export type Route = "lobby" | "agents" | "providers" | "game";
export type Viewer = "GM" | "SPECTATOR";

export interface ParsedHash {
  route: Route;
  gameId?: string;
  token?: string;
  viewer?: Viewer;
}

/** 解析当前 `location.hash`（或传入的字符串）。无法识别的路径一律归为 lobby；
 * `#/g/{id}` 没带 `gm=`/`spec=` 时仍返回 game 路由但不带 token（页面自行展示错误）。 */
export function parseHash(hash: string = location.hash): ParsedHash {
  const raw = hash.replace(/^#/, "");
  if (raw === "" || raw === "/") {
    return { route: "lobby" };
  }
  if (raw === "/agents" || raw.startsWith("/agents?") || raw.startsWith("/agents/")) {
    return { route: "agents" };
  }
  if (raw === "/providers" || raw.startsWith("/providers?") || raw.startsWith("/providers/")) {
    return { route: "providers" };
  }
  const match = /^\/g\/([^/?]+)(?:\?(.*))?$/.exec(raw);
  if (match) {
    const gameId = decodeURIComponent(match[1] ?? "");
    const query = new URLSearchParams(match[2] ?? "");
    const gm = query.get("gm");
    const spec = query.get("spec");
    if (gm) {
      return { route: "game", gameId, token: gm, viewer: "GM" };
    }
    if (spec) {
      return { route: "game", gameId, token: spec, viewer: "SPECTATOR" };
    }
    return { route: "game", gameId };
  }
  return { route: "lobby" };
}
