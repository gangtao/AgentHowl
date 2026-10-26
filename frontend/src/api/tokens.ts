// Hash 路由解析：token 只放在 URL hash（规格 §6），不写 localStorage。
// 支持：#/、#/agents、#/providers、#/history、#/login、#/register、#/verify、#/admin、
// #/g/{gameId}?gm=…、#/g/{gameId}?player=…（玩家 token，issue #115）、
// #/g/{gameId}?share=…（分享链接，issue #114）、
// 裸 #/g/{gameId}（靠 cookie 登录态，视角由服务端决定：建局者已入座 → 玩家，否则 GM）。

export type Route = "lobby" | "agents" | "providers" | "history" | "game" | "login" | "register" | "verify" | "admin";
/** URL 里的视角提示（issue #115）：`?gm=` → GM、`?share=` → SPECTATOR；`?player=` 与裸路径不给提示，
 * GamePage 以 `/state` / `/meta` 响应里的 `viewer` 为准。 */
export type ViewerHint = "GM" | "SPECTATOR";

export interface ParsedHash {
  route: Route;
  gameId?: string;
  token?: string;
  viewer?: ViewerHint;
  /** 分享链接 token（`?share=`，issue #114）。 */
  share?: string;
}

/** 解析当前 `location.hash`（或传入的字符串）。无法识别的路径一律归为 lobby；
 * `#/g/{id}` 没带 `gm=`/`share=` 时返回 game 路由、不带 viewer 提示、不带 token（靠 cookie 会话）。 */
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
  if (raw === "/history" || raw.startsWith("/history?") || raw.startsWith("/history/")) {
    return { route: "history" };
  }
  for (const r of ["login", "register", "verify", "admin"] as const) {
    if (raw === `/${r}` || raw.startsWith(`/${r}?`) || raw.startsWith(`/${r}/`)) {
      return { route: r };
    }
  }
  const match = /^\/g\/([^/?]+)(?:\?(.*))?$/.exec(raw);
  if (match) {
    const gameId = decodeURIComponent(match[1] ?? "");
    const query = new URLSearchParams(match[2] ?? "");
    const gm = query.get("gm");
    const player = query.get("player");
    const share = query.get("share");
    // 多个参数同时出现（不该发生，但不信任 URL）：gm > player > share——
    // 权限高的不能被同时携带的低权限参数降级。
    if (gm) {
      return { route: "game", gameId, token: gm, viewer: "GM" };
    }
    if (player) {
      return { route: "game", gameId, token: player };
    }
    if (share) {
      return { route: "game", gameId, share, viewer: "SPECTATOR" };
    }
    return { route: "game", gameId };
  }
  return { route: "lobby" };
}
