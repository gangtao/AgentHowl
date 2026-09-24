// ProviderEditor 抽屉（设计稿 3b）：名字 / 类型 chips（选后填默认地址）/ 地址 / 密钥
// （留空不改、「清除」）/ 默认模型（↻ 拉取模型列表）/ 测试连接结果条。
//
// 密钥永不回显：编辑态只显示 has_key + key_hint（末 4 位）。PUT body 的 api_key 语义
// （backend/app/api/providers.py::update_provider）：省略 = 保留原密钥，"" = 清除。

import { useId, useState } from "react";
import type {
  ProviderInput,
  ProviderKind,
  ProviderPublic,
  ProviderTestResult,
} from "../../api/providers";
import {
  DEFAULT_API_BASE,
  KIND_HINT,
  PROVIDER_KINDS,
  PROVIDER_KIND_ZH,
} from "../../lib/providerKinds";
import Drawer from "../Drawer/Drawer";
import styles from "./ProviderEditor.module.css";

export interface ProviderEditorProps {
  /** null = 新建。 */
  provider: ProviderPublic | null;
  /** 库内其它 provider：名字唯一性即时提示。 */
  others: ProviderPublic[];
  /** 引用它的 Agent 名字。 */
  refNames: string[];
  saving?: boolean;
  error?: string | null;
  onSave(body: ProviderInput): void;
  onCancel(): void;
  /** 测试连接：由页面接 useProviders().test（需要已保存的 provider_id）。 */
  onTest?(model: string | undefined): Promise<ProviderTestResult>;
  /** 拉取模型列表：同上，返回 {models, error}。 */
  onListModels?(): Promise<{ models: string[]; error?: string | null }>;
}

export default function ProviderEditor({
  provider,
  others,
  refNames,
  saving = false,
  error = null,
  onSave,
  onCancel,
  onTest,
  onListModels,
}: ProviderEditorProps): JSX.Element {
  const uid = useId();
  const [name, setName] = useState(provider?.name ?? "");
  const [kind, setKind] = useState<ProviderKind>(provider?.kind ?? "ollama");
  const [apiBase, setApiBase] = useState(
    provider?.api_base ?? DEFAULT_API_BASE[provider?.kind ?? "ollama"] ?? "",
  );
  const [defaultModel, setDefaultModel] = useState(provider?.default_model ?? "");
  const [keyInput, setKeyInput] = useState("");
  const [keyCleared, setKeyCleared] = useState(false);
  const [models, setModels] = useState<string[]>([]);
  const [modelsNote, setModelsNote] = useState<string | null>(null);
  const [test, setTest] = useState<ProviderTestResult | null>(null);
  const [testing, setTesting] = useState(false);

  const nameTrimmed = name.trim();
  const nameTaken = nameTrimmed !== "" && others.some((p) => p.name === nameTrimmed);
  const baseMissing = kind === "openai_compatible" && apiBase.trim() === "";
  const blocked = nameTrimmed === "" || nameTaken || baseMissing;

  function pickKind(next: ProviderKind): void {
    setKind(next);
    // 选类型自动填默认地址：只在地址为空或仍是上一个类型的默认值时覆盖，不踩用户手改的值
    const prevDefault = DEFAULT_API_BASE[kind] ?? "";
    if (apiBase.trim() === "" || apiBase === prevDefault) {
      setApiBase(DEFAULT_API_BASE[next] ?? "");
    }
  }

  function buildBody(): ProviderInput {
    const body: ProviderInput = {
      name: nameTrimmed,
      kind,
      api_base: apiBase.trim() || null,
      default_model: defaultModel.trim() || null,
    };
    // 省略 api_key = 保留原密钥；"" = 清除；有输入 = 设置新密钥
    if (keyCleared) body.api_key = "";
    else if (keyInput !== "") body.api_key = keyInput;
    return body;
  }

  async function runTest(): Promise<void> {
    if (!onTest) return;
    setTesting(true);
    try {
      setTest(await onTest(defaultModel.trim() || undefined));
    } catch (err) {
      setTest({
        ok: false,
        latency_ms: null,
        error: err instanceof Error ? err.message : String(err),
      });
    } finally {
      setTesting(false);
    }
  }

  async function fetchModels(): Promise<void> {
    if (!onListModels) return;
    setModelsNote("拉取中…");
    try {
      const res = await onListModels();
      setModels(res.models);
      setModelsNote(
        res.error ? `拉取失败：${res.error}（仍可手输）` : `${res.models.length} 个模型 · 可手输`,
      );
    } catch (err) {
      setModels([]);
      setModelsNote(`拉取失败：${err instanceof Error ? err.message : String(err)}（仍可手输）`);
    }
  }

  const footer = (
    <>
      <span className={styles.footNote}>
        {error ? (
          <span className={styles.err}>{error}</span>
        ) : refNames.length > 0 ? (
          `被 ${refNames.length} 个 Agent 引用`
        ) : (
          "密钥只存在本机 data/providers/（0600），永不回传前端。"
        )}
      </span>
      <button type="button" className="btn btn-ghost" style={{ marginLeft: "auto" }} onClick={onCancel}>
        取消
      </button>
      <button
        type="button"
        className="btn btn-primary"
        disabled={blocked || saving}
        onClick={() => onSave(buildBody())}
      >
        {saving ? "保存中…" : "保存"}
      </button>
    </>
  );

  return (
    <Drawer
      title={provider ? `编辑模型服务 · ${provider.name}` : "新建模型服务"}
      idTag={provider?.provider_id ?? null}
      width={560}
      onClose={onCancel}
      footer={footer}
    >
      <div className={styles.body}>
        <div className="field">
          <label htmlFor={`${uid}-name`}>名字 *</label>
          <input
            id={`${uid}-name`}
            className="input"
            value={name}
            placeholder="本地 Ollama"
            onChange={(e) => setName(e.target.value)}
          />
          {nameTrimmed === "" ? (
            <span className={styles.err}>名字必填。</span>
          ) : nameTaken ? (
            <span className={styles.err}>已有同名 provider：{nameTrimmed}</span>
          ) : (
            <span className={styles.ok}>✓ 唯一</span>
          )}
        </div>

        <div className="field">
          <label>类型</label>
          <div className={styles.kinds}>
            {PROVIDER_KINDS.map((k) => (
              <button
                key={k}
                type="button"
                className={`${styles.kind} ${k === kind ? styles.kindOn : ""}`}
                aria-pressed={k === kind}
                onClick={() => pickKind(k)}
              >
                {PROVIDER_KIND_ZH[k]}
              </button>
            ))}
          </div>
        </div>

        <div className="field">
          <label htmlFor={`${uid}-base`}>API 地址</label>
          <input
            id={`${uid}-base`}
            className={`input ${styles.mono}`}
            value={apiBase}
            placeholder={kind === "openai_compatible" ? "https://…/v1（必填）" : "（留空走官方端点）"}
            onChange={(e) => setApiBase(e.target.value)}
          />
          <span className={styles.hint}>{KIND_HINT[kind]}</span>
          {baseMissing && <span className={styles.err}>openai_compatible 类型须填写 api_base。</span>}
        </div>

        <div className="field">
          <label htmlFor={`${uid}-key`}>API 密钥</label>
          <div className={styles.keyRow}>
            <input
              id={`${uid}-key`}
              className="input"
              type="password"
              autoComplete="new-password"
              value={keyInput}
              disabled={keyCleared}
              placeholder={
                provider?.has_key
                  ? `保留现有密钥（留空即不改）· ····${provider.key_hint ?? "****"}`
                  : "未配置"
              }
              onChange={(e) => setKeyInput(e.target.value)}
            />
            {keyCleared ? (
              <button
                type="button"
                className="btn btn-secondary"
                onClick={() => setKeyCleared(false)}
              >
                撤销清除
              </button>
            ) : (
              <button
                type="button"
                className="btn btn-secondary"
                disabled={!provider?.has_key}
                onClick={() => {
                  setKeyCleared(true);
                  setKeyInput("");
                }}
              >
                清除
              </button>
            )}
          </div>
          <span className={keyCleared ? styles.err : styles.hint}>
            {keyCleared
              ? "保存后将清除现有密钥（api_key: \"\"）。"
              : "密钥永不回显；留空即不改动已保存的密钥。"}
          </span>
        </div>

        <div className="field">
          <label htmlFor={`${uid}-model`} className={styles.labelRow}>
            <span>默认模型</span>
            {onListModels && (
              <button
                type="button"
                className="btn btn-ghost"
                style={{ fontSize: 12, padding: "0 4px" }}
                onClick={() => void fetchModels()}
              >
                ↻ 拉取模型列表
              </button>
            )}
          </label>
          <input
            id={`${uid}-model`}
            className={`input ${styles.mono}`}
            list={`${uid}-models`}
            value={defaultModel}
            placeholder="qwen2.5:14b"
            onChange={(e) => setDefaultModel(e.target.value)}
          />
          <datalist id={`${uid}-models`}>
            {models.map((m) => (
              <option key={m} value={m} />
            ))}
          </datalist>
          {modelsNote && <span className={styles.hint}>{modelsNote}</span>}
          {!provider && <span className={styles.hint}>保存后才能拉取模型列表 / 测试连接。</span>}
        </div>

        {onTest && (
          <div className={styles.testBox}>
            <div
              className={styles.testBar}
              style={{
                background:
                  test === null
                    ? "color-mix(in srgb, var(--color-neutral-800) 55%, transparent)"
                    : test.ok
                      ? "color-mix(in srgb, var(--ah-ok) 10%, transparent)"
                      : "color-mix(in srgb, var(--ah-err) 10%, transparent)",
              }}
            >
              <button
                type="button"
                className="btn btn-secondary"
                style={{ padding: "4px 10px", fontSize: 12 }}
                disabled={testing}
                onClick={() => void runTest()}
              >
                测试连接
              </button>
              <span
                className={styles.dot}
                style={{
                  background:
                    test === null
                      ? "var(--color-neutral-600)"
                      : test.ok
                        ? "var(--ah-ok)"
                        : "var(--ah-err)",
                }}
              />
              <span className={styles.testText}>
                {testing
                  ? "测试中…"
                  : test === null
                    ? "未测试"
                    : `${test.ok ? "连通" : "失败"} · ${test.latency_ms ?? "?"} ms`}
              </span>
              <span className={styles.testMeta}>
                {(defaultModel.trim() || provider?.default_model) ?? "（需 default_model）"} ·
                max_tokens=8
              </span>
            </div>
            {test !== null && !test.ok && test.error && <pre className={styles.error}>{test.error}</pre>}
          </div>
        )}
      </div>
    </Drawer>
  );
}
