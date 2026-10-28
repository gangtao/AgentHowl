// SkillPicker「二 · 技艺」（规格 §6，设计稿 4e）：GET /skills 的两列羊皮纸技能卡 + 「全部（*）」开关；
// 选中卡 ■ + 篝火描边。
// 注意：SkillInfo.roles 为空数组 = 适用全部角色（后端口径），不是「无角色」。

import type { SkillInfo } from "../../api/agents";
import { ROLE_ZH } from "../../engine/phases";
import type { RoleType } from "../../engine/types";
import styles from "./SkillPicker.module.css";

export interface SkillPickerProps {
  skills: SkillInfo[];
  /** 已选技能名；`["*"]` = 全部。 */
  value: string[];
  onChange(next: string[]): void;
}

function rolesLabel(roles: string[]): string {
  if (roles.length === 0) return "全部角色";
  return roles.map((r) => ROLE_ZH[r as RoleType] ?? r).join(" / ");
}

export default function SkillPicker({ skills, value, onChange }: SkillPickerProps): JSX.Element {
  const all = value.includes("*");
  const selected = new Set(value);

  function toggle(name: string): void {
    const next = new Set(selected);
    next.delete("*");
    if (next.has(name)) next.delete(name);
    else next.add(name);
    onChange([...next]);
  }

  return (
    <div className={styles.root}>
      <div className={styles.head}>
        <span className={styles.kicker}>二 · 技艺 · 已选 {all ? skills.length : value.length}</span>
        <label className={styles.allToggle}>
          全部（*）
          <input
            type="checkbox"
            checked={all}
            aria-label="全部技能"
            onChange={(e) => onChange(e.target.checked ? ["*"] : [])}
          />
        </label>
      </div>
      {skills.length === 0 ? (
        <span className={styles.empty}>没有可用技能（GET /skills 为空）。</span>
      ) : (
        <div className={styles.grid}>
          {skills.map((s) => {
            const checked = all || selected.has(s.name);
            return (
              <label
                key={s.name}
                className={`${styles.item} ${checked ? styles.itemOn : ""}`}
                title={s.description}
              >
                <input
                  type="checkbox"
                  className={styles.box}
                  checked={checked}
                  disabled={all}
                  onChange={() => toggle(s.name)}
                />
                <span className={styles.mark} aria-hidden="true">
                  {checked ? "■" : "□"}
                </span>
                <span className={styles.itemText}>
                  <span className={styles.name}>{s.name}</span>
                  <span className={styles.desc}>
                    {s.description} · {rolesLabel(s.roles)}
                    {s.phases.length > 0 ? ` · ${s.phases.join(" / ")}` : ""}
                  </span>
                </span>
              </label>
            );
          })}
        </div>
      )}
    </div>
  );
}
