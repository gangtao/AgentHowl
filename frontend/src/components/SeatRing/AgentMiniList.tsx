// AgentMiniList（规格 §5 第 2 步，设计稿 1d 左栏）：羊皮纸搜索框 + 两列迷你档案卡（40px 首字圆 / 名字 /
// 模型简称 / 战绩）。点卡片 = 预选，再点同一张取消；真正的分配发生在 SeatRing 点座位时。

import { useState } from "react";
import type { StoredAgent } from "../../api/agents";
import { ratingLine } from "../../lib/rating";
import Avatar from "../Avatar/Avatar";
import styles from "./AgentMiniList.module.css";

export interface AgentMiniListProps {
  library: StoredAgent[];
  selected: string | null;
  /** 再点已选中的卡 → null。 */
  onSelect(agentId: string | null): void;
  onNewAgent(): void;
}

/** `openai/gpt-5` → `gpt-5`；没有斜杠原样返回。 */
function modelShort(model: string): string {
  return model.split("/").pop() ?? model;
}

export default function AgentMiniList({
  library,
  selected,
  onSelect,
  onNewAgent,
}: AgentMiniListProps): JSX.Element {
  const [query, setQuery] = useState("");
  const q = query.trim().toLowerCase();
  const filtered = library.filter((a) => {
    if (!q) return true;
    const p = a.profile;
    return [p.name, p.model, p.memory_id].some((v) => (v ?? "").toLowerCase().includes(q));
  });

  return (
    <div className={styles.root}>
      <input
        className="input"
        value={query}
        placeholder="⌕ 搜索档案…"
        aria-label="搜索档案"
        onChange={(e) => setQuery(e.target.value)}
      />
      {library.length === 0 ? (
        <span className={styles.hint}>档案库是空的；不分配也能开局（全随机 bot）。</span>
      ) : filtered.length === 0 ? (
        <span className={styles.hint}>没有匹配的档案。</span>
      ) : (
        <div className={styles.grid}>
          {filtered.map((a) => {
            const on = selected === a.agent_id;
            return (
              <button
                key={a.agent_id}
                type="button"
                className={styles.card}
                aria-pressed={on}
                data-agent-id={a.agent_id}
                onClick={() => onSelect(on ? null : a.agent_id)}
              >
                <Avatar
                  avatar={a.profile.avatar ?? null}
                  name={a.profile.name ?? ""}
                  seat={null}
                  size={40}
                />
                <span className={styles.text}>
                  <span className={styles.name}>{a.profile.name}</span>
                  <span className={styles.model}>{modelShort(a.profile.model)}</span>
                  <span className={styles.record}>{ratingLine(a.rating)}</span>
                </span>
              </button>
            );
          })}
        </div>
      )}
      <button type="button" className="btn btn-secondary" onClick={onNewAgent}>
        + 新建 Agent
      </button>
    </div>
  );
}
