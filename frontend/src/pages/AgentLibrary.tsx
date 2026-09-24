// AgentLibrary 页（设计稿 2b / 2d）：网格 AgentCard + 新建 / 导入 JSON / 导出全部 /
// 编辑 / 复制 / 删除（确认框）+ 空态。

import { useEffect, useRef, useState } from "react";
import type { AgentProfile, StoredAgent } from "../api/agents";
import { ApiError } from "../api/rest";
import AgentCard from "../components/AgentCard/AgentCard";
import AgentEditor from "../components/AgentEditor/AgentEditor";
import ConfirmDialog from "../components/ConfirmDialog/ConfirmDialog";
import { toProfilePayload } from "../lib/seats";
import { useAgentLibrary } from "../store/agents";
import { useProviders } from "../store/providers";
import styles from "./AgentLibrary.module.css";

function detailOf(err: unknown): string {
  if (err instanceof ApiError) return `${err.status} · ${err.detail}`;
  return err instanceof Error ? err.message : String(err);
}

/** 导入文件可以是 StoredAgent[] 或裸 AgentProfile[]（导出文件是前者）。 */
function profilesFromImport(data: unknown): AgentProfile[] {
  if (!Array.isArray(data)) throw new Error("JSON 顶层必须是数组");
  return data.map((item) => {
    if (item && typeof item === "object" && "profile" in item) {
      return toProfilePayload((item as StoredAgent).profile);
    }
    return toProfilePayload(item as AgentProfile);
  });
}

export default function AgentLibrary(): JSX.Element {
  const { items, skills, loading, error, refresh, create, update, remove } = useAgentLibrary();
  const providers = useProviders((s) => s.items);
  const refreshProviders = useProviders((s) => s.refresh);

  const [editing, setEditing] = useState<{ stored: StoredAgent | null } | null>(null);
  const [deleting, setDeleting] = useState<StoredAgent | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    void refresh();
    void refreshProviders();
  }, [refresh, refreshProviders]);

  async function save(profile: AgentProfile): Promise<void> {
    if (editing === null) return;
    setSaving(true);
    setSaveError(null);
    try {
      if (editing.stored) await update(editing.stored.agent_id, profile);
      else await create(profile);
      setEditing(null);
    } catch (err) {
      setSaveError(detailOf(err));
    } finally {
      setSaving(false);
    }
  }

  async function duplicate(stored: StoredAgent): Promise<void> {
    setNotice(null);
    try {
      // memory_id 库内唯一：副本不继承，否则必然 409
      await create({
        ...toProfilePayload(stored.profile),
        name: `${stored.profile.name ?? ""} 副本`,
        memory_id: null,
      });
      setNotice("已复制（副本不继承 memory_id）");
    } catch (err) {
      setNotice(detailOf(err));
    }
  }

  async function confirmDelete(): Promise<void> {
    if (deleting === null) return;
    try {
      await remove(deleting.agent_id);
      setDeleting(null);
    } catch (err) {
      setNotice(detailOf(err));
      setDeleting(null);
    }
  }

  async function importJson(file: File): Promise<void> {
    setNotice(null);
    let profiles: AgentProfile[];
    try {
      profiles = profilesFromImport(JSON.parse(await file.text()));
    } catch (err) {
      setNotice(`导入失败：${err instanceof Error ? err.message : String(err)}`);
      return;
    }
    const failures: string[] = [];
    for (const profile of profiles) {
      try {
        await create(profile);
      } catch (err) {
        failures.push(`${profile.name ?? "(无名)"}：${detailOf(err)}`);
      }
    }
    setNotice(
      failures.length === 0
        ? `导入 ${profiles.length} 个档案`
        : `导入 ${profiles.length - failures.length}/${profiles.length}；失败：${failures.join("；")}`,
    );
  }

  function exportAll(): void {
    const blob = new Blob([JSON.stringify(items, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "agenthowl-agents.json";
    a.click();
    URL.revokeObjectURL(url);
  }

  return (
    <div className={styles.page}>
      <div className={styles.head}>
        <div>
          <h3 className={styles.title}>Agent 档案库</h3>
          <p className="text-muted" style={{ fontSize: 13, margin: 0 }}>
            {items.length} 个档案 · 存于 data/agents/ · 同一 memory_id 跨局累积经验
          </p>
        </div>
        <div className={styles.headActions}>
          <button type="button" className="btn btn-secondary" onClick={() => fileRef.current?.click()}>
            导入 JSON
          </button>
          <button
            type="button"
            className="btn btn-secondary"
            disabled={items.length === 0}
            onClick={exportAll}
          >
            导出全部
          </button>
          <button
            type="button"
            className="btn btn-primary"
            onClick={() => {
              setSaveError(null);
              setEditing({ stored: null });
            }}
          >
            + 新建
          </button>
          <input
            ref={fileRef}
            type="file"
            accept="application/json,.json"
            hidden
            onChange={(e) => {
              const file = e.target.files?.[0];
              e.target.value = "";
              if (file) void importJson(file);
            }}
          />
        </div>
      </div>

      {error && <div className={styles.error}>{error}</div>}
      {notice && <div className={styles.notice}>{notice}</div>}

      {loading && items.length === 0 ? (
        <p className="text-muted" style={{ fontSize: 13 }}>
          载入中…
        </p>
      ) : items.length === 0 ? (
        <div className={styles.empty}>
          <div className={styles.emptyIcon}>?</div>
          <span className={styles.emptyTitle}>还没有 Agent</span>
          <span className={styles.emptyDesc}>先建一个：名字、模型、人格、技能与记忆标识。</span>
          <button
            type="button"
            className="btn btn-primary"
            style={{ marginTop: 8 }}
            onClick={() => setEditing({ stored: null })}
          >
            + 新建 Agent
          </button>
        </div>
      ) : (
        <div className={styles.grid}>
          {items.map((a) => (
            <AgentCard
              key={a.agent_id}
              stored={a}
              providerName={
                providers.find((p) => p.provider_id === a.profile.provider)?.name ?? null
              }
              onEdit={() => {
                setSaveError(null);
                setEditing({ stored: a });
              }}
              onDuplicate={() => void duplicate(a)}
              onDelete={() => setDeleting(a)}
            />
          ))}
          <button
            type="button"
            className={styles.addCard}
            onClick={() => {
              setSaveError(null);
              setEditing({ stored: null });
            }}
          >
            + 新建 Agent
          </button>
        </div>
      )}

      {editing !== null && (
        <AgentEditor
          stored={editing.stored}
          skills={skills}
          providers={providers}
          others={items.filter((a) => a.agent_id !== editing.stored?.agent_id)}
          saving={saving}
          error={saveError}
          onSave={(profile) => void save(profile)}
          onCancel={() => setEditing(null)}
        />
      )}

      {deleting !== null && (
        <ConfirmDialog
          title={`删除「${deleting.profile.name}」？`}
          body={
            <>
              档案文件将被移除。不会删除该记忆
              {deleting.profile.memory_id ? <code>（{deleting.profile.memory_id}）</code> : ""}
              的经验文件，另一档案仍可复用。
            </>
          }
          danger
          onConfirm={() => void confirmDelete()}
          onCancel={() => setDeleting(null)}
        />
      )}
    </div>
  );
}
