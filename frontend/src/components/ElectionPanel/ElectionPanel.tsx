// 右栏 · 警长竞选（设计稿 1f）：子阶段进度、上警名单（退水划线）、警下计票、当选 / 方向 / 警徽流失。

import { BADGE_LOST_ZH, DIRECTION_ZH, ELECTION_STAGE_ZH, ROLE_ABBR } from "../../engine/phases";
import { rolesKnown, sheriffVoteTally } from "../../engine/select";
import type { ElectionStage, Event, GameState, SheriffBadgeLostPayload } from "../../engine/types";
import { seatColor, seatName } from "../seatColor";
import styles from "./ElectionPanel.module.css";

export interface ElectionPanelProps {
  state: GameState;
  /** 已按回放游标截断的事件流。 */
  events: Event[];
}

/** 子阶段进度点列的顺序（与 engine 的 election_stage 取值一致）。 */
const STAGES: ElectionStage[] = [
  "candidacy",
  "speech",
  "withdraw",
  "vote",
  "direction",
  "announce",
];

export default function ElectionPanel({ state, events }: ElectionPanelProps): JSX.Element {
  const { votes, tally } = sheriffVoteTally(state, events);
  const current = STAGES.indexOf(state.election_stage as ElectionStage);
  const candidates =
    state.sheriff_candidates.length > 0 ? state.sheriff_candidates : state.sheriff_declared;
  const max = tally.reduce((m, [, n]) => Math.max(m, n), 0);
  const badgeLost = [...events].reverse().find((e) => e.type === "SHERIFF_BADGE_LOST") ?? null;
  const elected = state.sheriff_seat;
  const electedPlayer =
    elected !== null ? state.players.find((p) => p.seat === elected) : undefined;

  return (
    <section className={styles.root}>
      <div className={styles.head}>
        <span className={styles.title}>警长竞选</span>
        <span className={styles.sub}>第 {state.round} 轮</span>
      </div>

      <div className={styles.stages}>
        {STAGES.map((s, i) => {
          const done = current > i || (current === -1 && state.election_stage === "");
          const now = current === i;
          return (
            <div
              key={s}
              className={styles.stageRow}
              data-state={now ? "now" : done ? "done" : "todo"}
            >
              <span className={styles.stageDot} />
              <span>{ELECTION_STAGE_ZH[s]}</span>
            </div>
          );
        })}
      </div>

      {candidates.length > 0 && (
        <>
          <div className={styles.kicker}>上警名单</div>
          <div className={styles.tags}>
            {candidates.map((seat) => {
              const withdrew = state.sheriff_withdrawn.includes(seat);
              const color = seatColor(state, seat);
              return (
                <span
                  key={seat}
                  className={`tag ${withdrew ? styles.tagOut : ""}`}
                  style={
                    withdrew
                      ? undefined
                      : { background: `color-mix(in srgb, ${color} 18%, transparent)`, color }
                  }
                >
                  {seat}号 {seatName(state, seat)}
                  {withdrew ? " · 退水" : ""}
                </span>
              );
            })}
          </div>
        </>
      )}

      {tally.length > 0 && (
        <>
          <div className={styles.kicker}>警下投票 · {Object.keys(votes).length} 票</div>
          <div className={styles.bars}>
            {tally.map(([seat, n]) => {
              const color = seatColor(state, seat);
              return (
                <div className={styles.barRow} key={seat}>
                  <span style={{ color }}>{seat}号</span>
                  <span className={styles.barTrack}>
                    <span
                      className={styles.barFill}
                      style={{ width: `${max > 0 ? (n / max) * 100 : 0}%`, background: color }}
                    />
                  </span>
                  <span className={styles.barNum}>{n}</span>
                </div>
              );
            })}
          </div>
          <div className={styles.voteLines}>
            {Object.entries(votes).map(([voter, target]) => (
              <span key={voter}>
                {voter}号 → {target !== null ? `${target}号` : "弃票"}
              </span>
            ))}
          </div>
        </>
      )}

      {elected !== null && (
        <div className={styles.electedCard}>
          <span
            className={styles.electedDisc}
            style={{
              borderColor: seatColor(state, elected),
              color: seatColor(state, elected),
              background: `color-mix(in srgb, ${seatColor(state, elected)} 22%, transparent)`,
            }}
          >
            {electedPlayer && rolesKnown(state) ? ROLE_ABBR[electedPlayer.role] : "?"}
          </span>
          <div className={styles.electedBody}>
            <span className={styles.electedName}>
              {elected}号 {seatName(state, elected)} <span className={styles.star}>★</span>
            </span>
            <span className={styles.electedSub}>
              当选警长
              {state.sheriff_speech_direction !== null
                ? ` · 发言方向：${DIRECTION_ZH[state.sheriff_speech_direction] ?? state.sheriff_speech_direction}`
                : ""}
            </span>
          </div>
        </div>
      )}

      {state.speech_order.length > 0 && (
        <div className={styles.order}>
          顺序：{state.speech_order.map((s) => `${s}号`).join(" → ")}
        </div>
      )}

      {badgeLost !== null && (
        <>
          <div className={styles.kicker}>警徽流失</div>
          <div className={styles.lostCard}>
            {BADGE_LOST_ZH[(badgeLost.payload as SheriffBadgeLostPayload).reason] ??
              (badgeLost.payload as SheriffBadgeLostPayload).reason}
          </div>
        </>
      )}

      <div className={styles.footer}>【竞选】{ELECTION_STAGE_ZH[state.election_stage]}</div>
    </section>
  );
}
