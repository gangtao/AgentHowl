// AgentCard：完整卡 = 「村民名册」角色牌（规格 §6，设计稿 1k）——篝火光晕 + 首字渐变圆 + 名字 +
// 金色人格摘要 + 羊皮纸三行（声望 / 战绩 / 性情）+ 技能签 + 模型行 + 操作；精简卡（大厅 <900px 回退）不变。
// 性格摘要复用 personality_summary 口径（lib/personality.ts 抄录自后端）。

import type { StoredAgent } from "../../api/agents";
import { personalitySummary, type PersonalitySpecShape } from "../../lib/personality";
import { nameGradientCss } from "../../lib/pagesLook";
import { ratingLine } from "../../lib/rating";
import Avatar from "../Avatar/Avatar";
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
          <span className={styles.compactNameRow}>
            <Avatar avatar={p.avatar ?? null} name={p.name ?? ""} seat={null} size={22} />
            <span className={styles.compactName}>{p.name}</span>
          </span>
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
        <div className={styles.rating}>{ratingLine(stored.rating)}</div>
      </div>
    );
  }

  const r = stored.rating;
  const record =
    r.games === 0 ? "尚无战绩" : `${r.games} 局 · 胜率 ${Math.round((r.wins / r.games) * 100)}%`;
  return (
    <article className={styles.card} data-agent-id={stored.agent_id}>
      <div className={styles.crown}>
        <Avatar
          avatar={p.avatar ?? null}
          name={p.name ?? ""}
          seat={null}
          size={72}
          color={nameGradientCss(p.name)}
        />
        <h3 className={styles.name}>{p.name}</h3>
        {summary !== "" && <span className={styles.title}>「{summary}」</span>}
      </div>
      <div className={styles.lower}>
        <div className={`ah-parch ${styles.strip}`}>
          <div className={styles.stripRow}>
            <span>声望</span>
            <b>{Math.round(r.rating)}</b>
          </div>
          <div className={styles.stripRow}>
            <span>战绩</span>
            <span>{record}</span>
          </div>
          <div className={styles.stripRow}>
            <span>性情</span>
            <span className={styles.stripVal}>{summary || "—"}</span>
          </div>
        </div>
        <div className={styles.skills}>
          {shown.length === 0 ? (
            <span className={styles.more}>无技能</span>
          ) : (
            shown.map((s) => (
              <span key={s} className={styles.skill}>
                {s}
              </span>
            ))
          )}
          {more > 0 && <span className={styles.more}>+{more}</span>}
        </div>
        <span
          className={styles.meta}
          title={[
            providerName ? `服务 ${providerName}` : "兼容模式 · 无 provider",
            subModels,
            p.memory_id ? `记忆 ${p.memory_id}` : null,
            `更新于 ${formatTime(stored.updated_at)}`,
          ]
            .filter((x): x is string => !!x)
            .join(" · ")}
        >
          {p.model} · T={p.temperature ?? 0.3}
        </span>
        {(onEdit || onDuplicate || onDelete) && (
          <div className={styles.actions}>
            {onEdit && (
              <button type="button" className={styles.action} onClick={onEdit}>
                编辑
              </button>
            )}
            {onDuplicate && (
              <button type="button" className={styles.action} onClick={onDuplicate}>
                复制
              </button>
            )}
            {onDelete && (
              <button type="button" className={`${styles.action} ${styles.del}`} onClick={onDelete}>
                删除
              </button>
            )}
          </div>
        )}
      </div>
    </article>
  );
}
