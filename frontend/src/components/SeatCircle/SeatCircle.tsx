// 座位环（设计稿 1c/1d/1g/1h）：0 号在顶部顺时针，坐标 50 + 41·cos/sin(-90° + i·360°/n)。
// 零过滤：角色牌是否翻面完全由 state 决定（是否已应用 ROLES_ASSIGNED），与 viewer 无关——
// 观众的 state 通常没有角色，所以自然显示 ?；终局回放里服务端把全量事件也发给观众，就照实翻牌。

import { ROLE_ABBR, factionColorVar } from "../../engine/phases";
import { aliveSeats, rolesKnown, wolfSeats } from "../../engine/select";
import type { NightLink } from "../../engine/select";
import type { GameState } from "../../engine/types";
import styles from "./SeatCircle.module.css";

export interface SeatCircleProps {
  state: GameState;
  /** 当前发言座位（无则 null）。 */
  speaking: number | null;
  /** 座位 → 当前得票数（空对象即不显示票数小标）。 */
  votes: Record<number, number>;
  /** 夜间连线（观众流没有夜间事件，自然为空）。 */
  nightLines: NightLink[];
}

interface SeatPos {
  seat: number;
  x: number;
  y: number;
}

function positions(seats: number[]): SeatPos[] {
  const n = seats.length;
  return seats.map((seat, i) => {
    const a = ((-90 + (i * 360) / n) * Math.PI) / 180;
    return {
      seat,
      x: +(50 + 41 * Math.cos(a)).toFixed(2),
      y: +(50 + 41 * Math.sin(a)).toFixed(2),
    };
  });
}

export default function SeatCircle({
  state,
  speaking,
  votes,
  nightLines,
}: SeatCircleProps): JSX.Element {
  const players = [...state.players].sort((a, b) => a.seat - b.seat);
  const pos = positions(players.map((p) => p.seat));
  const posOf = new Map(pos.map((p) => [p.seat, p]));
  const known = rolesKnown(state);
  const alive = aliveSeats(state).length;
  const wolves = wolfSeats(state).length;
  // 分母取「当前有投票权的存活者」与「已投票数」的较大值：放逐已结算时存活数会小于
  // 当时投票的人数，直接用存活数会出现 8/7 这种读不通的分母。
  const aliveVoters = state.players.filter((p) => p.alive && p.can_vote).length;
  // 已投人数取自 state 的票箱（voter → target），而不是 votes（target → 票数）——
  // 后者的键数是「被投的人数」，拿来当已投人数会算错。
  const voteBox =
    state.phase === "SHERIFF_ELECTION" || state.phase === "SHERIFF_PK"
      ? state.sheriff_votes
      : state.votes;
  const castCount = Object.keys(voteBox).length;
  const voters = Math.max(aliveVoters, castCount);

  const center =
    speaking !== null
      ? { label: "发言中", value: `${speaking}号` }
      : Object.keys(votes).length > 0
        ? { label: "投票中", value: `${castCount}/${voters}` }
        : null;

  return (
    <div className={styles.root}>
      <div className={styles.circle}>
        {nightLines.length > 0 && (
          <svg
            className={styles.lines}
            viewBox="0 0 100 100"
            preserveAspectRatio="none"
            aria-hidden="true"
          >
            {nightLines.map((l, i) => {
              const a = posOf.get(l.from);
              const b = posOf.get(l.to);
              if (!a || !b) return null;
              return (
                <line
                  key={`${l.from}-${l.to}-${i}`}
                  x1={a.x}
                  y1={a.y}
                  x2={b.x}
                  y2={b.y}
                  stroke={`var(${l.color})`}
                  strokeWidth={0.9}
                  strokeDasharray={l.dashed ? "2 1.6" : undefined}
                  strokeLinecap="round"
                  opacity={0.9}
                />
              );
            })}
          </svg>
        )}
        {players.map((p) => {
          const at = posOf.get(p.seat) as SeatPos;
          const colorVar = known ? factionColorVar(p.role) : null;
          const color = colorVar !== null ? `var(${colorVar})` : "var(--color-neutral-500)";
          const abbr = known ? ROLE_ABBR[p.role] : "?";
          const isSpeaking = speaking === p.seat;
          const n = votes[p.seat];
          return (
            <div
              key={p.seat}
              className={styles.seat}
              style={{
                left: `${at.x}%`,
                top: `${at.y}%`,
                opacity: p.alive ? 1 : 0.42,
              }}
              aria-label={`${p.seat}号 ${p.display_name} ${p.alive ? "存活" : "出局"}${
                p.is_sheriff ? " 警长" : ""
              }`}
              {...(isSpeaking ? { "data-speaking": "true" } : {})}
            >
              <div
                className={`${styles.disc} ${isSpeaking ? styles.speaking : ""}`}
                style={{
                  borderColor: color,
                  color,
                  background: known
                    ? `color-mix(in srgb, ${color} 22%, transparent)`
                    : "var(--color-surface)",
                }}
              >
                <span className={styles.abbr}>{abbr}</span>
                {p.is_sheriff && (
                  <span className={styles.badge} title="警长">
                    ★
                  </span>
                )}
                {p.idiot_revealed && <span className={styles.idiot}>痴</span>}
                {!p.alive && <span className={styles.dead}>✕</span>}
                {n !== undefined && n > 0 && <span className={styles.votes}>{n}</span>}
              </div>
              <span className={styles.name}>
                {p.seat}号 {p.display_name}
              </span>
            </div>
          );
        })}
        {center !== null && (
          <div className={styles.center}>
            <span className={styles.centerLabel}>{center.label}</span>
            <span className={styles.centerValue}>{center.value}</span>
          </div>
        )}
      </div>

      {nightLines.length > 0 ? (
        <div className={styles.legend}>
          <span className={styles.legendItem}>
            <span className={styles.lineWolf} />
            狼刀
          </span>
          <span className={styles.legendItem}>
            <span className={styles.lineGuard} />
            守护
          </span>
          <span className={styles.legendItem}>
            <span className={styles.lineSave} />
            解药
          </span>
          <span className={styles.legendItem}>
            <span className={styles.linePoison} />
            毒药
          </span>
          <span className={styles.legendItem}>
            <span className={styles.lineSeer} />
            查验
          </span>
        </div>
      ) : (
        <div className={styles.legend}>
          {known && (
            <>
              <span className={styles.legendItem}>
                <span className={styles.dotWolf} />
                狼人
              </span>
              <span className={styles.legendItem}>
                <span className={styles.dotGod} />
                神职
              </span>
              <span className={styles.legendItem}>
                <span className={styles.dotVillager} />
                村民
              </span>
            </>
          )}
          <span className={styles.legendItem}>
            <span className={styles.star}>★</span>警长
          </span>
          <span className={styles.legendItem}>
            <span className={styles.dotSpeaking} />
            当前发言
          </span>
        </div>
      )}

      <div className={styles.cards}>
        <div className={`card ${styles.statCard}`}>
          <span>存活</span>
          <span className={styles.statValue}>
            {alive}
            <span className={styles.statSub}>/{players.length}</span>
          </span>
        </div>
        {known && (
          <div className={`card ${styles.statCard}`}>
            <span>狼 / 好人</span>
            <span className={styles.statValue}>
              <span className={styles.wolfNum}>{wolves}</span> / {players.length - wolves}
            </span>
          </div>
        )}
        <div className={`card ${styles.statCard}`}>
          <span>警长</span>
          <span className={styles.statValue}>
            {state.sheriff_seat !== null ? `${state.sheriff_seat}号` : "无"}
          </span>
        </div>
      </div>
    </div>
  );
}
