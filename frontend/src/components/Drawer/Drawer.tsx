// 右侧抽屉（设计稿 4e「招募告示」羊皮纸抽屉 / 木牌变体）。
// 只负责壳：遮罩、左侧木轴、标题行（kicker + 标题 + 可选 id 签 + ✕）、可滚动主体、底部操作区；Esc 关闭。
// tone="parch"（缺省）时根节点带全局类 .ah-parch，内部 .input 自动换浅底。

import { useEffect, type CSSProperties, type ReactNode } from "react";
import styles from "./Drawer.module.css";

export type DrawerTone = "wood" | "parch";

export interface DrawerProps {
  title: string;
  /** 标题上方的小字眉题，如「招 募 告 示」。 */
  kicker?: string;
  /** 标题右侧的等宽 id 签（如 `a_3f9c1e2b`）。 */
  idTag?: string | null;
  /** 羊皮纸（缺省）或木牌。 */
  tone?: DrawerTone;
  width?: number;
  onClose(): void;
  footer: ReactNode;
  children: ReactNode;
}

export default function Drawer({
  title,
  kicker,
  idTag,
  tone = "parch",
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
        className={`${styles.panel} ${tone === "parch" ? "ah-parch" : ""}`}
        data-tone={tone}
        style={{ "--drawer-width": `${width}px` } as CSSProperties}
        role="dialog"
        aria-modal="true"
        aria-label={title}
      >
        <span className={styles.spine} aria-hidden="true" />
        <div className={styles.head}>
          <div className={styles.heading}>
            {kicker && <span className={styles.kicker}>{kicker}</span>}
            <span className={styles.title}>
              {title}
              {idTag && <span className={styles.idTag}>{idTag}</span>}
            </span>
          </div>
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
