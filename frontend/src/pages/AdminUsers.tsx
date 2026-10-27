// 管理员用户页（issue #114）：列出全部用户，禁用/启用、角色切换、手工验证邮箱。
// 自己那行不渲染操作按钮（后端同样拒绝改自己）；每次操作后用响应替换该行。

import { useCallback, useEffect, useState } from "react";
import { listUsers, patchUser, verifyUser } from "../api/admin";
import type { UserPublic } from "../api/auth";
import { ApiError } from "../api/rest";
import { useAuth } from "../store/auth";
import styles from "./AdminUsers.module.css";

/** ISO 时间 → 本地可读；解析不了（旧数据 / 测试桩）原样返回。 */
function fmtTime(iso: string): string {
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return iso;
  return new Date(t).toLocaleString("zh-CN", { hour12: false });
}

export default function AdminUsers(): JSX.Element {
  const me = useAuth((s) => s.user);
  const [users, setUsers] = useState<UserPublic[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  // 在途请求的 user_id：同一行请求未返回前禁用该行按钮，避免响应乱序互相覆盖
  const [busy, setBusy] = useState<ReadonlySet<string>>(new Set());
  // issue #120：操作错误按行记录，两行并发失败互不覆盖；顶部错误条只给列表载入失败
  const [rowErrors, setRowErrors] = useState<Record<string, string>>({});

  useEffect(() => {
    let alive = true;
    listUsers()
      .then((rows) => {
        if (alive) setUsers(rows);
      })
      .catch((e: unknown) => {
        if (alive) setError(e instanceof ApiError ? e.detail : "载入用户失败");
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, []);

  const act = useCallback(async (userId: string, call: () => Promise<UserPublic>): Promise<void> => {
    setRowErrors((prev) => {
      const next = { ...prev };
      delete next[userId];
      return next;
    });
    setBusy((prev) => new Set(prev).add(userId));
    try {
      const updated = await call();
      setUsers((prev) => prev.map((u) => (u.user_id === updated.user_id ? updated : u)));
    } catch (e) {
      const detail = e instanceof ApiError ? e.detail : "操作失败";
      setRowErrors((prev) => ({ ...prev, [userId]: detail }));
    } finally {
      setBusy((prev) => {
        const next = new Set(prev);
        next.delete(userId);
        return next;
      });
    }
  }, []);

  return (
    <div className={styles.page}>
      <div>
        <h3 className={styles.title}>用户管理</h3>
        <p className="text-muted" style={{ fontSize: 13, margin: 0 }}>
          共 {users.length} 个用户
        </p>
      </div>

      {error !== null && <div className={styles.error}>{error}</div>}

      {loading ? (
        <p className="text-muted" style={{ fontSize: 13 }}>
          载入中…
        </p>
      ) : (
        <table className="table">
          <thead>
            <tr>
              <th>用户名</th>
              <th>邮箱</th>
              <th>角色</th>
              <th>状态</th>
              <th>邮箱验证</th>
              <th>注册时间</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            {users.map((u) => (
              <tr key={u.user_id}>
                <td>{u.username}</td>
                <td>{u.email}</td>
                <td>{u.role === "admin" ? "管理员" : "普通用户"}</td>
                <td>{u.status === "active" ? "正常" : "已禁用"}</td>
                <td>{u.email_verified ? "已验证" : "未验证"}</td>
                <td className={styles.nowrap}>{fmtTime(u.created_at)}</td>
                <td>
                  {rowErrors[u.user_id] !== undefined && (
                    <div className={styles.error} role="alert">
                      {rowErrors[u.user_id]}
                    </div>
                  )}
                  {u.user_id !== me?.user_id && (
                    <div className={styles.actions}>
                      <button
                        type="button"
                        className="btn btn-ghost"
                        disabled={busy.has(u.user_id)}
                        aria-label={`${u.status === "active" ? "禁用" : "启用"} ${u.username}`}
                        onClick={() =>
                          void act(u.user_id, () => patchUser(u.user_id, { status: u.status === "active" ? "disabled" : "active" }))
                        }
                      >
                        {u.status === "active" ? "禁用" : "启用"}
                      </button>
                      <button
                        type="button"
                        className="btn btn-ghost"
                        disabled={busy.has(u.user_id)}
                        aria-label={`${u.role === "admin" ? "降为普通用户" : "设为管理员"} ${u.username}`}
                        onClick={() =>
                          void act(u.user_id, () => patchUser(u.user_id, { role: u.role === "admin" ? "user" : "admin" }))
                        }
                      >
                        {u.role === "admin" ? "降为普通用户" : "设为管理员"}
                      </button>
                      {!u.email_verified && (
                        <button
                          type="button"
                          className="btn btn-ghost"
                          disabled={busy.has(u.user_id)}
                          aria-label={`标记已验证 ${u.username}`}
                          onClick={() => void act(u.user_id, () => verifyUser(u.user_id))}
                        >
                          标记已验证
                        </button>
                      )}
                    </div>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
