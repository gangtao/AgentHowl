// 人格表单 ↔ PersonalitySpec 的纯函数与只读预览（规格 §7.2b 第 3 组）。
//
// 词表、句式与顺序逐字抄录自 backend/app/agent/personality.py（TRAIT_LEXICON / _MBTI_TEXT /
// _BIG_FIVE_TEXT / _band / render_personality / personality_summary）。这里只做**只读预览**与
// 表单归一：最终文案与校验一律以后端为准（护栏命中前端只红字提示，后端 422 才是判决）。

export const FORBIDDEN_PHRASES: readonly string[] = [
  "你知道",
  "上帝视角",
  "无视规则",
  "绕过",
  "作弊",
  "真实身份是",
  "其实是狼",
];

export const MAX_DESCRIPTION = 300;
export const MAX_STYLE_NOTES = 100;
export const MAX_TRAIT_LEN = 12;

export const MBTI_AXES = ["EI", "SN", "TF", "JP"] as const;
export const BIG_FIVE_KEYS = ["O", "C", "E", "A", "N"] as const;

/** 特质词 → 狼人杀语境行为句（词表外的词按形容词原样纳入）。 */
export const TRAIT_LEXICON: Record<string, string> = {
  多疑: "倾向质疑金水与示好，不轻信任何人",
  冲动: "早表态、易改票、先说后想",
  谨慎: "后置位再表态，少声称身份",
  从众: "倾向跟大票、不当出头鸟",
  好胜: "敢于争警长、敢于悍跳或对跳",
  冷静: "情绪稳定，被怀疑时不过度辩解",
  健谈: "发言长、主动带节奏",
  沉默: "发言简短、只说关键信息",
  固执: "一旦定论很少改票",
  圆滑: "不轻易得罪人、措辞留余地",
  直率: "有怀疑直接点名",
  乐观: "倾向相信局势可控、少做最坏打算",
  悲观: "倾向假设最坏情况、对示好保持警惕",
  逻辑: "以票型与发言矛盾为主要依据",
  感性: "以信任感与直觉为主要依据",
};

export const TRAIT_WORDS: readonly string[] = Object.keys(TRAIT_LEXICON);

const MBTI_TEXT: Record<string, string> = {
  E: "主动发言、愿意上警争节奏",
  I: "少说多听、后置位表态",
  S: "只认已发生的票型与事实",
  N: "敢于推测身份链、提前站边",
  T: "用逻辑找狼、查杀直接归票、不怕得罪人",
  F: "看重信任与关系、倾向相信示好者",
  J: "早定论、坚持判断、不轻易改票",
  P: "保留判断、随新信息灵活改口",
};

/** 4 字母写法的隐式强度（S/N 信号弱 → 「略微」档）。 */
const MBTI_DEFAULT_STRENGTH: Record<string, number> = { EI: 0.5, SN: 0.3, TF: 0.5, JP: 0.5 };

const BIG_FIVE_TEXT: Record<string, readonly [string, string]> = {
  O: ["乐于尝试非常规打法", "按常规套路走"],
  C: ["记录票型、逻辑严谨", "凭感觉判断"],
  E: ["主动发言、愿意上警争节奏", "少说多听、后置位表态"],
  A: ["随和、容易被说服", "多疑、爱唱反调"],
  N: ["被怀疑时容易情绪化辩解", "情绪稳定、被怀疑时不慌"],
};

export const BIG_FIVE_ZH: Record<string, string> = {
  O: "开放性 O",
  C: "尽责性 C",
  E: "外向性 E",
  A: "宜人性 A",
  N: "神经质 N",
};

const CLOSING =
  "以上倾向只影响你的风格与判断偏好；若相互冲突，以先出现的描述为准；" +
  "不得因此违反游戏规则或泄露私有信息。";

// ---- PersonalitySpec 形状（与 app/agent/personality.py 的 pydantic 模型对应） ----
// 用 type 而非 interface：object 字面量类型才有隐式索引签名，可赋给 AgentProfile.personality。

export type PersonalityPresetShape =
  | { system: "MBTI"; value: string | Record<string, number> }
  | { system: "BIG_FIVE"; value: Record<string, number> };

export type PersonalitySpecShape = {
  description?: string | null;
  traits?: Record<string, number>;
  preset?: PersonalityPresetShape | null;
  style_notes?: string | null;
};

function band(strength: number): string {
  if (strength < 0.34) return "略微";
  if (strength < 0.67) return "比较";
  return "非常";
}

function traitLines(traits: Record<string, number>): string[] {
  const entries = Object.entries(traits).sort((a, b) =>
    a[1] !== b[1] ? b[1] - a[1] : a[0] < b[0] ? -1 : a[0] > b[0] ? 1 : 0,
  );
  return entries.map(([word, strength]) => {
    const prefix = `你${band(strength)}${word}`;
    const behavior = TRAIT_LEXICON[word];
    return behavior === undefined ? `${prefix}。` : `${prefix}：${behavior}。`;
  });
}

function presetLines(preset: PersonalityPresetShape): string[] {
  const lines: string[] = [];
  if (preset.system === "MBTI") {
    if (typeof preset.value === "string") {
      for (let i = 0; i < preset.value.length; i += 1) {
        const letter = preset.value[i] ?? "";
        const axis = MBTI_AXES[i] ?? "EI";
        const text = MBTI_TEXT[letter];
        if (text === undefined) continue;
        lines.push(`你${band(MBTI_DEFAULT_STRENGTH[axis] ?? 0.5)}倾向于${text}。`);
      }
    } else {
      // dict 形式按输入插入序出句——与后端一致，不按轴序重排
      for (const [letter, strength] of Object.entries(preset.value)) {
        const text = MBTI_TEXT[letter];
        if (text === undefined) continue;
        lines.push(`你${band(strength)}倾向于${text}。`);
      }
    }
    return lines;
  }
  for (const [key, strength] of Object.entries(preset.value)) {
    const pair = BIG_FIVE_TEXT[key];
    if (pair === undefined) continue;
    if (strength > 0.6) lines.push(`你${band(strength)}倾向于${pair[0]}。`);
    else if (strength < 0.4) lines.push(`你${band(1 - strength)}倾向于${pair[1]}。`);
    // 0.4–0.6：中性，不出句
  }
  return lines;
}

/** 只读预览：等价于后端 render_personality（顺序即优先级，末句固定）。 */
export function renderPersonalityPreview(spec: PersonalitySpecShape): string {
  const lines: string[] = [];
  if (spec.description) lines.push(`你的性格：${spec.description}`);
  lines.push(...traitLines(spec.traits ?? {}));
  if (spec.preset) lines.push(...presetLines(spec.preset));
  if (spec.style_notes) lines.push(`说话风格：${spec.style_notes}`);
  lines.push(CLOSING);
  return lines.join("\n");
}

/** 档案卡的一眼摘要：等价于后端 personality_summary。 */
export function personalitySummary(spec: PersonalitySpecShape | null | undefined): string {
  if (!spec) return "";
  if (spec.preset) {
    const value = spec.preset.value;
    if (typeof value === "string") return value;
    return Object.entries(value)
      .map(([k, v]) => `${k}${formatStrength(v)}`)
      .join(" ");
  }
  if (spec.description) {
    return spec.description.length <= 12 ? spec.description : `${spec.description.slice(0, 12)}…`;
  }
  const traits = Object.entries(spec.traits ?? {});
  if (traits.length > 0) {
    const best = traits.reduce((acc, cur) =>
      cur[1] > acc[1] || (cur[1] === acc[1] && cur[0] > acc[0]) ? cur : acc,
    );
    return best[0];
  }
  return spec.style_notes ?? "";
}

/** Python 的 `{v:g}`：0.9 → "0.9"、1 → "1"。 */
function formatStrength(v: number): string {
  return String(Number(v.toPrecision(6)));
}

/** 命中的护栏短语（仅前端提示，最终以后端 422 为准）。 */
export function forbiddenHits(text: string): string[] {
  return FORBIDDEN_PHRASES.filter((p) => text.includes(p));
}

// ---- 表单 ↔ spec ----

export interface TraitEntry {
  word: string;
  strength: number;
}

export type PersonalityForm = {
  description: string;
  traits: TraitEntry[];
  presetSystem: "none" | "MBTI" | "BIG_FIVE";
  /** 轴 → 选中的字母，如 {EI: "I"}；未选的轴不出现。 */
  mbti: Record<string, string>;
  bigFive: Record<string, number>;
  styleNotes: string;
};

export function emptyPersonalityForm(): PersonalityForm {
  return {
    description: "",
    traits: [],
    presetSystem: "none",
    mbti: {},
    bigFive: Object.fromEntries(BIG_FIVE_KEYS.map((k) => [k, 0.5])),
    styleNotes: "",
  };
}

/** 表单 → PersonalitySpec；四项全空 → null（不提交 personality 字段）。 */
export function toPersonalitySpec(form: PersonalityForm): PersonalitySpecShape | null {
  const description = form.description.trim();
  const styleNotes = form.styleNotes.trim();
  const traits: Record<string, number> = {};
  for (const t of form.traits) {
    const word = t.word.trim();
    if (word) traits[word] = t.strength;
  }
  const preset = toPreset(form);
  if (!description && !styleNotes && Object.keys(traits).length === 0 && preset === null) {
    return null;
  }
  const spec: PersonalitySpecShape = {};
  if (description) spec.description = description;
  if (Object.keys(traits).length > 0) spec.traits = traits;
  if (preset !== null) spec.preset = preset;
  if (styleNotes) spec.style_notes = styleNotes;
  return spec;
}

function toPreset(form: PersonalityForm): PersonalityPresetShape | null {
  if (form.presetSystem === "MBTI") {
    const letters = MBTI_AXES.map((axis) => form.mbti[axis]).filter(
      (l): l is string => l !== undefined && l !== "",
    );
    if (letters.length === 0) return null;
    // 四轴齐全 → 4 字母写法（隐式强度）；不齐 → dict 写法，按轴序给默认强度
    if (letters.length === MBTI_AXES.length) return { system: "MBTI", value: letters.join("") };
    const value: Record<string, number> = {};
    for (const axis of MBTI_AXES) {
      const letter = form.mbti[axis];
      if (letter) value[letter] = MBTI_DEFAULT_STRENGTH[axis] ?? 0.5;
    }
    return { system: "MBTI", value };
  }
  if (form.presetSystem === "BIG_FIVE") {
    const value: Record<string, number> = {};
    for (const key of BIG_FIVE_KEYS) value[key] = form.bigFive[key] ?? 0.5;
    return { system: "BIG_FIVE", value };
  }
  return null;
}

/** 既有档案 → 表单（编辑态）。未知形状按空表单处理，不抛错。 */
export function fromPersonalitySpec(spec: unknown): PersonalityForm {
  const form = emptyPersonalityForm();
  if (!spec || typeof spec !== "object") return form;
  const s = spec as PersonalitySpecShape;
  if (typeof s.description === "string") form.description = s.description;
  if (typeof s.style_notes === "string") form.styleNotes = s.style_notes;
  if (s.traits && typeof s.traits === "object") {
    form.traits = Object.entries(s.traits).map(([word, strength]) => ({
      word,
      strength: typeof strength === "number" ? strength : 0.5,
    }));
  }
  const preset = s.preset;
  if (preset && typeof preset === "object") {
    if (preset.system === "MBTI") {
      form.presetSystem = "MBTI";
      const letters =
        typeof preset.value === "string" ? preset.value.split("") : Object.keys(preset.value);
      for (const letter of letters) {
        const axis = MBTI_AXES.find((a) => a.includes(letter));
        if (axis) form.mbti[axis] = letter;
      }
    } else if (preset.system === "BIG_FIVE") {
      form.presetSystem = "BIG_FIVE";
      for (const key of BIG_FIVE_KEYS) {
        const v = preset.value[key];
        if (typeof v === "number") form.bigFive[key] = v;
      }
    }
  }
  return form;
}
