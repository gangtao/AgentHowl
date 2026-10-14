// AgentEditor 抽屉（设计稿 2c）：四组表单——基本（ModelSelect / 温度 / thinking）、
// 技能、人格、记忆；底部护栏提示 + 取消 / 保存。
//
// 本组件只产出 AgentProfile 形状的 body（extra=forbid），由调用方决定 POST 还是 PUT。
// 唯一性只做即时提示，判决权在后端（409）。

import { useId, useMemo, useState, type ChangeEvent } from "react";
import { PRESET_SPEAKERS, type AgentProfile, type SkillInfo, type StoredAgent } from "../../api/agents";
import { AVATAR_ACCEPT, MAX_AVATAR_BYTES, uploadAvatar } from "../../api/avatars";
import type { ProviderPublic } from "../../api/providers";
import { ApiError, designVoice, voiceAnchorUrl } from "../../api/rest";
import { isValidMemoryId, suggestMemoryId } from "../../lib/memoryId";
import {
  MAX_DESCRIPTION,
  MAX_STYLE_NOTES,
  forbiddenHits,
  fromPersonalitySpec,
  toPersonalitySpec,
  type PersonalityForm,
} from "../../lib/personality";
import Avatar from "../Avatar/Avatar";
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
  avatar: string | null;
  models: ModelSelectValue;
  temperature: number;
  thinking: boolean;
  skills: string[];
  personality: PersonalityForm;
  memoryId: string;
  voice: {
    mode: "none" | "preset" | "design";
    speaker: string;
    style: string;
    speed: number;
    /** 描述声线的锚点 id；描述一改就清空（锚点与旧描述绑定）。 */
    anchor: string | null;
  };
}

function initialForm(stored: StoredAgent | null, providers: ProviderPublic[]): FormState {
  const p = stored?.profile;
  // 新建时默认选中第一个已配置的模型服务（设计稿 3c）；没有 provider 才落到兼容模式
  const fallback = stored === null ? (providers[0] ?? null) : null;
  return {
    name: p?.name ?? "",
    avatar: p?.avatar ?? null,
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
    voice: p?.voice
      ? {
          mode: p.voice.mode,
          speaker: p.voice.speaker ?? "dylan",
          style: p.voice.style ?? "",
          speed: p.voice.speed ?? 1,
          anchor: p.voice.anchor ?? null,
        }
      : { mode: "none", speaker: "dylan", style: "", speed: 1, anchor: null },
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
  const [avatarNotice, setAvatarNotice] = useState<string | null>(null);

  async function onAvatarFile(e: ChangeEvent<HTMLInputElement>): Promise<void> {
    const file = e.target.files?.[0];
    e.target.value = ""; // 同一文件可重选
    if (!file) return;
    if (file.size > MAX_AVATAR_BYTES) {
      setAvatarNotice(`头像不能超过 ${MAX_AVATAR_BYTES / 1024} KB`);
      return;
    }
    setAvatarNotice(null);
    try {
      const up = await uploadAvatar(file);
      setForm((f) => ({ ...f, avatar: up.avatar_id }));
    } catch (err) {
      setAvatarNotice(err instanceof ApiError ? err.detail : String(err));
    }
  }

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
  // design 声线必须给出描述，否则后端 VoiceSpec._check_mode 会 422（issue #103）。
  const voiceBad = form.voice.mode === "design" && form.voice.style.trim() === "";

  const blocked =
    nameTrimmed === "" ||
    form.models.model.trim() === "" ||
    nameTaken ||
    memoryShapeBad ||
    memoryTakenBy !== undefined ||
    tooLong ||
    voiceBad;

  const [designing, setDesigning] = useState(false);
  const [designError, setDesignError] = useState<string | null>(null);

  async function designAnchor(): Promise<void> {
    const style = form.voice.style.trim();
    if (style === "" || designing) return;
    setDesigning(true);
    setDesignError(null);
    try {
      const res = await designVoice(style);
      setForm((f) => ({ ...f, voice: { ...f.voice, anchor: res.anchor_id } }));
    } catch (err) {
      setDesignError(err instanceof ApiError ? err.detail : String(err));
    } finally {
      setDesigning(false);
    }
  }

  function submit(): void {
    if (blocked || saving) return;
    const voice: AgentProfile["voice"] =
      form.voice.mode === "none"
        ? null
        : form.voice.mode === "preset"
          ? {
              mode: "preset",
              speaker: form.voice.speaker,
              style: form.voice.style.trim() || null,
              speed: form.voice.speed,
            }
          : {
              mode: "design",
              style: form.voice.style.trim(),
              speed: form.voice.speed,
              anchor: form.voice.anchor,
            };
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
      avatar: form.avatar,
      voice,
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
            <label>头像</label>
            <div className={styles.avatarRow}>
              <Avatar avatar={form.avatar} name={nameTrimmed} seat={null} size={56} />
              <label className="btn btn-secondary" htmlFor={`${uid}-avatar`}>
                上传头像
                <input
                  id={`${uid}-avatar`}
                  type="file"
                  accept={AVATAR_ACCEPT}
                  hidden
                  onChange={(e) => void onAvatarFile(e)}
                />
              </label>
              {form.avatar !== null && (
                <button
                  type="button"
                  className="btn btn-ghost"
                  onClick={() => setForm((f) => ({ ...f, avatar: null }))}
                >
                  移除头像
                </button>
              )}
              <span className="text-muted" style={{ fontSize: 12 }}>
                PNG / JPEG / WebP，≤ 512 KB，建议正方形
              </span>
            </div>
            {avatarNotice !== null && <div className={styles.err}>{avatarNotice}</div>}
          </div>
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

        <section className={styles.group}>
          <span className="card-kicker">5 · 声线</span>
          <div className="field">
            <label htmlFor={`${uid}-voice-mode`}>声线模式</label>
            <select
              id={`${uid}-voice-mode`}
              className="input"
              value={form.voice.mode}
              onChange={(e) =>
                setForm({
                  ...form,
                  voice: { ...form.voice, mode: e.target.value as FormState["voice"]["mode"] },
                })
              }
            >
              <option value="none">不配音</option>
              <option value="preset">预置声线</option>
              <option value="design">描述声线</option>
            </select>
          </div>
          {form.voice.mode === "preset" && (
            <>
              <div className="field">
                <label htmlFor={`${uid}-voice-speaker`}>预置声线</label>
                <select
                  id={`${uid}-voice-speaker`}
                  className="input"
                  value={form.voice.speaker}
                  onChange={(e) =>
                    setForm({ ...form, voice: { ...form.voice, speaker: e.target.value } })
                  }
                >
                  {PRESET_SPEAKERS.map((s) => (
                    <option key={s.id} value={s.id}>
                      {s.label}
                    </option>
                  ))}
                </select>
              </div>
              <div className="field">
                <label htmlFor={`${uid}-voice-style`}>情绪 / 语速指令（可选）</label>
                <input
                  id={`${uid}-voice-style`}
                  className="input"
                  maxLength={200}
                  value={form.voice.style}
                  onChange={(e) =>
                    setForm({ ...form, voice: { ...form.voice, style: e.target.value } })
                  }
                />
              </div>
            </>
          )}
          {form.voice.mode === "design" && (
            <div className="field">
              <label htmlFor={`${uid}-voice-style`}>声线描述</label>
              <textarea
                id={`${uid}-voice-style`}
                className="input"
                rows={2}
                maxLength={200}
                placeholder="沙哑低沉的中年东北男声，语速快"
                value={form.voice.style}
                onChange={(e) =>
                  // 描述一改，旧锚点就不再代表这段描述：清掉，提示重新生成
                  setForm({
                    ...form,
                    voice: { ...form.voice, style: e.target.value, anchor: null },
                  })
                }
              />
              {voiceBad && <span className={styles.err}>声线描述必填。</span>}
              <div className={styles.anchorRow}>
                <button
                  type="button"
                  className="btn btn-secondary"
                  disabled={voiceBad || designing}
                  onClick={() => void designAnchor()}
                >
                  {designing ? "生成中…" : form.voice.anchor ? "换一个" : "生成声线试听"}
                </button>
                {form.voice.anchor !== null && (
                  <audio
                    controls
                    preload="none"
                    src={voiceAnchorUrl(form.voice.anchor)}
                    aria-label="声线试听"
                  />
                )}
              </div>
              {designError !== null && <span className={styles.err}>{designError}</span>}
              <span className={styles.hint}>
                {form.voice.anchor
                  ? "已固定这个声线：对局里每句话都用它。想换就再点「换一个」。"
                  : "描述只约束风格，具体是谁每次生成都不同——先「生成声线试听」把人定下来再保存；不生成则开局时自动定一次。"}
              </span>
            </div>
          )}
          {form.voice.mode !== "none" && (
            <div className="field">
              <label htmlFor={`${uid}-voice-speed`}>
                语速 <span className={styles.tempValue}>{form.voice.speed.toFixed(1)}×</span>
              </label>
              <input
                id={`${uid}-voice-speed`}
                type="range"
                min={0.5}
                max={2}
                step={0.1}
                value={form.voice.speed}
                className={styles.range}
                onChange={(e) =>
                  setForm({ ...form, voice: { ...form.voice, speed: Number(e.target.value) } })
                }
              />
            </div>
          )}
          <span className={styles.hint}>
            需配置 TTS 服务（AGENTHOWL_TTS_URL）且建局勾选「语音」才会生效；方言只有北京话 / 四川话两个预置声线。
          </span>
        </section>
      </div>
    </Drawer>
  );
}
