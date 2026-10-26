// Hash 路由（规格 §7.1）：#/ Lobby、#/agents 档案库、#/providers 模型服务、#/g/{id} 对局页。
// `#/g/…` 不显示顶部导航——对局页有自己的顶栏（PhaseBar）。

import { useEffect, useState } from "react";
import { setUnauthorizedHandler } from "./api/rest";
import { parseHash } from "./api/tokens";
import type { ParsedHash } from "./api/tokens";
import AdminUsers from "./pages/AdminUsers";
import AgentLibrary from "./pages/AgentLibrary";
import GamePage from "./pages/GamePage";
import History from "./pages/History";
import Lobby from "./pages/Lobby";
import LoginPage from "./pages/LoginPage";
import Providers from "./pages/Providers";
import { useAuth } from "./store/auth";

const NAV = [
  { href: "#/", label: "新的一局", route: "lobby" as const },
  { href: "#/history", label: "历史对局", route: "history" as const },
  { href: "#/agents", label: "Agent 档案库", route: "agents" as const },
  { href: "#/providers", label: "模型服务", route: "providers" as const },
];

const NEXT_KEY = "agenthowl.next";

// sessionStorage 在隐私模式下可能抛：读写都吞掉，最差退回首页。
function readNext(): string {
  try {
    return sessionStorage.getItem(NEXT_KEY) ?? "#/";
  } catch {
    return "#/";
  }
}

function writeNext(value: string): void {
  try {
    sessionStorage.setItem(NEXT_KEY, value);
  } catch {
    // 记不住就算了
  }
}

export default function App(): JSX.Element {
  const [hash, setHash] = useState<ParsedHash>(() => parseHash());
  const status = useAuth((s) => s.status);
  const user = useAuth((s) => s.user);
  const anonLogin = status === "anon" && hash.route !== "login" && hash.route !== "register" && hash.route !== "verify" && hash.route !== "game";

  useEffect(() => {
    setUnauthorizedHandler(() => {
      // 只有「已登录后会话丢失」才需要重新确认；匿名态的 401 无需处理。
      if (useAuth.getState().status === "authed") void useAuth.getState().load();
    });
    void useAuth.getState().load();
    return () => setUnauthorizedHandler(null);
  }, []);

  // 匿名访问受保护路由：记下目的地，登录后回跳（hash 不动，刷新仍停在原路由）。
  useEffect(() => {
    if (anonLogin) writeNext(location.hash || "#/");
  }, [anonLogin]);

  useEffect(() => {
    const onHash = (): void => setHash(parseHash());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  if (hash.route === "game") {
    return (
      <GamePage
        key={`${hash.gameId ?? ""}:${hash.token ?? ""}:${hash.viewer ?? ""}:${hash.share ?? ""}`}
        gameId={hash.gameId}
        token={hash.token}
        viewer={hash.viewer}
        share={hash.share}
      />
    );
  }

  if (hash.route === "login" || hash.route === "register" || hash.route === "verify") {
    return <LoginPage mode={hash.route} next={readNext()} />;
  }

  let body: JSX.Element;
  if (status === "loading") {
    body = <p className="text-muted">载入中…</p>;
  } else if (status === "anon") {
    body = <LoginPage mode="login" next={location.hash || "#/"} />;
  } else if (hash.route === "history") {
    body = <History />;
  } else if (hash.route === "agents") {
    body = <AgentLibrary />;
  } else if (hash.route === "providers") {
    body = <Providers />;
  } else {
    // admin 页仅管理员可见；非 admin 一律退回大厅。
    body = hash.route === "admin" && user?.role === "admin" ? <AdminUsers /> : <Lobby />;
  }

  return (
    <div style={{ height: "100%", display: "grid", gridTemplateRows: "56px minmax(0, 1fr)" }}>
      <nav className="nav">
        <span className="nav-brand">AgentHowl</span>
        {NAV.map((n) => (
          <a
            key={n.href}
            href={n.href}
            {...(hash.route === n.route ? { "aria-current": "page" as const } : {})}
          >
            {n.label}
          </a>
        ))}
        <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 12 }}>
          {user ? (
            <>
              <span>
                {user.username}
                {user.role === "admin" ? " · admin" : ""}
              </span>
              {user.role === "admin" && <a href="#/admin">用户</a>}
              <button
                className="btn btn-ghost"
                onClick={() => {
                  void useAuth
                    .getState()
                    .logout()
                    .finally(() => {
                      window.location.hash = "#/login";
                    })
                    .catch(() => {
                      /* 登出失败已在 finally 中置匿名，无需再抛 */
                    });
                }}
              >
                登出
              </button>
            </>
          ) : (
            <a href="#/login">登录</a>
          )}
        </div>
      </nav>
      {body}
    </div>
  );
}
