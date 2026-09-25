// ShareDialog（设计稿 1b）：建局成功后的 GM / 观众链接 + 复制 + 安全提示。
// token 只存在于链接里（src/api/tokens.ts 的约定：不写 localStorage）。

import { useState } from "react";
import styles from "./ShareDialog.module.css";

export interface ShareDialogProps {
  gameId: string;
  gmToken: string;
  spectatorToken: string | null;
  onEnter(): void;
  onLater(): void;
}

function linkFor(gameId: string, param: "gm" | "spec", token: string): string {
  const base = typeof window === "undefined" ? "" : window.location.origin + window.location.pathname;
  return `${base}#/g/${gameId}?${param}=${token}`;
}

export default function ShareDialog({
  gameId,
  gmToken,
  spectatorToken,
  onEnter,
  onLater,
}: ShareDialogProps): JSX.Element {
  const [copied, setCopied] = useState<string | null>(null);

  async function copy(key: string, text: string): Promise<void> {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(key);
    } catch {
      // 无剪贴板权限（http 非 localhost / 测试环境）：链接本就可见可手选，不当作错误
      setCopied(null);
    }
  }

  const gmLink = linkFor(gameId, "gm", gmToken);
  const specLink = spectatorToken === null ? null : linkFor(gameId, "spec", spectatorToken);

  return (
    <div className="dialog-backdrop" style={{ zIndex: 60 }}>
      <div className="dialog" role="dialog" aria-modal="true" aria-label="对局已创建">
        <div className="dialog-title">对局已创建</div>
        <div className="dialog-body" style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          <div className="field">
            <label htmlFor="share-gm">上帝视角链接 · GM</label>
            <div className={styles.row}>
              <input id="share-gm" className={`input ${styles.mono}`} readOnly value={gmLink} />
              <button type="button" className="btn btn-secondary" onClick={() => void copy("gm", gmLink)}>
                {copied === "gm" ? "已复制" : "复制"}
              </button>
            </div>
          </div>
          {specLink !== null && (
            <div className="field">
              <label htmlFor="share-spec">观众链接 · 仅公开信息</label>
              <div className={styles.row}>
                <input id="share-spec" className={`input ${styles.mono}`} readOnly value={specLink} />
                <button
                  type="button"
                  className="btn btn-secondary"
                  onClick={() => void copy("spec", specLink)}
                >
                  {copied === "spec" ? "已复制" : "复制"}
                </button>
              </div>
            </div>
          )}
          <div className={styles.warn}>
            <span>⚠</span>
            <span>
              上帝视角链接含全部身份信息，勿分享给玩家。token 只存在于链接中，关闭页面后需重新打开链接。
            </span>
          </div>
        </div>
        <div className="dialog-actions">
          <button type="button" className="btn btn-ghost" onClick={onLater}>
            稍后
          </button>
          <button type="button" className="btn btn-primary" onClick={onEnter}>
            进入上帝视角 →
          </button>
        </div>
      </div>
    </div>
  );
}
