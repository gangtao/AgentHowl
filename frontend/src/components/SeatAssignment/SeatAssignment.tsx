// SeatAssignment（设计稿 2a 步骤 2）：左档案库侧栏 + 右座位表 / 工具行 / 图例。
//
// 受控组件：自身不持有分配状态，由 Lobby 传入并回调。座位下拉里，memory_id 已被其它座位
// 占用的档案被禁用并提示「该记忆已在 N号 使用」（后端 validate_profiles 也会 400）。

import { useMemo, useState } from "react";
import type { StoredAgent } from "../../api/agents";
import { memoryConflicts, type SeatSlot } from "../../lib/seats";
import AgentCard from "../AgentCard/AgentCard";
import styles from "./SeatAssignment.module.css";

export interface SeatAssignmentProps {
  library: StoredAgent[];
  assignment: SeatSlot[];
  /** 「填满其余座位」的档案 id（写入 `"*"`）；null = 其余座位是随机 bot。 */
  fill: string | null;
  onAssign(seat: number, agentId: string | null): void;
  onFill(agentId: string | null): void;
  onAllRandom(): void;
  onShuffle(): void;
  onNewAgent(): void;
}

export default function SeatAssignment({
  library,
  assignment,
  fill,
  onAssign,
  onFill,
  onAllRandom,
  onShuffle,
  onNewAgent,
}: SeatAssignmentProps): JSX.Element {
  const [query, setQuery] = useState("");
  const conflicts = useMemo(() => memoryConflicts(assignment, library), [assignment, library]);
  const byId = useMemo(() => new Map(library.map((a) => [a.agent_id, a])), [library]);

  const filtered = library.filter((a) => {
    const q = query.trim().toLowerCase();
    if (!q) return true;
    const p = a.profile;
    return [p.name, p.model, p.memory_id].some((v) => (v ?? "").toLowerCase().includes(q));
  });

  const fillAgent = fill === null ? null : (byId.get(fill) ?? null);
  const fillHasMemory = fillAgent?.profile.memory_id != null;

  return (
    <div className={styles.root}>
      <div className={styles.sidebar}>
        <input
          className="input"
          value={query}
          placeholder="⌕ 搜索档案…"
          aria-label="搜索档案"
          onChange={(e) => setQuery(e.target.value)}
        />
        <div className={styles.list}>
          {library.length === 0 ? (
            <span className={styles.hint}>档案库是空的；不分配也能开局（全随机 bot）。</span>
          ) : filtered.length === 0 ? (
            <span className={styles.hint}>没有匹配的档案。</span>
          ) : (
            filtered.map((a) => <AgentCard key={a.agent_id} stored={a} compact />)
          )}
          <button type="button" className="btn btn-secondary" onClick={onNewAgent}>
            + 新建 Agent
          </button>
        </div>
      </div>

      <div className={styles.seats}>
        <div className={styles.tools}>
          <span className={styles.toolLabel}>工具：</span>
          <label className={styles.fillLabel}>
            填满其余座位（*）
            <select
              className={`input ${styles.fillSelect}`}
              value={fill ?? ""}
              aria-label="填满其余座位"
              onChange={(e) => onFill(e.target.value || null)}
            >
              <option value="">不填（随机 bot）</option>
              {library.map((a) => (
                <option key={a.agent_id} value={a.agent_id} disabled={a.profile.memory_id != null}>
                  {a.profile.name}
                  {a.profile.memory_id != null ? "（含 memory_id，不可填满）" : ""}
                </option>
              ))}
            </select>
          </label>
          <button type="button" className="btn btn-secondary" onClick={onAllRandom}>
            全部随机 bot
          </button>
          <button type="button" className="btn btn-secondary" onClick={onShuffle}>
            随机打乱
          </button>
        </div>

        {fillHasMemory && (
          <span className={styles.warn}>
            「{fillAgent?.profile.name}」配置了 memory_id，不能用于填满（<code>&quot;*&quot;</code>{" "}
            会展开成多个座位共用一份记忆，后端 400）。请改用逐座位分配。
          </span>
        )}

        <div className={styles.grid}>
          {assignment.map((slot) => {
            const conflictSeat = slot.agentId === null ? undefined : conflicts.get(slot.agentId);
            return (
              <div key={slot.seat} className={styles.row}>
                <span className={styles.seatNo}>{slot.seat}号</span>
                <div className={styles.rowMain}>
                  <select
                    className={`input ${styles.select} ${slot.agentId ? styles.selectOn : ""}`}
                    value={slot.agentId ?? ""}
                    aria-label={`${slot.seat}号 座位`}
                    onChange={(e) => onAssign(slot.seat, e.target.value || null)}
                  >
                    <option value="">{fill === null ? "随机 bot" : "填满（*）"}</option>
                    {library.map((a) => {
                      const takenAt = conflicts.get(a.agent_id);
                      const disabled = takenAt !== undefined && takenAt !== slot.seat;
                      return (
                        <option key={a.agent_id} value={a.agent_id} disabled={disabled}>
                          {a.profile.name}
                          {disabled ? `（记忆已在 ${takenAt}号 使用）` : ""}
                        </option>
                      );
                    })}
                  </select>
                  {conflictSeat !== undefined && conflictSeat !== slot.seat && (
                    <span className={styles.warn}>该记忆已在 {conflictSeat}号 使用</span>
                  )}
                </div>
              </div>
            );
          })}
        </div>

        <div className={styles.legend}>
          <span>
            ● 座位专属档案 → <code>&quot;{"{seat}"}&quot;</code> · ● 填满 → <code>&quot;*&quot;</code> ·
            随机 bot 不写入
          </span>
          <span>同一档案可放多个座位；配置了 memory_id 的档案只能占一个座位。</span>
        </div>
      </div>
    </div>
  );
}
