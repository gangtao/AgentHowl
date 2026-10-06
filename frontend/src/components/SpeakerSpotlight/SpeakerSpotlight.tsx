// 当前发言者聚光牌（issue #102 追加）：放在左栏座位环下方的空白区，放大显示发言座位的头像与名字。
// 零过滤：座位来自 state 的发言游标，头像 id 来自服务端 /games/{id}/avatars；无发言者不渲染。

import type { GameState } from "../../engine/types";
import Avatar from "../Avatar/Avatar";
import { seatColor } from "../seatColor";
import styles from "./SpeakerSpotlight.module.css";

export interface SpeakerSpotlightProps {
  state: GameState;
  /** 当前发言座位；null 时不渲染。 */
  seat: number | null;
  avatars: Record<number, string>;
}

export default function SpeakerSpotlight({
  state,
  seat,
  avatars,
}: SpeakerSpotlightProps): JSX.Element | null {
  if (seat === null) return null;
  const player = state.players.find((p) => p.seat === seat);
  if (!player) return null;
  const color = seatColor(state, seat);
  return (
    <div className={styles.root} role="status" aria-label={`${seat}号 ${player.display_name} 发言中`}>
      <div className={styles.ring} style={{ borderColor: color }}>
        <Avatar avatar={avatars[seat] ?? null} name={player.display_name} seat={seat} size={128} />
      </div>
      <div className={styles.text}>
        <span className={styles.seat} style={{ color }}>
          {seat}号
        </span>
        <span className={styles.name}>{player.display_name}</span>
        <span className={styles.tag}>发言中</span>
      </div>
    </div>
  );
}
