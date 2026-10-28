// 终局结算（规格 §4.8，设计稿 1i「血月 · 身份揭晓」）：覆盖舞台；按胜方切血月 / 金月；揭晓网格只渲染
// state 里有角色的座位（观众直播尾声拿不到角色就是「?」，回放装入后自然翻牌——零过滤）。

import { ROLE_ZH, WINNER_ZH } from "../../engine/phases";
import { rolesKnown } from "../../engine/select";
import type { Event, GameState, RoleType } from "../../engine/types";
import { fateOf } from "../../lib/village";
import RoleToken from "../RoleToken/RoleToken";
import styles from "./GameOverScreen.module.css";

export interface GameOverScreenProps {
  state: GameState;
  events: readonly Event[];
  /** 事件总数（最后一条 seq）。 */
  total: number;
  /** 服务端观察给出的角色覆盖层。 */
  knownRoles?: Record<number, RoleType>;
  /** 「查看全局回放」；缺省不渲染该按钮。 */
  onReplay?(): void;
}

function roleColorVar(role: RoleType | null): string {
  if (role === "WEREWOLF") return "var(--ah-wolf)";
  if (role === "VILLAGER") return "var(--ah-villager)";
  if (role === null) return "var(--ah-text-muted)";
  return "var(--ah-god)";
}

export default function GameOverScreen({
  state,
  events,
  total,
  knownRoles = {},
  onReplay,
}: GameOverScreenProps): JSX.Element {
  const winner = state.winner;
  const winnerKey = winner === null ? "TIE" : winner;
  const headline = winner === null ? "平局" : `${WINNER_ZH[winner] ?? winner}胜`;
  const cfg = state.config as Record<string, unknown>;
  const how =
    winner === "WOLF"
      ? cfg.win_condition === "kill_all"
        ? "屠城成功"
        : "屠边成功"
      : winner === "GOOD"
        ? "狼人出清"
        : "无人胜出";
  const allKnown = rolesKnown(state);
  const players = [...state.players].sort((a, b) => a.seat - b.seat);

  return (
    <section className={styles.root} data-winner={winnerKey} role="region" aria-label="游戏结束">
      <div className={styles.moon} aria-hidden="true" />
      <div className={styles.head}>
        <div className={styles.kicker}>第 {state.round} 轮 · 游 戏 结 束</div>
        <h1 className={styles.headline}>{headline}</h1>
        <div className={styles.sub}>
          {winner ?? "TIE"} · {how} · {total} 条事件
        </div>
      </div>
      <div
        className={styles.grid}
        style={{ "--cols": Math.min(players.length, 9) } as React.CSSProperties}
      >
        {players.map((p) => {
          const role: RoleType | null = allKnown ? p.role : (knownRoles[p.seat] ?? null);
          return (
            <div key={p.seat} className={styles.cell} data-alive={p.alive ? "true" : "false"}>
              <RoleToken role={role} size={52} initial={p.display_name.slice(0, 1)} />
              <div className={styles.cellName}>
                {p.seat} {p.display_name}
              </div>
              <div className={styles.cellRole} style={{ color: roleColorVar(role) }}>
                {role === null ? "身份未知" : ROLE_ZH[role]}
              </div>
              <div className={styles.cellFate}>{fateOf(p.seat, events, state)}</div>
            </div>
          );
        })}
      </div>
      <div className={styles.actions}>
        {onReplay !== undefined && (
          <button type="button" className="btn btn-primary" onClick={onReplay}>
            查看全局回放
          </button>
        )}
        <a className="btn btn-secondary" href="#/">
          再来一局
        </a>
        <a className="btn btn-ghost" href="#/history">
          回到历史对局
        </a>
      </div>
    </section>
  );
}
