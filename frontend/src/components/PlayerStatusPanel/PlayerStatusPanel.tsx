// 右栏 · 发言顺序 / 公开警徽流 / 备注行（设计稿 1d）。
// 零过滤：全部取自 state，且不看 viewer——备注行的狼人座位在没有角色数据时本就是空数组，
// 空则不渲染，有则照实渲染。

import { DIRECTION_ZH, factionColorVar } from "../../engine/phases";
import { wolfSeats } from "../../engine/select";
import type { GameState } from "../../engine/types";
import styles from "./PlayerStatusPanel.module.css";

export interface PlayerStatusPanelProps {
  state: GameState;
  speakingSeat: number | null;
}

export default function PlayerStatusPanel({
  state,
  speakingSeat,
}: PlayerStatusPanelProps): JSX.Element {
  const nameOf = new Map(state.players.map((p) => [p.seat, p.display_name]));
  const order = state.speech_order;
  const badgeFlows = Object.entries(state.badge_flow_claims);
  const wolves = wolfSeats(state);
  const direction = state.sheriff_speech_direction;

  return (
    <section className={styles.root}>
      <div className={styles.head}>
        <span className={styles.title}>发言顺序</span>
        <span className={styles.sub}>
          {state.sheriff_seat !== null ? `警长 ${state.sheriff_seat}号` : "无警长"}
          {direction !== null ? ` · ${DIRECTION_ZH[direction] ?? direction}` : ""}
        </span>
      </div>

      {order.length > 0 ? (
        <div className={styles.order}>
          {order.map((seat, i) => {
            const status =
              i < state.speech_idx ? "已发言" : seat === speakingSeat ? "发言中" : "待发言";
            return (
              <div
                key={seat}
                className={`${styles.orderRow} ${seat === speakingSeat ? styles.orderNow : ""}`}
              >
                <span className={styles.orderSeat}>{seat}号</span>
                <span className={styles.orderName}>{nameOf.get(seat) ?? ""}</span>
                <span className={styles.orderStatus} data-status={status}>
                  {status}
                </span>
              </div>
            );
          })}
        </div>
      ) : (
        <div className={styles.emptyLine}>本阶段没有发言顺序</div>
      )}

      {badgeFlows.length > 0 && (
        <>
          <div className={styles.head}>
            <span className={styles.title}>公开警徽流</span>
          </div>
          <div className={styles.tags}>
            {badgeFlows.map(([seat, flow]) => (
              <span className="tag tag-neutral" key={seat}>
                {seat}号：{flow.join(" → ")}
              </span>
            ))}
          </div>
        </>
      )}

      {wolves.length > 0 && (
        <div className={styles.footer}>
          GM 备注：狼人{" "}
          {wolves.map((s, i) => {
            const p = state.players.find((x) => x.seat === s);
            return (
              <span key={s} style={{ color: p ? `var(${factionColorVar(p.role)})` : undefined }}>
                {i > 0 ? "、" : ""}
                {s}号
              </span>
            );
          })}{" "}
          · 存活 {state.players.filter((p) => p.alive && p.faction === "WOLF").length} 匹
        </div>
      )}
    </section>
  );
}
