// 右栏 · 投票 / PK（设计稿 1e、1g）：voter → target 列表、实时计票条形、等待名单、结果行。
// 零过滤：票箱与计票由 voteTally(state, events) 纯选择器算出，events 已按回放游标截断。

import { ROLE_ZH } from "../../engine/phases";
import { rolesKnown, voteTally } from "../../engine/select";
import type { Event, GameState, PlayerExiledPayload, VoteResultPayload } from "../../engine/types";
import { seatColor, seatName } from "../seatColor";
import styles from "./VotePanel.module.css";

export interface VotePanelProps {
  state: GameState;
  /** 已按回放游标截断的事件流。 */
  events: Event[];
}

function lastOf(events: readonly Event[], type: string): Event | null {
  for (let i = events.length - 1; i >= 0; i -= 1) {
    const e = events[i] as Event;
    if (e.type === type) return e;
    if (e.type === "VOTE_STARTED") return null; // 本轮投票尚未出结果
  }
  return null;
}

export default function VotePanel({ state, events }: VotePanelProps): JSX.Element {
  const { votes, tally } = voteTally(state, events);
  const pk = state.phase === "VOTE_PK" || state.tie_round > 0;
  const voteWeight =
    typeof state.config.sheriff.vote_weight === "number" ? state.config.sheriff.vote_weight : 1.5;
  const voters = state.players.filter((p) => p.alive && p.can_vote).map((p) => p.seat);
  const waiting = voters.filter((s) => !(s in votes));
  // 分母同 SeatCircle：放逐结算后存活数会小于当时投票人数，取较大值以免出现 8/7。
  const expected = Math.max(voters.length, Object.keys(votes).length);
  const max = tally.reduce((m, [, n]) => Math.max(m, n), 0);
  const result = lastOf(events, "VOTE_RESULT");
  const exiled = lastOf(events, "PLAYER_EXILED");
  const candidates = state.vote_candidates;

  return (
    <section className={styles.root}>
      <div className={styles.head}>
        <span className={styles.title}>
          {pk ? "PK 投票" : "投票"} · 第 {state.round} 轮
        </span>
        {pk ? (
          <span className="tag tag-accent">PK</span>
        ) : (
          <span className={styles.sub}>
            已投 {Object.keys(votes).length}/{expected}
          </span>
        )}
      </div>

      {pk && candidates.length > 0 && (
        <div className={styles.candidates}>
          {candidates.map((seat) => {
            const color = seatColor(state, seat);
            const got = tally.find(([t]) => t === seat)?.[1] ?? 0;
            return (
              <div
                key={seat}
                className={styles.candidate}
                style={{
                  borderColor: color,
                  background: `color-mix(in srgb, ${color} 12%, transparent)`,
                }}
              >
                <span className={styles.candidateKicker}>候选</span>
                <span className={styles.candidateName} style={{ color }}>
                  {seat}号 {seatName(state, seat)}
                </span>
                <span className={styles.candidateVotes}>{got} 票</span>
              </div>
            );
          })}
        </div>
      )}

      <div className={styles.votes}>
        {Object.entries(votes).map(([voterStr, target]) => {
          const voter = Number(voterStr);
          const sheriff = state.players.find((p) => p.seat === voter)?.is_sheriff === true;
          return (
            <div className={styles.voteRow} key={voter}>
              <span style={{ color: seatColor(state, voter) }}>{voter}号</span>
              <span className={styles.arrow}>→</span>
              <span style={{ color: seatColor(state, target) }}>
                {target !== null ? `${target}号 ${seatName(state, target)}` : "弃票"}
              </span>
              <span className={styles.weight}>{sheriff ? `${voteWeight} 票` : ""}</span>
            </div>
          );
        })}
      </div>

      {tally.length > 0 && (
        <>
          <div className={styles.kicker}>
            实时计票{state.sheriff_seat !== null ? `（警长 ${voteWeight} 票）` : ""}
          </div>
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
        </>
      )}

      <div className={styles.footer}>
        {result !== null ? (
          <div className={styles.resultCard}>
            {(() => {
              const vr = result.payload as VoteResultPayload;
              if (vr.exiled !== null) {
                const p = state.players.find((x) => x.seat === vr.exiled);
                return (
                  <>
                    【计票】
                    <span style={{ color: seatColor(state, vr.exiled) }}>
                      {vr.exiled}号
                    </span>
                    得票最高，出局
                    {exiled !== null && (
                      <span className={styles.resultSub}>
                        【放逐】{(exiled.payload as PlayerExiledPayload).seat ?? "无人"}号被票出
                        {p && rolesKnown(state) ? ` · 身份翻牌：${ROLE_ZH[p.role]}` : ""}
                      </span>
                    )}
                  </>
                );
              }
              return <>【计票】平票：{vr.tie_seats.map((s) => `${s}号`).join("、")}</>;
            })()}
          </div>
        ) : waiting.length > 0 ? (
          <span className={styles.waiting}>
            等待 {waiting.map((s) => `${s}号`).join("、")} 投票…
          </span>
        ) : (
          <span className={styles.waiting}>投票已结束，等待计票</span>
        )}
      </div>
    </section>
  );
}
