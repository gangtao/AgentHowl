// 空 / 错误态（设计稿 4f「这局已随风散去 / 村口有人守着」）：4404 对局不存在、4409 等待开局、
// auth 需要登录、locked 上帝视角封锁、reconnecting 重连中、error 兜底。六种 kind 共用一个壳。

import type { ReactNode } from "react";
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
  /** 已登录（issue #170）：auth 态不再指向登录页（登录页会回跳到本页原地循环），改为回到村志。 */
  authed?: boolean;
}

type Art = "moon" | "card" | "fire";

interface ShellProps {
  role: "alert" | "status";
  art: Art;
  /** 木牌「?」/「!」卡上的字。 */
  glyph?: string;
  code: string | null;
  title: string;
  desc: ReactNode;
  detail: string | null | undefined;
  action: ReactNode;
}

function Shell({ role, art, glyph, code, title, desc, detail, action }: ShellProps): JSX.Element {
  return (
    <div className={styles.root} role={role}>
      <div className={styles.box}>
        {art === "moon" && <div className={styles.artMoon} aria-hidden="true" />}
        {art === "card" && (
          <div className={styles.artCard} aria-hidden="true">
            {glyph ?? "?"}
          </div>
        )}
        {art === "fire" && <div className={styles.artFire} aria-hidden="true" />}
        {code !== null && <span className={styles.code}>{code}</span>}
        <span className={styles.title}>{title}</span>
        <span className={styles.desc}>{desc}</span>
        {detail && <span className={styles.detail}>{detail}</span>}
        {action}
      </div>
    </div>
  );
}

export default function ErrorState({
  kind,
  attempt,
  detail,
  playerHref,
  authed = false,
}: ErrorStateProps): JSX.Element {
  if (kind === "4409") {
    return (
      <Shell
        role="status"
        art="fire"
        code="4409"
        title="篝火未燃 · 等待开局"
        desc={<>对局尚未开始 · 每 2 秒重试{attempt ? ` · 第 ${attempt} 次` : ""}</>}
        detail={detail}
        action={null}
      />
    );
  }
  if (kind === "reconnecting") {
    // 注：GamePage 走 spec §7.5 的「重连中在顶栏提示」（PhaseBar.reconnectHint），目前不会把 kind
    // 置为 "reconnecting"；本分支保留给整页重连提示。
    return (
      <Shell
        role="status"
        art="fire"
        code={null}
        title="重连中"
        desc={
          <>连接已断开，正在补发事件{attempt ? `（第 ${attempt} 次）` : ""}。指数退避 1s → 8s。</>
        }
        detail={detail}
        action={null}
      />
    );
  }
  if (kind === "error") {
    // 兜底错误态：后端 5xx / 网络失败等既不是 404/401/409 的情况，原文展示 detail。
    return (
      <Shell
        role="alert"
        art="card"
        glyph="!"
        code={null}
        title="载入对局失败"
        desc="请稍后重试；若持续失败请检查服务端状态。"
        detail={detail}
        action={
          <a className={`btn btn-secondary ${styles.action}`} href="#/history">
            回到村志
          </a>
        }
      />
    );
  }
  if (kind === "locked") {
    return (
      <Shell
        role="alert"
        art="card"
        code="403"
        title="你还坐在桌上"
        desc="你已入座这局，对局结束前不能查看全局；终局后自动恢复。"
        detail={detail}
        action={
          playerHref ? (
            <a className={`btn btn-primary ${styles.action}`} href={playerHref}>
              以玩家身份进入
            </a>
          ) : null
        }
      />
    );
  }
  if (kind === "auth") {
    return (
      <Shell
        role="alert"
        art="card"
        code="4401 / 4403"
        title="村口有人守着"
        desc={
          authed ? (
            <>
              这局不是你建的，也没有分享给你。
              <br />
              回村志看看自己的对局，或向建局者要分享链接。
            </>
          ) : (
            <>
              这局不对外公开。请登录，
              <br />
              或使用建局者给你的分享链接。
            </>
          )
        }
        detail={detail}
        action={
          authed ? (
            <a className={`btn btn-secondary ${styles.action}`} href="#/history">
              回到村志
            </a>
          ) : (
            <a className={`btn btn-primary ${styles.action}`} href="#/login">
              去登录
            </a>
          )
        }
      />
    );
  }
  return (
    <Shell
      role="alert"
      art="moon"
      code="4404"
      title="这局已随风散去"
      desc={
        <>
          对局不存在，或已被建局者删除。
          <br />
          检查链接，或回村志看看别的局。
        </>
      }
      detail={detail}
      action={
        <a className={`btn btn-secondary ${styles.action}`} href="#/history">
          回到村志
        </a>
      }
    />
  );
}
