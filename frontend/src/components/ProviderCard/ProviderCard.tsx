// ProviderCard（设计稿 3a）：名字 + 类型徽标 + 连通点 + 地址/密钥/默认模型键值网格 + 引用数。
// 密钥永不显示明文：只有 has_key + key_hint（末 4 位）。

import type { ProviderPublic, ProviderTestResult } from "../../api/providers";
import { PROVIDER_KIND_ZH } from "../../lib/providerKinds";
import styles from "./ProviderCard.module.css";

export interface ProviderCardProps {
  provider: ProviderPublic;
  /** 引用它的 Agent 名字（由 useAgentLibrary 计算）。 */
  refNames: string[];
  test?: ProviderTestResult | null;
  testing?: boolean;
  onTest(): void;
  onEdit(): void;
  onDelete(): void;
}

export default function ProviderCard({
  provider,
  refNames,
  test = null,
  testing = false,
  onTest,
  onEdit,
  onDelete,
}: ProviderCardProps): JSX.Element {
  const statusColor = testing
    ? "var(--color-neutral-600)"
    : test === null
      ? "var(--color-neutral-600)"
      : test.ok
        ? "var(--ah-ok)"
        : "var(--ah-err)";
  const statusText = testing
    ? "测试中…"
    : test === null
      ? "未测试"
      : test.ok
        ? `连通 · ${test.latency_ms ?? "?"} ms`
        : `失败 · ${test.latency_ms ?? "?"} ms`;

  return (
    <div className={`card elev-sm ${styles.card}`}>
      <div className={styles.head}>
        <span className={styles.name}>{provider.name}</span>
        <span className="tag tag-accent" style={{ padding: "1px 8px", fontSize: 10.5 }}>
          {PROVIDER_KIND_ZH[provider.kind] ?? provider.kind}
        </span>
        <span className={styles.status}>
          <span className={styles.dot} style={{ background: statusColor }} />
          {statusText}
        </span>
      </div>
      <div className={styles.kv}>
        <span className={styles.k}>地址</span>
        <span className={styles.v}>{provider.api_base ?? "（默认）"}</span>
        <span className={styles.k}>密钥</span>
        <span className={styles.v} style={{ color: provider.has_key ? undefined : "var(--color-neutral-500)" }}>
          {provider.has_key ? `已配置 ····${provider.key_hint ?? "****"}` : "未配置"}
        </span>
        <span className={styles.k}>默认模型</span>
        <span className={styles.v}>{provider.default_model ?? "—"}</span>
      </div>
      {test !== null && !test.ok && test.error && <pre className={styles.error}>{test.error}</pre>}
      <div className="card-meta" style={{ justifyContent: "space-between", marginTop: 2 }}>
        <span>
          {refNames.length === 0 ? "未被引用" : `被 ${refNames.length} 个 Agent 引用`}
          {refNames.length > 0 ? `：${refNames.join("、")}` : ""}
        </span>
        <span className={styles.actions}>
          <button type="button" className="btn btn-ghost" disabled={testing} onClick={onTest}>
            测试连接
          </button>
          <button type="button" className="btn btn-ghost" onClick={onEdit}>
            编辑
          </button>
          <button
            type="button"
            className={`btn btn-ghost ${styles.del}`}
            onClick={onDelete}
            title={refNames.length > 0 ? `仍被引用：${refNames.join("、")}` : undefined}
          >
            删除
          </button>
        </span>
      </div>
    </div>
  );
}
