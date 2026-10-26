// 空 / 错误态（设计稿 1i）：4404 对局不存在、4409 等待开局、token 无效、重连中。

import styles from "./ErrorState.module.css";

export type ErrorKind = "4404" | "4409" | "auth" | "reconnecting" | "error" | "locked";

export interface ErrorStateProps {
  kind: ErrorKind;
  /** 轮询 / 重连次数（4409 与 reconnecting 用）。 */
  attempt?: number;
  /** 后端返回的 detail 原文（有则展示）。 */
  detail?: string | null;
  /** locked 态的「以玩家身份进入」链接。 */
  playerHref?: string;
}

export default function ErrorState({ kind, attempt, detail, playerHref }: ErrorStateProps): JSX.Element {
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
  if (kind === "error") {
    // 兜底错误态：后端 5xx / 网络失败等既不是 404/401/409 的情况，原文展示 detail。
    return (
      <div className={styles.root} role="alert">
        <div className={styles.box}>
          <span className={styles.title}>载入对局失败</span>
          <span className={styles.desc}>请稍后重试；若持续失败请检查服务端状态。</span>
          {detail && <span className={styles.detail}>{detail}</span>}
          <a className={`btn btn-primary ${styles.back}`} href="#/">
            返回 Lobby
          </a>
        </div>
      </div>
    );
  }
  // 注：GamePage 走 spec §7.5 的「重连中在顶栏提示」（PhaseBar.reconnectHint），
  // 目前不会把 kind 置为 "reconnecting"；本分支保留给整页重连提示（设计稿 1i 第三张）。
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
  if (kind === "locked") {
    return (
      <div className={styles.root} role="alert">
        <div className={styles.box}>
          <span className={styles.code}>403</span>
          <span className={styles.title}>上帝视角已封锁</span>
          <span className={styles.desc}>你已入座这局，对局结束前不能查看全局；终局后自动恢复。</span>
          {detail && <span className={styles.detail}>{detail}</span>}
          {playerHref && (
            <a className={`btn btn-primary ${styles.back}`} href={playerHref}>
              以玩家身份进入
            </a>
          )}
        </div>
      </div>
    );
  }
  if (kind === "auth") {
    return (
      <div className={styles.root} role="alert">
        <div className={styles.box}>
          <span className={styles.code}>4401 / 4403</span>
          <span className={styles.title}>需要登录</span>
          <span className={styles.desc}>请登录，或使用建局者提供的分享链接</span>
          {detail && <span className={styles.detail}>{detail}</span>}
          <a className={`btn btn-primary ${styles.back}`} href="#/login">
            去登录
          </a>
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
