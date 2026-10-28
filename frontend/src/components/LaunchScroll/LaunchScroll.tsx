// LaunchScroll（规格 §5 第 3 步，设计稿 4a）：640px 羊皮纸卷轴——顶部木轴条、「开 局 卷 轴」、副标、
// 两列定义表（剧本 / 座位 / seed / 我的显示名 / 发言时限 / 行动时限 / 播报）、底部返回 + 篝火按钮。
// 创建中与错误文案放卷轴底部。受控组件：显示名与时限由 Lobby 持有。

import type { PresetInfo } from "../../api/agents";
import { scrollSubtitle, type SeatTag } from "../../lib/lobbyText";
import styles from "./LaunchScroll.module.css";

export interface LaunchScrollProps {
  preset: PresetInfo;
  /** 「我自己」所在座位；全 AI 为 null。 */
  me: number | null;
  seatTags: SeatTag[];
  /** 未显式分配的座位数（随机 bot，或由 fill 填满）。 */
  rest: number;
  fillName: string | null;
  seed: string;
  displayName: string;
  displayNamePlaceholder: string;
  onDisplayName(v: string): void;
  speechTimeout: string;
  onSpeechTimeout(v: string): void;
  actionTimeout: string;
  onActionTimeout(v: string): void;
  voice: boolean;
  narration: boolean;
  ttsEnabled: boolean;
  /** createError 或 fillBlocked 文案；null 不渲染。 */
  error: string | null;
  canDiscard: boolean;
  onDiscard(): void;
  canLaunch: boolean;
  creating: boolean;
  onBack(): void;
  onLaunch(): void;
}

export default function LaunchScroll({
  preset,
  me,
  seatTags,
  rest,
  fillName,
  seed,
  displayName,
  displayNamePlaceholder,
  onDisplayName,
  speechTimeout,
  onSpeechTimeout,
  actionTimeout,
  onActionTimeout,
  voice,
  narration,
  ttsEnabled,
  error,
  canDiscard,
  onDiscard,
  canLaunch,
  creating,
  onBack,
  onLaunch,
}: LaunchScrollProps): JSX.Element {
  const restText =
    fillName !== null ? `其余 ${rest} 座由「${fillName}」填满` : `其余 ${rest} 座随机 bot`;
  return (
    <section className={`ah-parch ${styles.scroll}`} aria-label="开局卷轴">
      <div className={styles.roller} aria-hidden="true" />
      <h2 className={styles.title}>开 局 卷 轴</h2>
      <p className={styles.subtitle}>{scrollSubtitle(me)}</p>

      <dl className={styles.table}>
        <dt>剧本</dt>
        <dd>
          <span>{preset.description_zh}</span> <code className={styles.mono}>{preset.name}</code>
        </dd>

        <dt>座位</dt>
        <dd className={styles.seats}>
          {seatTags.map((t) => (
            <span key={t.seat} className={`tag ${t.kind === "me" ? "tag-gold" : styles.tagAgent}`}>
              {t.seat}号 {t.text}
            </span>
          ))}
          {rest > 0 && (
            <span className={styles.muted}>
              {seatTags.length > 0 ? "· " : ""}
              {restText}
            </span>
          )}
        </dd>

        <dt>seed</dt>
        <dd>{seed.trim() === "" ? "随机" : seed.trim()}</dd>

        {me !== null && (
          <>
            <dt>我的显示名</dt>
            <dd>
              <input
                className={`input ${styles.nameInput}`}
                aria-label="我的显示名"
                value={displayName}
                placeholder={displayNamePlaceholder}
                onChange={(e) => onDisplayName(e.target.value)}
              />
            </dd>

            <dt>发言时限</dt>
            <dd className={styles.inline}>
              <input
                className={`input ${styles.inputNum}`}
                aria-label="发言时限"
                inputMode="numeric"
                value={speechTimeout}
                onChange={(e) => onSpeechTimeout(e.target.value)}
              />
              <span className={styles.muted}>秒 · 一根蜡烛</span>
            </dd>

            <dt>行动时限</dt>
            <dd className={styles.inline}>
              <input
                className={`input ${styles.inputNum}`}
                aria-label="行动时限"
                inputMode="numeric"
                value={actionTimeout}
                onChange={(e) => onActionTimeout(e.target.value)}
              />
              <span className={styles.muted}>秒</span>
            </dd>
          </>
        )}

        {ttsEnabled && (
          <>
            <dt>播报</dt>
            <dd>
              {voice ? "☑" : "☐"} 语音播报 <span className={styles.muted}>·</span>{" "}
              {voice && narration ? "☑" : "☐"} 旁白（GM 播报阶段 / 结算 / 投票结果）
            </dd>
          </>
        )}
      </dl>

      {error !== null && (
        <div className={styles.error} role="alert">
          <span>{error}</span>
          {canDiscard && (
            <button type="button" className="btn btn-ghost" onClick={onDiscard}>
              删除这局
            </button>
          )}
        </div>
      )}

      <div className={styles.foot}>
        <button type="button" className={`btn btn-ghost ${styles.back}`} onClick={onBack}>
          ← 上一步 · 分配座位
        </button>
        <button
          type="button"
          className={`btn btn-primary ${styles.launch}`}
          disabled={!canLaunch || creating}
          onClick={onLaunch}
        >
          {creating ? "创建中…" : "点燃篝火 · 开局"}
        </button>
      </div>
    </section>
  );
}
