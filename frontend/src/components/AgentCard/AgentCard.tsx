// AgentCard（设计稿 2b 网格卡 / 2a 档案库侧栏精简版）。
// 性格摘要复用 personality_summary 口径（lib/personality.ts 抄录自后端）。

import type { StoredAgent } from "../../api/agents";
import { personalitySummary, type PersonalitySpecShape } from "../../lib/personality";
import styles from "./AgentCard.module.css";

export interface AgentCardProps {
  stored: StoredAgent;
  /** 精简版：Lobby 侧栏用。 */
  compact?: boolean;
  /** provider 显示名（未配置 provider 时不传）。 */
  providerName?: string | null;
  selected?: boolean;
  onClick?(): void;
  onEdit?(): void;
  onDuplicate?(): void;
  onDelete?(): void;
}

function formatTime(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const pad = (n: number): string => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

export default function AgentCard({
  stored,
  compact = false,
  providerName,
  selected = false,
  onClick,
  onEdit,
  onDuplicate,
  onDelete,
}: AgentCardProps): JSX.Element {
  const p = stored.profile;
  const skills = p.skills ?? [];
  const shown = skills.includes("*") ? ["全部技能（*）"] : skills.slice(0, 3);
  const more = skills.includes("*") ? 0 : skills.length - shown.length;
  const summary = personalitySummary(p.personality as PersonalitySpecShape | null | undefined);
  const subModels = [
    p.model_speech ? `发言 ${p.model_speech}` : null,
    p.reflection_model ? `反思 ${p.reflection_model}` : null,
  ]
    .filter((x): x is string => x !== null)
    .join(" · ");

  if (compact) {
    return (
      <div
        className={`card ${styles.compact} ${selected ? styles.selected : ""}`}
        onClick={onClick}
        role={onClick ? "button" : undefined}
        tabIndex={onClick ? 0 : undefined}
        onKeyDown={(e) => {
          if (onClick && (e.key === "Enter" || e.key === " ")) {
            e.preventDefault();
            onClick();
          }
        }}
      >
        <div className={styles.compactHead}>
          <span className={styles.compactName}>{p.name}</span>
          <span className={styles.mono}>{p.model}</span>
        </div>
        <div className={styles.tags}>
          {shown.map((s) => (
            <span key={s} className="tag tag-neutral" style={{ padding: "1px 7px", fontSize: 10 }}>
              {s}
            </span>
          ))}
          {more > 0 && <span className={styles.more}>+{more}</span>}
        </div>
        <div className={styles.compactFoot}>
          <span>{summary || "—"}</span>
          {p.memory_id && <span className={styles.memory}>记忆 {p.memory_id}</span>}
        </div>
      </div>
    );
  }

  return (
    <div className={`card elev-sm ${styles.card}`}>
      <div className={styles.head}>
        <div className={styles.headMain}>
          <span className={styles.name}>{p.name}</span>
          <span className={styles.mono}>{p.model}</span>
          <span className={styles.sub}>
            {providerName ? `服务 ${providerName}` : "兼容模式 · 无 provider"}
            {subModels ? ` · ${subModels}` : ""}
          </span>
        </div>
        <span className={styles.temp}>T={p.temperature ?? 0.3}</span>
      </div>
      <div className={styles.tags}>
        {shown.length === 0 ? (
          <span className={styles.more}>无技能</span>
        ) : (
          shown.map((s) => (
            <span key={s} className="tag tag-neutral" style={{ padding: "1px 8px", fontSize: 10.5 }}>
              {s}
            </span>
          ))
        )}
        {more > 0 && <span className={styles.more}>+{more}</span>}
      </div>
      <div className={styles.body}>
        <span className={styles.summary}>{summary || "—"}</span>
        {p.memory_id && <span className={styles.memory}>记忆 {p.memory_id}</span>}
      </div>
      <div className="card-meta" style={{ marginTop: "auto", justifyContent: "space-between" }}>
        <span>更新于 {formatTime(stored.updated_at)}</span>
        <span className={styles.actions}>
          {onEdit && (
            <button type="button" className="btn btn-ghost" onClick={onEdit}>
              编辑
            </button>
          )}
          {onDuplicate && (
            <button type="button" className="btn btn-ghost" onClick={onDuplicate}>
              复制
            </button>
          )}
          {onDelete && (
            <button type="button" className={`btn btn-ghost ${styles.del}`} onClick={onDelete}>
              删除
            </button>
          )}
        </span>
      </div>
    </div>
  );
}
