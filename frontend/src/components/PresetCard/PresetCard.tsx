// PresetCard（规格 §5 第 1 步，设计稿 1c）：羊皮纸剧本牌——标题 + 木签「N 人 / 带警长」+ 胜利条件 +
// 角色徽记一行（按 roles 展开）+ mono preset id。选中态 3px 篝火描边。

import type { PresetInfo } from "../../api/agents";
import { ROLE_ZH } from "../../engine/phases";
import type { RoleType } from "../../engine/types";
import { presetTag } from "../../lib/lobbyText";
import RoleToken from "../RoleToken/RoleToken";
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
  const tokens: RoleType[] = [];
  for (const r of preset.roles) {
    for (let i = 0; i < r.count; i += 1) tokens.push(r.role as RoleType);
  }
  return (
    <button
      type="button"
      className={`ah-parch ${styles.card}`}
      aria-pressed={selected}
      data-selected={selected ? "true" : undefined}
      onClick={onSelect}
    >
      <div className={styles.head}>
        <h4 className={styles.title}>{preset.description_zh}</h4>
        <span className={`tag tag-wood ${styles.tag}`}>
          {presetTag(preset.num_players, preset.sheriff)}
        </span>
      </div>
      <div className={styles.sub}>{WIN_ZH[preset.win_condition] ?? preset.win_condition}</div>
      <div className={styles.tokens}>
        {tokens.map((role, i) => (
          <span key={`${role}-${i}`} title={ROLE_ZH[role] ?? role} className={styles.token}>
            <RoleToken role={role} variant="parch" size={28} />
          </span>
        ))}
      </div>
      <span className={styles.id}>{preset.name}</span>
    </button>
  );
}
