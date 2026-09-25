// PersonalityEditor（设计稿 2c 第 3 组）：描述 + 特质 chips/滑块 + 预设（MBTI / Big Five）
// + 说话风格 + 右侧只读预览卡。所有文案来自 lib/personality.ts（抄录后端 personality.py）。
//
// 护栏短语命中只做红字提示：最终以后端 422 为准（spec §7.2b）。

import { useId, useState } from "react";
import {
  BIG_FIVE_KEYS,
  BIG_FIVE_ZH,
  MAX_DESCRIPTION,
  MAX_STYLE_NOTES,
  MAX_TRAIT_LEN,
  MBTI_AXES,
  TRAIT_WORDS,
  forbiddenHits,
  renderPersonalityPreview,
  toPersonalitySpec,
  type PersonalityForm,
} from "../../lib/personality";
import styles from "./PersonalityEditor.module.css";

export interface PersonalityEditorProps {
  value: PersonalityForm;
  onChange(next: PersonalityForm): void;
}

export default function PersonalityEditor({
  value,
  onChange,
}: PersonalityEditorProps): JSX.Element {
  const uid = useId();
  const [custom, setCustom] = useState("");
  const [customOpen, setCustomOpen] = useState(false);

  const descHits = forbiddenHits(value.description);
  const styleHits = forbiddenHits(value.styleNotes);
  const spec = toPersonalitySpec(value);
  const selectedWords = new Set(value.traits.map((t) => t.word));
  // 后端对 traits 的**键**同样跑 _check_guardrail（personality.py::_check_traits）
  const traitHits = [...new Set(value.traits.flatMap((t) => forbiddenHits(t.word)))];
  const customHits = forbiddenHits(custom);

  function toggleTrait(word: string): void {
    onChange({
      ...value,
      traits: selectedWords.has(word)
        ? value.traits.filter((t) => t.word !== word)
        : [...value.traits, { word, strength: 0.5 }],
    });
  }

  function setStrength(word: string, strength: number): void {
    onChange({
      ...value,
      traits: value.traits.map((t) => (t.word === word ? { ...t, strength } : t)),
    });
  }

  /** letter 为空串 = 清空该轴（不表态）。 */
  function setAxis(axis: string, letter: string): void {
    const mbti = { ...value.mbti };
    if (letter) mbti[axis] = letter;
    else delete mbti[axis];
    onChange({ ...value, mbti });
  }

  function addCustom(): void {
    const word = custom.trim();
    if (!word || word.length > MAX_TRAIT_LEN || selectedWords.has(word)) return;
    onChange({ ...value, traits: [...value.traits, { word, strength: 0.5 }] });
    setCustom("");
    setCustomOpen(false);
  }

  return (
    <div className={styles.root}>
      <div className={styles.main}>
        <div className="field">
          <label htmlFor={`${uid}-desc`}>
            描述
            <span
              className={
                value.description.length > MAX_DESCRIPTION
                  ? `${styles.counter} ${styles.errText}`
                  : styles.counter
              }
            >
              {value.description.length} / {MAX_DESCRIPTION}
            </span>
          </label>
          <textarea
            id={`${uid}-desc`}
            className="input"
            rows={3}
            value={value.description}
            placeholder="话少，只在有逻辑链时开口。倾向相信查验而非情绪；被质疑时不急于自证。"
            onChange={(e) => onChange({ ...value, description: e.target.value })}
          />
          {value.description.length > MAX_DESCRIPTION && (
            <span className={styles.err}>超过 {MAX_DESCRIPTION} 字，后端会 422 拒绝。</span>
          )}
          {descHits.length > 0 && (
            <span className={styles.err}>护栏：描述含「{descHits.join("」「")}」— 保存将被后端 422 拒绝</span>
          )}
        </div>

        <div className={styles.chips}>
          {TRAIT_WORDS.map((word) => (
            <button
              key={word}
              type="button"
              className={`${styles.chip} ${selectedWords.has(word) ? styles.chipOn : ""}`}
              aria-pressed={selectedWords.has(word)}
              onClick={() => toggleTrait(word)}
            >
              {word}
            </button>
          ))}
          {customOpen ? (
            <span className={styles.customBox}>
              <input
                className={`input ${styles.customInput}`}
                value={custom}
                maxLength={MAX_TRAIT_LEN}
                aria-label="自定义特质"
                placeholder={`≤ ${MAX_TRAIT_LEN} 字`}
                onChange={(e) => setCustom(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    e.preventDefault();
                    addCustom();
                  }
                }}
              />
              <button type="button" className="btn btn-ghost" onClick={addCustom}>
                加入
              </button>
            </span>
          ) : (
            <button type="button" className={styles.chip} onClick={() => setCustomOpen(true)}>
              + 自定义
            </button>
          )}
        </div>

        {customHits.length > 0 && (
          <span className={styles.err}>
            护栏：自定义特质含「{customHits.join("」「")}」— 加入后保存将被后端 422 拒绝
          </span>
        )}
        {traitHits.length > 0 && (
          <span className={styles.err}>
            护栏：特质词含「{traitHits.join("」「")}」— 保存将被后端 422 拒绝
          </span>
        )}

        {value.traits.length > 0 && (
          <div className={styles.sliders}>
            {value.traits.map((t) => (
              <div key={t.word} className={styles.sliderRow}>
                <span className={styles.sliderName}>{t.word}</span>
                <input
                  type="range"
                  min={0}
                  max={1}
                  step={0.1}
                  value={t.strength}
                  aria-label={`${t.word} 强度`}
                  onChange={(e) => setStrength(t.word, Number(e.target.value))}
                />
                <span className={styles.sliderValue}>{t.strength.toFixed(1)}</span>
              </div>
            ))}
          </div>
        )}

        <div className={styles.presetRow}>
          <span className="seg" role="group" aria-label="人格预设">
            {(["none", "MBTI", "BIG_FIVE"] as const).map((sys) => (
              <label key={sys} className="seg-opt">
                <input
                  type="radio"
                  name={`${uid}-preset`}
                  checked={value.presetSystem === sys}
                  onChange={() => onChange({ ...value, presetSystem: sys })}
                />
                {sys === "none" ? "无预设" : sys === "MBTI" ? "MBTI" : "Big Five"}
              </label>
            ))}
          </span>
          {value.presetSystem === "MBTI" &&
            MBTI_AXES.map((axis) => (
              <span key={axis} className="seg" role="group" aria-label={`MBTI ${axis}`}>
                {/* 末项「—」= 这一轴不表态：后端支持部分轴（dict 写法），UI 也要能退回未选 */}
                {[axis[0] ?? "", axis[1] ?? "", ""].map((letter) => (
                  <label key={letter || "none"} className="seg-opt">
                    <input
                      type="radio"
                      name={`${uid}-${axis}`}
                      checked={(value.mbti[axis] ?? "") === letter}
                      onChange={() => setAxis(axis, letter)}
                    />
                    {letter || "—"}
                  </label>
                ))}
              </span>
            ))}
        </div>

        {value.presetSystem === "BIG_FIVE" && (
          <div className={styles.sliders}>
            {BIG_FIVE_KEYS.map((key) => (
              <div key={key} className={styles.sliderRow}>
                <span className={styles.sliderName}>{BIG_FIVE_ZH[key]}</span>
                <input
                  type="range"
                  min={0}
                  max={1}
                  step={0.1}
                  value={value.bigFive[key] ?? 0.5}
                  aria-label={`${BIG_FIVE_ZH[key] ?? key} 强度`}
                  onChange={(e) =>
                    onChange({ ...value, bigFive: { ...value.bigFive, [key]: Number(e.target.value) } })
                  }
                />
                <span className={styles.sliderValue}>{(value.bigFive[key] ?? 0.5).toFixed(1)}</span>
              </div>
            ))}
          </div>
        )}

        <div className="field">
          <label htmlFor={`${uid}-style`}>
            说话风格
            <span className={styles.counter}>
              {value.styleNotes.length} / {MAX_STYLE_NOTES}
            </span>
          </label>
          <input
            id={`${uid}-style`}
            className="input"
            value={value.styleNotes}
            placeholder="短句，少形容词，先结论后理由"
            onChange={(e) => onChange({ ...value, styleNotes: e.target.value })}
          />
          {value.styleNotes.length > MAX_STYLE_NOTES && (
            <span className={styles.err}>超过 {MAX_STYLE_NOTES} 字，后端会 422 拒绝。</span>
          )}
          {styleHits.length > 0 && (
            <span className={styles.err}>护栏：说话风格含「{styleHits.join("」「")}」</span>
          )}
        </div>
      </div>

      <aside className={styles.preview} aria-label="人格预览">
        <span className={styles.previewKicker}>预览 · render_personality</span>
        <pre className={styles.previewText}>
          {spec === null ? "（未配置人格：不提交 personality 字段）" : renderPersonalityPreview(spec)}
        </pre>
        <span className={styles.previewFoot}>只读预览，最终文案以后端为准</span>
      </aside>
    </div>
  );
}
