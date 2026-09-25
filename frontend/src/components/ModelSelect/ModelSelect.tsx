// ModelSelect（设计稿 3c）：模型服务下拉 → 模型（可手输，↻ 拉取模型列表填充 datalist）
// + 发言 / 反思模型。provider 为空 = 兼容模式：直接写含前缀的 LiteLLM 模型串。
//
// 「不编造服务端数据」：模型列表只来自 GET /providers/{id}/models；失败时列表为空、
// 原文展示 error，输入框仍可手输。

import { useCallback, useEffect, useId, useState } from "react";
import type { ProviderPublic } from "../../api/providers";
import { PROVIDER_KIND_ZH, PROVIDER_PREFIX } from "../../lib/providerKinds";
import { useProviders } from "../../store/providers";
import styles from "./ModelSelect.module.css";

export interface ModelSelectValue {
  provider: string | null;
  model: string;
  model_speech: string | null;
  reflection_model: string | null;
}

export interface ModelSelectProps {
  providers: ProviderPublic[];
  value: ModelSelectValue;
  onChange(next: ModelSelectValue): void;
}

export default function ModelSelect({ providers, value, onChange }: ModelSelectProps): JSX.Element {
  const listModels = useProviders((s) => s.listModels);
  const listId = useId();
  const [models, setModels] = useState<string[]>([]);
  const [modelsNote, setModelsNote] = useState<string | null>(null);
  const [fetching, setFetching] = useState(false);

  const current = providers.find((p) => p.provider_id === value.provider) ?? null;

  const fetchModels = useCallback(
    async (providerId: string): Promise<void> => {
      setFetching(true);
      setModelsNote(null);
      try {
        const res = await listModels(providerId);
        setModels(res.models);
        setModelsNote(
          res.error ? `拉取失败：${res.error}（仍可手输）` : `${res.models.length} 个模型 · 可手输`,
        );
      } catch (err) {
        setModels([]);
        setModelsNote(`拉取失败：${err instanceof Error ? err.message : String(err)}（仍可手输）`);
      } finally {
        setFetching(false);
      }
    },
    [listModels],
  );

  // 切换 provider 时清空上一份模型列表（不自动请求：避免编辑器一打开就打网络）
  useEffect(() => {
    setModels([]);
    setModelsNote(null);
  }, [value.provider]);

  function selectProvider(providerId: string): void {
    const next = providerId || null;
    const picked = providers.find((p) => p.provider_id === next) ?? null;
    onChange({
      ...value,
      provider: next,
      // 换到某个 provider 且模型为空时，用它的默认模型起头
      model: value.model || picked?.default_model || "",
    });
  }

  return (
    <div className={styles.root}>
      <div className={styles.grid2}>
        <div className="field">
          <label htmlFor={`${listId}-prov`}>模型服务</label>
          <select
            id={`${listId}-prov`}
            className="input"
            value={value.provider ?? ""}
            onChange={(e) => selectProvider(e.target.value)}
          >
            {providers.map((p) => (
              <option key={p.provider_id} value={p.provider_id}>
                {p.name} · {PROVIDER_KIND_ZH[p.kind]}
              </option>
            ))}
            <option value="">未配置——直接写 LiteLLM 模型串</option>
          </select>
        </div>
        <div className="field">
          <label htmlFor={`${listId}-model`} className={styles.labelRow}>
            <span>{current ? "模型" : "LiteLLM 模型串"}</span>
            {current && (
              <button
                type="button"
                className="btn btn-ghost"
                style={{ fontSize: 12, padding: "0 4px" }}
                disabled={fetching}
                onClick={() => void fetchModels(current.provider_id)}
              >
                ↻ 拉取模型列表
              </button>
            )}
          </label>
          <input
            id={`${listId}-model`}
            className={`input ${styles.mono}`}
            list={`${listId}-models`}
            value={value.model}
            placeholder={current ? "qwen2.5:14b" : "openai/gpt-4o-mini"}
            onChange={(e) => onChange({ ...value, model: e.target.value })}
          />
          <datalist id={`${listId}-models`}>
            {models.map((m) => (
              <option key={m} value={m} />
            ))}
          </datalist>
        </div>
      </div>

      {modelsNote && <span className={styles.note}>{modelsNote}</span>}

      {providers.length === 0 && (
        <span className={styles.note}>
          还没有配置模型服务。<a href="#/providers">去「模型服务」新建 →</a>
        </span>
      )}

      <div className={styles.grid2}>
        <div className="field">
          <label htmlFor={`${listId}-speech`}>发言模型（可选）</label>
          <input
            id={`${listId}-speech`}
            className={`input ${styles.mono}`}
            list={`${listId}-models`}
            value={value.model_speech ?? ""}
            placeholder="同模型"
            onChange={(e) => onChange({ ...value, model_speech: e.target.value || null })}
          />
        </div>
        <div className="field">
          <label htmlFor={`${listId}-reflect`}>反思模型（可选）</label>
          <input
            id={`${listId}-reflect`}
            className={`input ${styles.mono}`}
            list={`${listId}-models`}
            value={value.reflection_model ?? ""}
            placeholder="同模型"
            onChange={(e) => onChange({ ...value, reflection_model: e.target.value || null })}
          />
        </div>
      </div>

      <span className={styles.note}>
        {current ? (
          <>
            三者共用同一 provider；实际调用串：
            <code>{`${PROVIDER_PREFIX[current.kind]}/${value.model || "…"}`}</code>
          </>
        ) : (
          <>模型串需含前缀（如 <code>ollama/qwen2.5:7b</code>）；凭据走环境变量，行为与之前相同。</>
        )}
      </span>
    </div>
  );
}
