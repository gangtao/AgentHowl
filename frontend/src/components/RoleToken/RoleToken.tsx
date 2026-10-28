// 角色徽记（规格 §2.4，设计稿 2a）：座位 / 身份牌 / 羊皮纸 / 描边四种变体 × 已知 / 未知 / 出局三种态。
// 零过滤：传什么渲染什么——该不该露身份由调用方（最终由服务端给的 state）决定，组件不判断。

import { useState, type CSSProperties } from "react";
import { avatarUrl } from "../../api/avatars";
import { ROLE_ZH } from "../../engine/phases";
import type { RoleType } from "../../engine/types";
import { CAMP_VARS, ROLE_ICON_PATH, roleCamp } from "../../lib/roleIcons";
import styles from "./RoleToken.module.css";

export type RoleTokenState = "known" | "unknown" | "dead";
export type RoleTokenVariant = "seat" | "card" | "parch" | "outline";

export interface RoleTokenProps {
  /** known 时必有；null 一律按 unknown 渲染。 */
  role: RoleType | null;
  /** 缺省：role === null ? "unknown" : "known"。 */
  state?: RoleTokenState;
  /** 缺省 "seat"。 */
  variant?: RoleTokenVariant;
  /** seat / parch / outline 为直径；card 为宽，高 = size × 4 / 3。 */
  size: number;
  /** unknown 时显示的首字；缺省「?」。 */
  initial?: string;
  /** 头像 id；known / unknown 且非 dead 时圆内渲染图片，徽记缩成右下角小章。 */
  avatar?: string | null;
  className?: string;
  style?: CSSProperties;
}

function Icon({ role, px }: { role: RoleType; px: number }): JSX.Element {
  return (
    <svg viewBox="0 0 24 24" width={px} height={px} aria-hidden="true" className={styles.icon}>
      <path d={ROLE_ICON_PATH[role]} fill="currentColor" fillRule="evenodd" />
    </svg>
  );
}

export default function RoleToken({
  role,
  state,
  variant = "seat",
  size,
  initial,
  avatar = null,
  className,
  style,
}: RoleTokenProps): JSX.Element {
  const [broken, setBroken] = useState(false);
  const resolved: RoleTokenState = state ?? (role === null ? "unknown" : "known");
  const known = resolved === "known" && role !== null;
  const camp = known ? roleCamp(role) : null;
  const vars = camp === null ? null : CAMP_VARS[camp];

  const label = resolved === "dead" ? "已出局" : known ? ROLE_ZH[role] : "身份未知";
  const height = variant === "card" ? Math.round((size * 4) / 3) : size;
  const iconPx = Math.round(size * (variant === "card" ? 0.48 : 0.5));
  const showAvatar = avatar !== null && avatar !== "" && !broken && resolved !== "dead";

  const cssVars: Record<string, string> = {};
  if (vars !== null) {
    cssVars["--rt-ring"] = vars.ring;
    cssVars["--rt-hi"] = vars.hi;
    cssVars["--rt-lo"] = vars.lo;
    cssVars["--rt-fg"] = vars.fg;
  }

  let body: JSX.Element;
  if (resolved === "dead") {
    body = <span className={styles.glyph}>✕</span>;
  } else if (showAvatar) {
    body = (
      <>
        <img className={styles.avatar} src={avatarUrl(avatar)} alt="" onError={() => setBroken(true)} />
        {known && (
          <span className={styles.stamp} aria-hidden="true">
            <Icon role={role} px={Math.round(size * 0.3 * 0.6)} />
          </span>
        )}
      </>
    );
  } else if (known) {
    body = <Icon role={role} px={iconPx} />;
  } else {
    body = <span className={styles.glyph}>{initial && initial !== "" ? initial : "?"}</span>;
  }

  return (
    <span
      role="img"
      aria-label={label}
      data-variant={variant}
      data-state={resolved}
      {...(camp !== null ? { "data-camp": camp } : {})}
      className={`${styles.root} ${className ?? ""}`}
      style={{
        ...(cssVars as CSSProperties),
        width: size,
        height,
        fontSize: Math.round(size * 0.42),
        ...style,
      }}
    >
      {body}
    </span>
  );
}
