// 身份牌（规格 §4.7，设计稿 3a HUD 左栏）：84×112 角色卡 + 「N号 · 名字」+ 角色名 + 说明行。
// 说明行由 src/lib/identityLines.ts 生成；这里只渲染。

import { ROLE_ZH } from "../../engine/phases";
import type { RoleType } from "../../engine/types";
import RoleToken from "../RoleToken/RoleToken";
import styles from "./IdentityCard.module.css";

export interface IdentityCardProps {
  seat: number;
  name: string;
  role: RoleType | null;
  alive: boolean;
  avatar?: string | null;
  lines: string[];
}

export default function IdentityCard({
  seat,
  name,
  role,
  alive,
  avatar = null,
  lines,
}: IdentityCardProps): JSX.Element {
  const title = !alive ? "已出局" : role === null ? "身份未知" : ROLE_ZH[role];
  return (
    <div className={styles.root} data-alive={alive ? "true" : "false"}>
      <RoleToken
        role={role}
        state={alive ? undefined : "dead"}
        variant="card"
        size={84}
        initial={name.slice(0, 1)}
        avatar={avatar}
      />
      <div className={styles.text}>
        <div className={styles.who}>
          {seat}号 · {name}
        </div>
        <div className={styles.role} data-dead={alive ? undefined : "true"}>
          {title}
        </div>
        {lines.map((l) => (
          <div key={l} className={styles.line}>
            {l}
          </div>
        ))}
      </div>
    </div>
  );
}
