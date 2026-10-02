// 历史对局页（issue #98 设计 §3）：列出 data/games/ 里的全部对局，已结束的可无 token 回放。

import { useEffect } from "react";
import HistoryTable from "../components/HistoryTable/HistoryTable";
import { useHistory } from "../store/history";
import styles from "./History.module.css";

export default function History(): JSX.Element {
  const items = useHistory((s) => s.items);
  const loading = useHistory((s) => s.loading);
  const error = useHistory((s) => s.error);
  const refresh = useHistory((s) => s.refresh);

  useEffect(() => {
    void refresh();
  }, [refresh]);

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
        <HistoryTable items={items} />
      )}
    </div>
  );
}
