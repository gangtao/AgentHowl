// 窄屏抽屉（<1100px，规格 2026-10-28-speech-stage §3 / R3）：右栏隐藏时，舞台最右 28px 竖向页签从右滑出
// 400px 面板放同一份右栏（发言台 / 信息卡 + 对局记录）；宽屏由 CSS 整体隐藏。Esc 或再点页签收回。只是壳。

import { useEffect, type ReactNode } from "react";
import styles from "./EventDrawer.module.css";

export interface EventDrawerProps {
  open: boolean;
  onToggle(): void;
  /** 竖排页签文案。 */
  tabLabel: string;
  children: ReactNode;
}

export default function EventDrawer({
  open,
  onToggle,
  tabLabel,
  children,
}: EventDrawerProps): JSX.Element {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent): void => {
      if (e.key === "Escape") onToggle();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onToggle]);

  return (
    <>
      <button
        type="button"
        className={styles.tab}
        aria-expanded={open}
        aria-controls="event-drawer"
        onClick={onToggle}
      >
        {tabLabel} {open ? "◂" : "▸"}
      </button>
      {open && (
        <aside id="event-drawer" className={styles.panel} role="complementary" aria-label="发言台与对局记录">
          <div className={styles.body}>{children}</div>
        </aside>
      )}
    </>
  );
}
