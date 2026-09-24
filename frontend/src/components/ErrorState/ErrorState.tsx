// 空 / 错误态（设计稿 1i）：4404 对局不存在、4409 等待开局、token 无效、重连中。

import styles from "./ErrorState.module.css";

export type ErrorKind = "4404" | "4409" | "auth" | "reconnecting";

export interface ErrorStateProps {
  kind: ErrorKind;
  /** 轮询 / 重连次数（4409 与 reconnecting 用）。 */
  attempt?: number;
  /** 后端返回的 detail 原文（有则展示）。 */
  detail?: string | null;
}

export default function ErrorState({ kind, attempt, detail }: ErrorStateProps): JSX.Element {
  if (kind === "4409") {
    return (
      <div className={styles.root} role="status">
        <div className={styles.box}>
          <div className={styles.spinner} />
          <span className={styles.code}>4409</span>
          <span className={styles.title}>等待开局</span>
          <span className={styles.desc}>
            对局尚未开始 · 每 2 秒重试{attempt ? ` · 第 ${attempt} 次` : ""}
          </span>
          {detail && <span className={styles.detail}>{detail}</span>}
        </div>
      </div>
    );
  }
  if (kind === "reconnecting") {
    return (
      <div className={styles.root} role="status">
        <div className={styles.box}>
          <div className={styles.spinner} />
          <span className={styles.title}>重连中</span>
          <span className={styles.desc}>
            连接已断开，正在补发事件{attempt ? `（第 ${attempt} 次）` : ""}。指数退避 1s → 8s。
          </span>
          {detail && <span className={styles.detail}>{detail}</span>}
        </div>
      </div>
    );
  }
  if (kind === "auth") {
    return (
      <div className={styles.root} role="alert">
        <div className={styles.box}>
          <span className={styles.code}>4401 / 4403</span>
          <span className={styles.title}>token 无效</span>
          <span className={styles.desc}>该 token 无权观战。请向建局者索取新链接。</span>
          {detail && <span className={styles.detail}>{detail}</span>}
        </div>
      </div>
    );
  }
  return (
    <div className={styles.root} role="alert">
      <div className={styles.box}>
        <span className={styles.code}>4404</span>
        <span className={styles.title}>对局不存在</span>
        <span className={styles.desc}>链接可能已失效，或对局尚未创建。</span>
        {detail && <span className={styles.detail}>{detail}</span>}
        <a className={`btn btn-primary ${styles.back}`} href="#/">
          返回 Lobby
        </a>
      </div>
    </div>
  );
}
