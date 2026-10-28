// ProviderCard「炼金工坊」药剂木牌（规格 §6，设计稿 1l 左）：44px 药剂圆（按 kind 取色）+ 名字 + 金色
// kind 行 + 右上测试状态；羊皮纸信息条（地址 / 密钥 / 默认模型 mono）；底部引用数 + 操作。
// 密钥永不显示明文：只有 has_key + key_hint（末 4 位）。

import type { ProviderPublic, ProviderTestResult } from "../../api/providers";
import { potionColors } from "../../lib/pagesLook";
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
  const tone = testing || test === null ? "idle" : test.ok ? "ok" : "err";
  const statusText = testing
    ? "● 测试中…"
    : test === null
      ? "● 未测试"
      : test.ok
        ? `● 已连通 · ${test.latency_ms ?? "?"} ms`
        : `● 失败 · ${test.latency_ms ?? "?"} ms`;
  const { hi, lo } = potionColors(provider.kind);
  const kindZh = (PROVIDER_KIND_ZH as Record<string, string>)[provider.kind] ?? provider.kind;

  return (
    <article className={`ah-wood ${styles.card}`}>
      <div className={styles.head}>
        <span
          className={styles.potion}
          aria-hidden="true"
          style={{ background: `radial-gradient(circle at 40% 35%, ${hi}, ${lo})` }}
        />
        <div className={styles.headText}>
          <h3 className={styles.name}>{provider.name}</h3>
          <span className={styles.kind}>{kindZh} 药剂</span>
        </div>
        <span className={styles.status} data-tone={tone}>
          {statusText}
        </span>
      </div>

      <div className={`ah-parch ${styles.strip}`}>
        <span className={styles.k}>地址</span>
        <span className={styles.v}>{provider.api_base ?? "（默认）"}</span>
        <span className={styles.k}>密钥</span>
        <span className={styles.v} data-muted={provider.has_key ? undefined : "true"}>
          {provider.has_key ? `已配置 ····${provider.key_hint ?? "****"}` : "未配置"}
        </span>
        <span className={styles.k}>默认模型</span>
        <span className={styles.v}>{provider.default_model ?? "—"}</span>
      </div>

      {test !== null && !test.ok && test.error && <pre className={styles.error}>{test.error}</pre>}

      <div className={styles.foot}>
        <span className={styles.refs}>
          {refNames.length === 0
            ? "未被引用"
            : `被 ${refNames.length} 个 Agent 引用：${refNames.join("、")}`}
        </span>
        <span className={styles.actions}>
          <button type="button" className={styles.action} disabled={testing} onClick={onTest}>
            测试连接
          </button>
          <button type="button" className={styles.action} onClick={onEdit}>
            编辑
          </button>
          <button
            type="button"
            className={`${styles.action} ${styles.del}`}
            onClick={onDelete}
            title={refNames.length > 0 ? `仍被引用：${refNames.join("、")}` : undefined}
          >
            删除
          </button>
        </span>
      </div>
    </article>
  );
}
