// AgentEditor 抽屉（设计稿 2c）：四组表单——基本（ModelSelect / 温度 / thinking）、
// 技能、人格、记忆；底部护栏提示 + 取消 / 保存。
//
// 本组件只产出 AgentProfile 形状的 body（extra=forbid），由调用方决定 POST 还是 PUT。
// 唯一性只做即时提示，判决权在后端（409）。

import { useId, useMemo, useState } from "react";
import type { AgentProfile, SkillInfo, StoredAgent } from "../../api/agents";
import type { ProviderPublic } from "../../api/providers";
import { isValidMemoryId, suggestMemoryId } from "../../lib/memoryId";
import {
  MAX_DESCRIPTION,
  MAX_STYLE_NOTES,
  forbiddenHits,
  fromPersonalitySpec,
  toPersonalitySpec,
  type PersonalityForm,
} from "../../lib/personality";
import Drawer from "../Drawer/Drawer";
import ModelSelect, { type ModelSelectValue } from "../ModelSelect/ModelSelect";
import PersonalityEditor from "../PersonalityEditor/PersonalityEditor";
import SkillPicker from "../SkillPicker/SkillPicker";
import styles from "./AgentEditor.module.css";

export interface AgentEditorProps {
  /** null = 新建。 */
  stored: StoredAgent | null;
  skills: SkillInfo[];
  providers: ProviderPublic[];
  /** 库内其它档案：名字 / memory_id 唯一性即时提示。 */
  others: StoredAgent[];
  saving?: boolean;
  error?: string | null;
  onSave(profile: AgentProfile): void;
  onCancel(): void;
}

interface FormState {
  name: string;
  models: ModelSelectValue;
  temperature: number;
  thinking: boolean;
  skills: string[];
  personality: PersonalityForm;
  memoryId: string;
}

function initialForm(stored: StoredAgent | null, providers: ProviderPublic[]): FormState {
  const p = stored?.profile;
  // 新建时默认选中第一个已配置的模型服务（设计稿 3c）；没有 provider 才落到兼容模式
  const fallback = stored === null ? (providers[0] ?? null) : null;
  return {
    name: p?.name ?? "",
    models: {
      provider: p?.provider ?? fallback?.provider_id ?? null,
      model: p?.model ?? fallback?.default_model ?? "",
      model_speech: p?.model_speech ?? null,
      reflection_model: p?.reflection_model ?? null,
    },
    temperature: p?.temperature ?? 0.3,
    thinking: p?.thinking ?? false,
    skills: p?.skills ? [...p.skills] : [],
    personality: fromPersonalitySpec(p?.personality),
    memoryId: p?.memory_id ?? "",
  };
}

export default function AgentEditor({
  stored,
  skills,
  providers,
  others,
  saving = false,
  error = null,
  onSave,
  onCancel,
}: AgentEditorProps): JSX.Element {
  const uid = useId();
  const [form, setForm] = useState<FormState>(() => initialForm(stored, providers));

  const nameTrimmed = form.name.trim();
  const nameTaken = others.some((a) => a.profile.name === nameTrimmed && nameTrimmed !== "");
  const memoryTakenBy = others.find(
    (a) => form.memoryId !== "" && a.profile.memory_id === form.memoryId,
  );
  const memoryShapeBad = form.memoryId !== "" && !isValidMemoryId(form.memoryId);

  const personalitySpec = useMemo(() => toPersonalitySpec(form.personality), [form.personality]);
  // 护栏短语与后端 _check_guardrail 同口径（description / style_notes / traits 的键），
  // 但**只做提示不挡保存**：判决权在后端 422（spec §7.2b），落到 footer 的 error 位。
  const guardHits = [
    ...new Set([
      ...forbiddenHits(form.personality.description),
      ...forbiddenHits(form.personality.styleNotes),
      ...form.personality.traits.flatMap((t) => forbiddenHits(t.word)),
    ]),
  ];
  const tooLong =
    form.personality.description.length > MAX_DESCRIPTION ||
    form.personality.styleNotes.length > MAX_STYLE_NOTES;

  const blocked =
    nameTrimmed === "" ||
    form.models.model.trim() === "" ||
    nameTaken ||
    memoryShapeBad ||
    memoryTakenBy !== undefined ||
    tooLong;

  function submit(): void {
    if (blocked || saving) return;
    const profile: AgentProfile = {
      name: nameTrimmed,
      model: form.models.model.trim(),
      model_speech: form.models.model_speech,
      reflection_model: form.models.reflection_model,
      thinking: form.thinking,
      temperature: form.temperature,
      skills: form.skills,
      personality: personalitySpec,
      memory_id: form.memoryId || null,
      provider: form.models.provider,
    };
    onSave(profile);
  }

  const footer = (
    <>
      <span className={styles.guard}>
        {error ? (
          <span className={styles.err}>{error}</span>
        ) : guardHits.length > 0 ? (
          <span className={styles.err}>
            护栏：人格含「{guardHits.join("」「")}」— 保存将被后端 422 拒绝
          </span>
        ) : (
          <span className={styles.hint}>
            名字与 memory_id 库内唯一；技能名与 provider 由后端校验。
          </span>
        )}
      </span>
      <button type="button" className="btn btn-ghost" style={{ marginLeft: "auto" }} onClick={onCancel}>
        取消
      </button>
      <button type="button" className="btn btn-primary" disabled={blocked || saving} onClick={submit}>
        {saving ? "保存中…" : "保存"}
      </button>
    </>
  );

  return (
    <Drawer
      title={stored ? `编辑 Agent · ${stored.profile.name ?? ""}` : "新建 Agent"}
      idTag={stored?.agent_id ?? null}
      width={620}
      onClose={onCancel}
      footer={footer}
    >
      <div className={styles.groups}>
        <section className={styles.group}>
          <span className="card-kicker">1 · 基本</span>
          <div className="field">
            <label htmlFor={`${uid}-name`}>名字 *</label>
            <input
              id={`${uid}-name`}
              className="input"
              value={form.name}
              placeholder="夜枭"
              onChange={(e) => setForm({ ...form, name: e.target.value })}
            />
            {nameTrimmed === "" ? (
              <span className={styles.err}>名字必填。</span>
            ) : nameTaken ? (
              <span className={styles.err}>已有同名档案：{nameTrimmed}</span>
            ) : (
              <span className={styles.ok}>✓ 唯一</span>
            )}
          </div>
          <ModelSelect
            providers={providers}
            value={form.models}
            onChange={(models) => setForm({ ...form, models })}
          />
          <div className={styles.tempRow}>
            <div className="field">
              <label htmlFor={`${uid}-temp`}>
                温度 <span className={styles.tempValue}>{form.temperature.toFixed(1)}</span>
              </label>
              <input
                id={`${uid}-temp`}
                type="range"
                min={0}
                max={2}
                step={0.1}
                value={form.temperature}
                className={styles.range}
                onChange={(e) => setForm({ ...form, temperature: Number(e.target.value) })}
              />
            </div>
            <label className={styles.toggle}>
              thinking
              <input
                type="checkbox"
                checked={form.thinking}
                onChange={(e) => setForm({ ...form, thinking: e.target.checked })}
              />
              <span className={styles.toggleHint}>推理模型思考开关</span>
            </label>
          </div>
        </section>

        <section className={styles.group}>
          <SkillPicker
            skills={skills}
            value={form.skills}
            onChange={(next) => setForm({ ...form, skills: next })}
          />
        </section>

        <section className={styles.group}>
          <span className="card-kicker">3 · 人格</span>
          <PersonalityEditor
            value={form.personality}
            onChange={(personality) => setForm({ ...form, personality })}
          />
        </section>

        <section className={styles.group}>
          <span className="card-kicker">4 · 记忆</span>
          <div className={styles.memRow}>
            <div className="field">
              <label htmlFor={`${uid}-mem`}>memory_id（可选）</label>
              <input
                id={`${uid}-mem`}
                className={`input ${styles.mono}`}
                value={form.memoryId}
                placeholder="night-owl"
                onChange={(e) => setForm({ ...form, memoryId: e.target.value })}
              />
            </div>
            <button
              type="button"
              className="btn btn-secondary"
              onClick={() => setForm({ ...form, memoryId: suggestMemoryId(form.name) })}
            >
              按名字生成
            </button>
          </div>
          {memoryShapeBad ? (
            <span className={styles.err}>只能含 A–Z a–z 0–9 _ -，且 ≤ 64 字符。</span>
          ) : memoryTakenBy ? (
            <span className={styles.err}>
              memory_id 已被档案「{memoryTakenBy.profile.name}」使用
            </span>
          ) : form.memoryId ? (
            <span className={styles.ok}>✓ 唯一</span>
          ) : null}
          <span className={styles.hint}>
            同一 memory_id 的 Agent 跨局累积经验；改 id 不迁移已有经验文件。
          </span>
        </section>
      </div>
    </Drawer>
  );
}
