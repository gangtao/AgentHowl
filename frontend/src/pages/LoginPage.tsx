// 登录 / 注册 / 邮箱验证（issue #114）。三种 mode 由 hash 路由决定；成功后跳 next（默认 #/）。

import { useState } from "react";
import type { FormEvent } from "react";
import { register, resend, verify } from "../api/auth";
import { ApiError } from "../api/rest";
import { useAuth } from "../store/auth";
import styles from "./LoginPage.module.css";

export type LoginMode = "login" | "register" | "verify";

export interface LoginPageProps {
  mode: LoginMode;
  /** 登录成功后跳转的 hash；缺省 `#/`。 */
  next?: string;
}

const VERIFY_EMAIL_KEY = "agenthowl.verify_email";

// sessionStorage 在隐私模式 / 禁用站点数据时可能抛，读写都吞掉。
function readVerifyEmail(): string {
  try {
    return sessionStorage.getItem(VERIFY_EMAIL_KEY) ?? "";
  } catch {
    return "";
  }
}

function writeVerifyEmail(email: string): void {
  try {
    sessionStorage.setItem(VERIFY_EMAIL_KEY, email);
  } catch {
    // 记不住就让用户在验证页重填
  }
}

function messageOf(err: unknown): string {
  if (err instanceof ApiError) return err.detail;
  return err instanceof Error ? err.message : String(err);
}

export default function LoginPage({ mode, next = "#/" }: LoginPageProps): JSX.Element {
  const login = useAuth((s) => s.login);
  const [identifier, setIdentifier] = useState("");
  const [username, setUsername] = useState("");
  const [email, setEmail] = useState(() => (mode === "verify" ? readVerifyEmail() : ""));
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  async function submit(e: FormEvent): Promise<void> {
    e.preventDefault();
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      if (mode === "login") {
        await login(identifier, password);
        window.location.hash = next;
      } else if (mode === "register") {
        const r = await register(username, email, password);
        if (r.verification === "auto") {
          setNotice("注册成功，请登录。");
        } else {
          writeVerifyEmail(email);
          window.location.hash = "#/verify";
        }
      } else {
        await verify(email, code);
        await useAuth.getState().load();
        window.location.hash = next;
      }
    } catch (err) {
      if (err instanceof ApiError && err.reason === "unverified") {
        writeVerifyEmail(identifier);
        window.location.hash = "#/verify";
        return;
      }
      setError(messageOf(err));
    } finally {
      setBusy(false);
    }
  }

  async function doResend(): Promise<void> {
    setError(null);
    try {
      await resend(email);
      setNotice("如果该邮箱已注册且未验证，验证码已重新发送。");
    } catch (err) {
      setError(messageOf(err));
    }
  }

  const title = mode === "login" ? "登录" : mode === "register" ? "注册" : "验证邮箱";

  return (
    <div className={styles.page}>
      <form className={styles.card} onSubmit={(e) => void submit(e)}>
        <h2 className={styles.title}>{title}</h2>
        {mode === "login" && (
          <div className="field">
            <label htmlFor="login-id">用户名或邮箱</label>
            <input id="login-id" className="input" value={identifier} onChange={(e) => setIdentifier(e.target.value)} autoComplete="username" />
          </div>
        )}
        {mode === "register" && (
          <div className="field">
            <label htmlFor="reg-name">用户名</label>
            <input id="reg-name" className="input" value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" />
            <span className="text-muted">3–32 位小写字母、数字或下划线</span>
          </div>
        )}
        {mode !== "login" && (
          <div className="field">
            <label htmlFor="auth-email">邮箱</label>
            <input id="auth-email" className="input" type="email" value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="email" />
          </div>
        )}
        {mode !== "verify" && (
          <div className="field">
            <label htmlFor="auth-pw">密码</label>
            <input id="auth-pw" className="input" type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete={mode === "login" ? "current-password" : "new-password"} />
          </div>
        )}
        {mode === "verify" && (
          <div className="field">
            <label htmlFor="auth-code">验证码</label>
            <input id="auth-code" className="input" inputMode="numeric" value={code} onChange={(e) => setCode(e.target.value)} />
          </div>
        )}
        {error !== null && <div className={styles.error}>{error}</div>}
        {notice !== null && <div className={styles.notice}>{notice}</div>}
        <div className={styles.actions}>
          <button type="submit" className="btn btn-primary" disabled={busy}>
            {title}
          </button>
          {mode === "verify" && (
            <button type="button" className="btn" onClick={() => void doResend()}>
              重发验证码
            </button>
          )}
        </div>
        <div className={styles.links}>
          {mode !== "login" && <a href="#/login">已有账号？登录</a>}
          {mode !== "register" && <a href="#/register">没有账号？注册</a>}
          {mode !== "verify" && <a href="#/verify">输入验证码</a>}
        </div>
      </form>
    </div>
  );
}
