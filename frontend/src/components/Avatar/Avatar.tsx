// 头像（issue #102）：有 id 渲染 <img>（object-fit: cover，失败退占位）；无 id → 名字首字 + 座位色。
// 零过滤：id 来自服务端（档案或 /games/{id}/avatars），组件不做任何判断。

import { useState } from "react";
import { avatarUrl } from "../../api/avatars";
import styles from "./Avatar.module.css";

export interface AvatarProps {
  avatar: string | null;
  name: string;
  seat: number | null;
  size: number;
  /** 占位底色（CSS 颜色/变量）；缺省按座位号取一组柔和色。 */
  color?: string;
}

const PALETTE = ["#6c8cff", "#ff8c6c", "#5fbf8f", "#d98cff", "#ffc44d", "#4dc9d9", "#ff6ca8", "#8fa3b8"];

function placeholderText(name: string, seat: number | null): string {
  const t = name.trim();
  if (t !== "") return Array.from(t)[0] as string;
  return seat === null ? "?" : String(seat);
}

export default function Avatar({ avatar, name, seat, size, color }: AvatarProps): JSX.Element {
  const [broken, setBroken] = useState(false);
  const dim = { width: size, height: size, fontSize: Math.round(size * 0.42) };
  if (avatar !== null && !broken) {
    return (
      <img
        className={styles.img}
        style={dim}
        src={avatarUrl(avatar)}
        alt={name || (seat !== null ? `${seat}号` : "头像")}
        onError={() => setBroken(true)}
      />
    );
  }
  const bg = color ?? PALETTE[seat === null ? 7 : seat % PALETTE.length];
  return (
    <span className={styles.placeholder} style={{ ...dim, background: bg }} aria-hidden="true">
      {placeholderText(name, seat)}
    </span>
  );
}
