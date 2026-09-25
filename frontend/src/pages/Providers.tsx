// Providers 页（设计稿 3a / 3d）：ProviderCard 网格（引用数由 useAgentLibrary 计算）+
// ProviderEditor 抽屉 + 删除被引用（409）只读对话框 + 空态。

import { useEffect, useState } from "react";
import type { ProviderInput, ProviderPublic, ProviderTestResult } from "../api/providers";
import { ApiError } from "../api/rest";
import ConfirmDialog from "../components/ConfirmDialog/ConfirmDialog";
import ProviderCard from "../components/ProviderCard/ProviderCard";
import ProviderEditor from "../components/ProviderEditor/ProviderEditor";
import { useAgentLibrary } from "../store/agents";
import { useProviders } from "../store/providers";
import styles from "./Providers.module.css";

function detailOf(err: unknown): string {
  if (err instanceof ApiError) return `${err.status} · ${err.detail}`;
  return err instanceof Error ? err.message : String(err);
}

export default function Providers(): JSX.Element {
  const { items, loading, error, refresh, create, update, remove, test, listModels } =
    useProviders();
  const agents = useAgentLibrary((s) => s.items);
  const refreshAgents = useAgentLibrary((s) => s.refresh);

  const [editing, setEditing] = useState<{ provider: ProviderPublic | null } | null>(null);
  const [deleting, setDeleting] = useState<ProviderPublic | null>(null);
  const [blockedDelete, setBlockedDelete] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [tests, setTests] = useState<Record<string, ProviderTestResult>>({});
  const [testingId, setTestingId] = useState<string | null>(null);

  useEffect(() => {
    void refresh();
    void refreshAgents();
  }, [refresh, refreshAgents]);

  function refNamesOf(providerId: string): string[] {
    return agents
      .filter((a) => a.profile.provider === providerId)
      .map((a) => a.profile.name ?? a.agent_id);
  }

  async function save(body: ProviderInput): Promise<void> {
    if (editing === null) return;
    setSaving(true);
    setSaveError(null);
    try {
      if (editing.provider) await update(editing.provider.provider_id, body);
      else await create(body);
      setEditing(null);
    } catch (err) {
      setSaveError(detailOf(err));
    } finally {
      setSaving(false);
    }
  }

  async function runTest(providerId: string, model?: string): Promise<ProviderTestResult> {
    setTestingId(providerId);
    try {
      const result = await test(providerId, model);
      setTests((prev) => ({ ...prev, [providerId]: result }));
      return result;
    } catch (err) {
      // 400（没有 default_model）/404 等请求层错误：折成同一条结果条展示原文
      const result: ProviderTestResult = { ok: false, latency_ms: null, error: detailOf(err) };
      setTests((prev) => ({ ...prev, [providerId]: result }));
      return result;
    } finally {
      setTestingId(null);
    }
  }

  async function confirmDelete(): Promise<void> {
    if (deleting === null) return;
    const target = deleting;
    setDeleting(null);
    try {
      await remove(target.provider_id);
    } catch (err) {
      // 后端 409 会列出仍在引用的档案名，原文展示
      setBlockedDelete(detailOf(err));
    }
  }

  return (
    <div className={styles.page}>
      <div className={styles.head}>
        <div>
          <h3 className={styles.title}>模型服务</h3>
          <p className="text-muted" style={{ fontSize: 13, margin: 0 }}>
            {items.length} 个 provider · 存于 data/providers/（本地 0600）· 密钥永不回传
          </p>
        </div>
        <div className={styles.headActions}>
          <button
            type="button"
            className="btn btn-primary"
            onClick={() => {
              setSaveError(null);
              setEditing({ provider: null });
            }}
          >
            + 新建
          </button>
        </div>
      </div>

      {error && <div className={styles.error}>{error}</div>}

      {loading && items.length === 0 ? (
        <p className="text-muted" style={{ fontSize: 13 }}>
          载入中…
        </p>
      ) : items.length === 0 ? (
        <div className={styles.empty}>
          <div className={styles.emptyIcon}>⌁</div>
          <span className={styles.emptyTitle}>还没有模型服务</span>
          <span className={styles.emptyDesc}>
            Ollama 用户：安装后点「新建」选择 Ollama，地址保持默认即可。
          </span>
          <button
            type="button"
            className="btn btn-primary"
            style={{ marginTop: 8 }}
            onClick={() => setEditing({ provider: null })}
          >
            + 新建
          </button>
        </div>
      ) : (
        <div className={styles.grid}>
          {items.map((p) => (
            <ProviderCard
              key={p.provider_id}
              provider={p}
              refNames={refNamesOf(p.provider_id)}
              test={tests[p.provider_id] ?? null}
              testing={testingId === p.provider_id}
              onTest={() => void runTest(p.provider_id)}
              onEdit={() => {
                setSaveError(null);
                setEditing({ provider: p });
              }}
              onDelete={() => setDeleting(p)}
            />
          ))}
        </div>
      )}

      {items.length > 0 && (
        <div className={styles.foot}>被引用的 provider 不可删除（后端 409 会列出档案名）。</div>
      )}

      {editing !== null && (
        <ProviderEditor
          provider={editing.provider}
          others={items.filter((p) => p.provider_id !== editing.provider?.provider_id)}
          refNames={editing.provider ? refNamesOf(editing.provider.provider_id) : []}
          saving={saving}
          error={saveError}
          onSave={(body) => void save(body)}
          onCancel={() => setEditing(null)}
          {...(editing.provider
            ? {
                onTest: (model: string | undefined) =>
                  runTest((editing.provider as ProviderPublic).provider_id, model),
                onListModels: () => listModels((editing.provider as ProviderPublic).provider_id),
              }
            : {})}
        />
      )}

      {deleting !== null && (
        <ConfirmDialog
          title={`删除「${deleting.name}」？`}
          body="该模型服务的配置文件（含密钥）将被移除。引用它的 Agent 需要改用其它服务。"
          danger
          onConfirm={() => void confirmDelete()}
          onCancel={() => setDeleting(null)}
        />
      )}

      {blockedDelete !== null && (
        <ConfirmDialog
          title="无法删除"
          body={blockedDelete}
          readOnly
          onConfirm={() => setBlockedDelete(null)}
          onCancel={() => setBlockedDelete(null)}
        />
      )}
    </div>
  );
}
