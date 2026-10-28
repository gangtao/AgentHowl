// 顶栏（规格 §4.1，设计稿 3a / 5c / 7d）：品牌、对局 id、居中状态（直播 / 回放 / 终局 / 连接），
// 右侧视角分段标签与插槽（匿名观众的「登录」、玩家的语音开关、PR ⑤ 的桌面皮肤切换）。
// 轮次与阶段名不再放顶栏——它们在左上角的阶段木牌（PhasePlaque）上。

import type { ReactNode } from "react";
import type { GameState } from "../../engine/types";
import { statusText } from "../../lib/phaseText";
import type { ConnectionState, PlaybackMode, Viewer } from "../../store/game";
import styles from "./PhaseBar.module.css";

export interface PhaseBarProps {
  state: GameState;
  mode: PlaybackMode;
  viewer: Viewer;
  connection: ConnectionState;
  /** 事件流总条数（最后一条 seq）。 */
  totalSeq: number;
  /** 这局是否已结束（head 到终局或回放模式）。 */
  over: boolean;
  /** 最终胜方（来自 head，而不是回放游标处的 state）。 */
  winner: string | null;
  /** 右侧插槽。 */
  extra?: ReactNode;
}

/** 长 game_id 缩略成 `g_7f3a…c21` 的样子。 */
function shortId(id: string): string {
  return id.length > 14 ? `${id.slice(0, 6)}…${id.slice(-3)}` : id;
}

export default function PhaseBar({
  state,
  mode,
  viewer,
  connection,
  totalSeq,
  over,
  winner,
  extra,
}: PhaseBarProps): JSX.Element {
  const status = statusText(winner, mode, connection, totalSeq, over);
  // 终局之后仍要告诉用户现在是回放还是直播（设计稿 5c：居中「游戏结束」，右侧「▶ 回放 · N 条事件」）。
  const secondary = over ? statusText(winner, mode, connection, totalSeq, false) : null;
  return (
    <header className={styles.root}>
      <span className={styles.brand}>AgentHowl</span>
      <span className={styles.gameId} title={state.game_id}>
        {shortId(state.game_id)}
      </span>
      <span className={styles.spacer} />
      <span className={styles.status} data-tone={status.tone} role="status">
        {status.tone === "over" && <span className={styles.rule} aria-hidden="true" />}
        {status.text}
        {status.tone === "over" && <span className={styles.rule} aria-hidden="true" />}
      </span>
      <span className={styles.spacer} />
      {secondary !== null && (
        <span className={styles.status} data-tone={secondary.tone}>
          {secondary.text}
        </span>
      )}
      {extra}
      <span className="seg" aria-label="视角">
        <span className="seg-opt" {...(viewer === "GM" ? { "aria-current": "true" } : {})}>
          上帝
        </span>
        <span className="seg-opt" {...(viewer === "SPECTATOR" ? { "aria-current": "true" } : {})}>
          观众
        </span>
        <span
          className="seg-opt"
          {...(typeof viewer === "number" ? { "aria-current": "true" } : {})}
        >
          {typeof viewer === "number" ? `玩家 ${viewer}号` : "玩家"}
        </span>
      </span>
    </header>
  );
}
