// 夜晚流程（设计稿 5a 右栏）：按 config.night_order 列出各角色「已行动 / 行动中 / 待行动」；
// 折叠夜晚 NIGHT（观众 / 玩家视角）看不到子阶段，全部写「进行中」。

import { ROLE_ZH } from "../../engine/phases";
import type { GameState, Phase, RoleType } from "../../engine/types";
import styles from "./InfoRail.module.css";

const PHASE_OF: Partial<Record<RoleType, Phase>> = {
  GUARD: "NIGHT_GUARD",
  WEREWOLF: "NIGHT_WEREWOLF",
  WITCH: "NIGHT_WITCH",
  SEER: "NIGHT_SEER",
  HUNTER: "NIGHT_HUNTER_CONFIRM",
};

const FALLBACK_ORDER: RoleType[] = ["GUARD", "WEREWOLF", "WITCH", "SEER", "HUNTER"];

function nightOrder(state: GameState): RoleType[] {
  const raw = state.config.night_order;
  if (Array.isArray(raw) && raw.every((r) => typeof r === "string" && r in PHASE_OF)) {
    return raw as RoleType[];
  }
  const present = new Set(state.config.roles.map((r) => r.role));
  return FALLBACK_ORDER.filter((r) => present.has(r));
}

export function NightFlow({ state }: { state: GameState }): JSX.Element {
  const order = nightOrder(state);
  const folded = state.phase === "NIGHT";
  const idx = order.findIndex((r) => PHASE_OF[r] === state.phase);
  return (
    <section className="ah-panel">
      <div className="ah-panel-head">
        <h3 className={styles.title}>夜晚流程</h3>
        <span>第 {state.round} 夜</span>
      </div>
      {order.map((r, i) => {
        const status = folded
          ? "进行中"
          : idx === -1
            ? "待行动"
            : i < idx
              ? "已行动"
              : i === idx
                ? "行动中"
                : "待行动";
        const now = !folded && i === idx;
        return (
          <div
            key={r}
            className={styles.flowRow}
            data-status={status}
            data-now={now ? "true" : undefined}
          >
            {now ? "◉" : status === "已行动" ? "●" : "○"} {ROLE_ZH[r]} · {status}
          </div>
        );
      })}
    </section>
  );
}
