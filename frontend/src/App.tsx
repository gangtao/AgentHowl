// Hash 路由（规格 §7.1）：#/ Lobby、#/agents 档案库、#/providers 模型服务、#/g/{id} 对局页。
// `#/g/…` 不显示顶部导航——对局页有自己的顶栏（PhaseBar）。

import { useEffect, useState } from "react";
import { parseHash } from "./api/tokens";
import type { ParsedHash } from "./api/tokens";
import GamePage from "./pages/GamePage";

const NAV = [
  { href: "#/", label: "新的一局", route: "lobby" as const },
  { href: "#/agents", label: "Agent 档案库", route: "agents" as const },
  { href: "#/providers", label: "模型服务", route: "providers" as const },
];

export default function App(): JSX.Element {
  const [hash, setHash] = useState<ParsedHash>(() => parseHash());

  useEffect(() => {
    const onHash = (): void => setHash(parseHash());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  if (hash.route === "game") {
    return (
      <GamePage
        key={`${hash.gameId ?? ""}:${hash.viewer ?? ""}`}
        gameId={hash.gameId}
        token={hash.token}
        viewer={hash.viewer}
      />
    );
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
      </nav>
      {/* Lobby / AgentLibrary / Providers 页由 Task 8 实现，这里先占位。 */}
      <main style={{ padding: "36px var(--space-8) 32px 56px" }}>
        <h3>{NAV.find((n) => n.route === hash.route)?.label ?? "AgentHowl"}</h3>
        <p className="text-muted" style={{ fontSize: 13 }}>
          该页面尚未实现。打开对局链接（<code>#/g/&#123;gameId&#125;?gm=…</code> 或{" "}
          <code>?spec=…</code>）即可观看直播与回放。
        </p>
      </main>
    </div>
  );
}
