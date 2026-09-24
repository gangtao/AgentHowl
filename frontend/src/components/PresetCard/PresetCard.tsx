// PresetCard（设计稿 2d 步骤 1）：板子名 + 胜利条件 tag + 角色圆点组 + config_id。

import type { PresetInfo } from "../../api/agents";
import { ROLE_ABBR, ROLE_ZH, factionColorVar } from "../../engine/phases";
import type { RoleType } from "../../engine/types";
import styles from "./PresetCard.module.css";

export interface PresetCardProps {
  preset: PresetInfo;
  selected: boolean;
  onSelect(): void;
}

const WIN_ZH: Record<string, string> = {
  KILL_SIDE: "屠边",
  KILL_ALL: "屠城",
};

export default function PresetCard({ preset, selected, onSelect }: PresetCardProps): JSX.Element {
  const dots: RoleType[] = [];
  for (const r of preset.roles) {
    for (let i = 0; i < r.count; i += 1) dots.push(r.role as RoleType);
  }
  return (
    <button
      type="button"
      className={`card ${styles.card} ${selected ? styles.selected : ""}`}
      aria-pressed={selected}
      onClick={onSelect}
    >
      <div className={styles.head}>
        <span className={styles.title}>{preset.description_zh}</span>
        <span className="tag tag-neutral" style={{ fontSize: 10 }}>
          {WIN_ZH[preset.win_condition] ?? preset.win_condition}
          {preset.sheriff ? " · 警长" : ""}
        </span>
      </div>
      <div className={styles.foot}>
        <div className={styles.dots}>
          {dots.map((role, i) => (
            <span
              key={`${role}-${i}`}
              className={styles.dot}
              title={ROLE_ZH[role] ?? role}
              style={{
                borderColor: `var(${factionColorVar(role)})`,
                color: `var(${factionColorVar(role)})`,
                background: `color-mix(in srgb, var(${factionColorVar(role)}) 22%, transparent)`,
              }}
            >
              {ROLE_ABBR[role] ?? "?"}
            </span>
          ))}
        </div>
        <span className={styles.id}>{preset.name}</span>
      </div>
    </button>
  );
}
