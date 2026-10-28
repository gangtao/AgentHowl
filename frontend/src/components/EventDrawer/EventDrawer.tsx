// 事件流抽屉（规格 §4.6，设计稿 3a 右侧 28px 竖向页签）：点页签从右滑出 400px 面板覆盖在右栏上，
// Esc 或再点页签收回。只是壳：内容（SpeechFeed / 窄屏时的 InfoRail）由调用方传入。

import { useEffect, type ReactNode } from "react";
import styles from "./EventDrawer.module.css";

export interface EventDrawerProps {
  open: boolean;
  onToggle(): void;
  /** 竖排页签文案。 */
  tabLabel: string;
  children: ReactNode;
  /** <1100px 时并入抽屉上半部分的内容（右栏信息卡）。 */
  top?: ReactNode;
}

export default function EventDrawer({
  open,
  onToggle,
  tabLabel,
  children,
  top,
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
        <aside id="event-drawer" className={styles.panel} role="complementary" aria-label="事件流">
          {top !== undefined && <div className={styles.top}>{top}</div>}
          <div className={styles.body}>{children}</div>
        </aside>
      )}
    </>
  );
}
