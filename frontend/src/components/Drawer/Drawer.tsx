// 右侧抽屉（设计稿 2c AgentEditor 620px / 3b ProviderEditor 560px）。
// 只负责壳：遮罩、标题行（标题 + 可选 id tag + ✕）、可滚动主体、底部操作区；Esc 关闭。

import { useEffect, type CSSProperties, type ReactNode } from "react";
import styles from "./Drawer.module.css";

export interface DrawerProps {
  title: string;
  /** 标题右侧的等宽 id 徽标（如 `a_3f9c1e2b`）。 */
  idTag?: string | null;
  width?: number;
  onClose(): void;
  footer: ReactNode;
  children: ReactNode;
}

export default function Drawer({
  title,
  idTag,
  width = 620,
  onClose,
  footer,
  children,
}: DrawerProps): JSX.Element {
  useEffect(() => {
    const onKey = (e: KeyboardEvent): void => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <>
      <div className={styles.backdrop} onClick={onClose} />
      <div
        className={styles.panel}
        style={{ "--drawer-width": `${width}px` } as CSSProperties}
        role="dialog"
        aria-modal="true"
        aria-label={title}
      >
        <div className={styles.head}>
          <span className={styles.title}>{title}</span>
          {idTag && (
            <span className="tag tag-neutral" style={{ fontFamily: "ui-monospace, Menlo, monospace" }}>
              {idTag}
            </span>
          )}
          <button type="button" className={styles.close} onClick={onClose} aria-label="关闭">
            ✕
          </button>
        </div>
        <div className={styles.body}>{children}</div>
        <div className={styles.foot}>{footer}</div>
      </div>
    </>
  );
}
