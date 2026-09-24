// 确认框（设计稿 2d 删除确认 / 3d 删除被引用只读版）。用 tokens.css 的 .dialog 全局类。

import type { ReactNode } from "react";
import styles from "./ConfirmDialog.module.css";

export interface ConfirmDialogProps {
  title: string;
  body: ReactNode;
  confirmLabel?: string;
  cancelLabel?: string;
  /** 只读版（如 409 提示）：不显示取消，确认按钮即「知道了」。 */
  readOnly?: boolean;
  danger?: boolean;
  onConfirm(): void;
  onCancel(): void;
}

export default function ConfirmDialog({
  title,
  body,
  confirmLabel = "删除",
  cancelLabel = "取消",
  readOnly = false,
  danger = false,
  onConfirm,
  onCancel,
}: ConfirmDialogProps): JSX.Element {
  return (
    <div className="dialog-backdrop" style={{ zIndex: 60 }} onClick={onCancel}>
      <div
        className="dialog"
        role="alertdialog"
        aria-label={title}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="dialog-title" style={{ fontSize: 17 }}>
          {title}
        </div>
        <div className="dialog-body">{body}</div>
        <div className="dialog-actions">
          {!readOnly && (
            <button type="button" className="btn btn-ghost" onClick={onCancel}>
              {cancelLabel}
            </button>
          )}
          <button
            type="button"
            className={`btn btn-primary ${danger ? styles.danger : ""}`}
            onClick={onConfirm}
          >
            {readOnly ? "知道了" : confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
