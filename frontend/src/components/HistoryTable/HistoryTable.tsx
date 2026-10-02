// 历史对局表格（issue #98 设计 §3）：零过滤——只渲染服务端 GameSummary 给出的字段。
// 操作列：finished → 无 token 回放链接；live → 提示用建局链接观看；aborted → 无法回放。

import type { GameSummary } from "../../api/history";
import styles from "./HistoryTable.module.css";

export interface HistoryTableProps {
  items: GameSummary[];
}

/** 板子 id → 中文名（后端 presets）；未知 id 原样显示。 */
const PRESET_LABEL: Record<string, string> = {
  std_9_kill_side: "9 人屠边",
  std_9_kill_all: "9 人屠城",
  std_12_yn_hunter_idiot: "12 人预女猎白",
  std_12_yn_hunter_guard: "12 人预女猎守",
};

const WINNER_LABEL: Record<string, string> = {
  GOOD: "好人胜",
  WOLF: "狼人胜",
};

/** 超过这个座位数就只在 title 里放全文，单元格截断显示。 */
const SEATS_INLINE_MAX = 6;

/** ISO 时间 → 本地时区 `MM-DD HH:mm`；null / 不可解析 → `—`。 */
function formatStartedAt(iso: string | null): string {
  if (iso === null) return "—";
  const at = new Date(iso);
  if (Number.isNaN(at.getTime())) return "—";
  const pad = (n: number): string => String(n).padStart(2, "0");
  return `${pad(at.getMonth() + 1)}-${pad(at.getDate())} ${pad(at.getHours())}:${pad(at.getMinutes())}`;
}

function statusLabel(row: GameSummary): string {
  if (row.status === "finished") return "已结束";
  if (row.status === "live") return "直播中";
  return `中断于第 ${row.rounds} 轮`;
}

function statusTagClass(status: GameSummary["status"]): string {
  if (status === "finished") return "tag tag-accent";
  if (status === "live") return "tag tag-accent-2";
  return "tag tag-neutral";
}

export default function HistoryTable({ items }: HistoryTableProps): JSX.Element {
  if (items.length === 0) {
    return (
      <div className={styles.empty}>
        <div className={styles.emptyIcon}>⌛</div>
        <span className={styles.emptyTitle}>
          还没有对局，<a href="#/">去建一局</a>
        </span>
        <span className={styles.emptyDesc}>
          打完的对局会留在 data/games/ 里，服务端重启后仍可在这里回放。
        </span>
      </div>
    );
  }

  return (
    <table className="table">
      <thead>
        <tr>
          <th>开始时间</th>
          <th>板子</th>
          <th>人数</th>
          <th>状态</th>
          <th>胜方</th>
          <th>轮数</th>
          <th>座位</th>
          <th>操作</th>
        </tr>
      </thead>
      <tbody>
        {items.map((row) => {
          const names = row.seats.map((s) => s.display_name);
          const seatsText = names.join("、");
          return (
            <tr key={row.game_id}>
              <td className={styles.nowrap}>{formatStartedAt(row.started_at)}</td>
              <td title={row.game_id}>{PRESET_LABEL[row.preset] ?? row.preset}</td>
              <td>{row.num_players}</td>
              <td className={styles.nowrap}>
                <span className={statusTagClass(row.status)}>{statusLabel(row)}</span>
              </td>
              <td>{row.winner !== null ? (WINNER_LABEL[row.winner] ?? row.winner) : "—"}</td>
              <td>{row.rounds}</td>
              <td
                className={styles.seats}
                {...(names.length > SEATS_INLINE_MAX ? { title: seatsText } : {})}
              >
                {seatsText === "" ? "—" : seatsText}
              </td>
              <td className={styles.nowrap}>
                {row.status === "finished" ? (
                  <a className="btn btn-primary" href={`#/g/${row.game_id}?replay=1`}>
                    回放
                  </a>
                ) : row.status === "live" ? (
                  <span className={styles.hint}>用建局时的链接观看</span>
                ) : (
                  <span className={styles.hint} title="没有终局事件，服务端不开放回放">
                    无法回放
                  </span>
                )}
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}
