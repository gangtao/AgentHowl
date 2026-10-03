// 历史对局页（issue #98 设计 §3）：列出 data/games/ 里的全部对局，已结束的可无 token 回放。
// 删除（issue #100）：行内「删除」→ ConfirmDialog → store.remove；服务端 409/404 落到页面错误条。

import { useEffect, useState } from "react";
import type { GameSummary } from "../api/history";
import ConfirmDialog from "../components/ConfirmDialog/ConfirmDialog";
import HistoryTable from "../components/HistoryTable/HistoryTable";
import { useHistory } from "../store/history";
import styles from "./History.module.css";

export default function History(): JSX.Element {
  const items = useHistory((s) => s.items);
  const loading = useHistory((s) => s.loading);
  const error = useHistory((s) => s.error);
  const refresh = useHistory((s) => s.refresh);
  const remove = useHistory((s) => s.remove);
  const [deleting, setDeleting] = useState<GameSummary | null>(null);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  async function confirmDelete(): Promise<void> {
    if (deleting === null) return;
    try {
      await remove(deleting.game_id);
    } catch {
      // 错误文案已由 store 落到 error，这里只关框
    }
    setDeleting(null);
  }

  const finished = items.filter((r) => r.status === "finished").length;

  return (
    <div className={styles.page}>
      <div className={styles.head}>
        <div>
          <h3 className={styles.title}>历史对局</h3>
          <p className="text-muted" style={{ fontSize: 13, margin: 0 }}>
            {items.length} 局 · {finished} 局可回放 · 事件流存于 data/games/（服务端重启不丢）
          </p>
        </div>
        <div className={styles.headActions}>
          <button type="button" className="btn" disabled={loading} onClick={() => void refresh()}>
            刷新
          </button>
        </div>
      </div>

      {error !== null && <div className={styles.error}>{error}</div>}

      {loading && items.length === 0 ? (
        <p className="text-muted" style={{ fontSize: 13 }}>
          载入中…
        </p>
      ) : (
        <HistoryTable items={items} onDelete={setDeleting} />
      )}

      {deleting !== null && (
        <ConfirmDialog
          title="删除这局？"
          body={
            <>
              将删除 <code>{deleting.game_id}</code> 的事件文件，回放随之不可用，不可恢复。
              Agent 的跨局记忆不受影响。
            </>
          }
          confirmLabel="确认删除"
          danger
          onConfirm={() => void confirmDelete()}
          onCancel={() => setDeleting(null)}
        />
      )}
    </div>
  );
}
