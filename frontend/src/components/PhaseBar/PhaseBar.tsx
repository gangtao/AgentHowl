// 顶栏（设计稿 1c/1d/1g/1h/1j）：轮次、阶段中文、模式徽标、连接状态、视角标签。

import { ELECTION_STAGE_ZH, PHASE_ZH } from "../../engine/phases";
import type { GameState } from "../../engine/types";
import type { ConnectionState, PlaybackMode, Viewer } from "../../store/game";
import styles from "./PhaseBar.module.css";

export interface PhaseBarProps {
  state: GameState;
  mode: PlaybackMode;
  viewer: Viewer;
  connection: ConnectionState;
  /** 当前显示到的 seq（回放游标或最新）。 */
  lastSeq: number;
  /** 事件流总条数（最后一条 seq）。 */
  totalSeq: number;
  /** 重连提示文案（无则不显示）。 */
  reconnectHint?: string | null;
}

/** 长 game_id 缩略成 `g_7f3a…c21` 的样子。 */
function shortId(id: string): string {
  return id.length > 14 ? `${id.slice(0, 6)}…${id.slice(-3)}` : id;
}

function phaseLabel(state: GameState): string {
  const base = PHASE_ZH[state.phase] ?? state.phase;
  if (state.phase === "SHERIFF_ELECTION" && state.election_stage !== "") {
    return `${base} · ${ELECTION_STAGE_ZH[state.election_stage]}`;
  }
  return base;
}

function connectionLabel(
  connection: ConnectionState,
  mode: PlaybackMode,
  totalSeq: number,
  over: boolean,
): string {
  if (mode === "replay" || over) return `已结束 · ${totalSeq} 条事件`;
  if (connection === "open") return `已连接 · seq ${totalSeq}`;
  if (connection === "connecting") return "连接中…";
  if (connection === "closed") return "连接已断开";
  if (connection === "error") return "连接错误";
  return "未连接";
}

export default function PhaseBar({
  state,
  mode,
  viewer,
  connection,
  lastSeq,
  totalSeq,
  reconnectHint,
}: PhaseBarProps): JSX.Element {
  const over = state.phase === "GAME_OVER";
  return (
    <header className={styles.root}>
      <span className={styles.brand}>AgentHowl</span>
      <span className={styles.gameId} title={state.game_id}>
        {shortId(state.game_id)}
      </span>
      <span className="tag tag-neutral">第 {state.round} 轮</span>
      <span className={styles.phase}>{phaseLabel(state)}</span>
      {mode === "live" ? (
        <span className={styles.mode}>
          <span className={styles.liveDot} />
          直播
        </span>
      ) : (
        <span className={styles.mode}>
          <span className={styles.replayIcon}>▶</span>回放
        </span>
      )}
      {reconnectHint ? (
        <span className={styles.reconnect}>
          <span className={styles.reconnectDot} />
          {reconnectHint}
        </span>
      ) : null}
      <span className={styles.status}>
        {connectionLabel(connection, mode, totalSeq, over)}
        {lastSeq !== totalSeq ? ` · 回放到 seq ${lastSeq}` : ""}
      </span>
      <span className={`seg ${styles.seg}`}>
        <span className={`seg-opt ${viewer === "GM" ? styles.segOn : ""}`}>上帝</span>
        <span className={`seg-opt ${viewer === "SPECTATOR" ? styles.segOn : ""}`}>观众</span>
      </span>
    </header>
  );
}
