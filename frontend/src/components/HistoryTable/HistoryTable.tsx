// 历史对局表格「村志」账本（规格 §6，设计稿 1j）：零过滤——只渲染服务端 GameSummary 给出的字段。
// 操作列：finished → 回放、live → 观看（均为 `#/g/{id}`，靠登录态 cookie 以 GM 身份进入）；aborted → 无法回放。
// onShare：每行「分享」按钮（share_token 为 null 时禁用）；showOwner：管理员多一列「创建者」。
// 传入 onDelete 时每行多一个「删除」（issue #100）：直播中禁用，确认框由页面负责。

import type { GameSummary } from "../../api/history";
import { winnerColorVar } from "../../lib/pagesLook";
import styles from "./HistoryTable.module.css";

export interface HistoryTableProps {
  items: GameSummary[];
  onDelete?: (row: GameSummary) => void;
  onShare?: (row: GameSummary) => void;
  showOwner?: boolean;
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

/** 羊皮纸上的状态签：已结束木签、直播中篝火、中断描边。 */
function statusTagClass(status: GameSummary["status"]): string {
  if (status === "finished") return "tag tag-wood";
  if (status === "live") return "tag tag-accent-2";
  return `tag ${styles.tagAborted}`;
}

export default function HistoryTable({
  items,
  onDelete,
  onShare,
  showOwner = false,
}: HistoryTableProps): JSX.Element {
  if (items.length === 0) {
    return (
      <div className={`ah-parch ${styles.empty}`}>
        <div className={styles.emptyIcon}>⌛</div>
        <span className={styles.emptyTitle}>
          还没有对局，<a href="#/">去建一局</a>
        </span>
        <span className={styles.emptyDesc}>打完的对局会留在这里，服务端重启后仍可回放。</span>
      </div>
    );
  }

  return (
    <div className={`ah-parch ${styles.ledger}`}>
      <table className="table-parch">
        <thead>
          <tr>
            <th>开始时间</th>
            <th>剧本</th>
            {showOwner && <th>创建者</th>}
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
                <td className={styles.nowrap}>
                  <b>{formatStartedAt(row.started_at)}</b>
                  {/* 对局 id 可见可复制：排查问题时不用去 hover 别的列。 */}
                  <code className={styles.gameId} title={row.game_id}>
                    {row.game_id}
                  </code>
                </td>
                <td>{PRESET_LABEL[row.preset] ?? row.preset}</td>
                {showOwner && <td>{row.owner_name ?? "—"}</td>}
                <td>{row.num_players}</td>
                <td className={styles.nowrap}>
                  <span className={statusTagClass(row.status)}>{statusLabel(row)}</span>
                </td>
                <td>
                  {row.winner !== null ? (
                    <span
                      className={styles.winner}
                      style={
                        winnerColorVar(row.winner) !== null
                          ? { color: `var(${winnerColorVar(row.winner)})` }
                          : undefined
                      }
                    >
                      {WINNER_LABEL[row.winner] ?? row.winner}
                    </span>
                  ) : (
                    "—"
                  )}
                </td>
                <td>{row.rounds}</td>
                {/* 单元格对所有行恒定截断，所以只要有名单就挂 title（复核 m2）。 */}
                <td className={styles.seats} {...(seatsText !== "" ? { title: seatsText } : {})}>
                  {seatsText === "" ? "—" : seatsText}
                </td>
                <td className={styles.nowrap}>
                  {row.status === "finished" ? (
                    <a className={`btn btn-secondary ${styles.act}`} href={`#/g/${row.game_id}`}>
                      回放
                    </a>
                  ) : row.status === "live" ? (
                    <a className={`btn btn-secondary ${styles.act}`} href={`#/g/${row.game_id}`}>
                      观看
                    </a>
                  ) : (
                    <span className={styles.hint} title="没有终局事件，服务端不开放回放">
                      无法回放
                    </span>
                  )}
                  {onShare !== undefined && (
                    <button
                      type="button"
                      className={`btn btn-ghost ${styles.act} ${styles.share}`}
                      disabled={row.share_token === null}
                      title={row.share_token === null ? "该对局未开放观众" : "复制观众分享链接"}
                      onClick={() => onShare(row)}
                    >
                      分享
                    </button>
                  )}
                  {onDelete !== undefined && (
                    <button
                      type="button"
                      className={`btn btn-ghost ${styles.act} ${styles.del}`}
                      disabled={row.status === "live"}
                      title={
                        row.status === "live" ? "进行中的对局不能删除" : "删除事件文件，不可恢复"
                      }
                      onClick={() => onDelete(row)}
                    >
                      删除
                    </button>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
