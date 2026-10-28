// LobbyScrollCard（规格 §5 右栏，设计稿 1c / 1d）：「开局卷轴」木牌卡——汇总两行、语音 / 旁白复选、
// 篝火按钮「点燃篝火 · 开局」。三步都在；按钮只在父级判定可开局（第 3 步）时亮。
//
// 旁白依赖语音：取消语音时父级负责清掉 narration（Lobby 现有联动，issue #110）。

import type { TtsStatus } from "../../api/rest";
import { summaryMain, summarySub } from "../../lib/lobbyText";
import type { AssignmentSummary } from "../../lib/seats";
import styles from "./LobbyScrollCard.module.css";

export interface LobbyScrollCardProps {
  numPlayers: number | null;
  presetZh: string | null;
  summary: AssignmentSummary;
  fillName: string | null;
  seed: string;
  tts: TtsStatus;
  voice: boolean;
  narration: boolean;
  onVoice(v: boolean): void;
  onNarration(v: boolean): void;
  /** 第 2 步为 true：多一段 12px 规则说明。 */
  showNotes: boolean;
  canLaunch: boolean;
  creating: boolean;
  onLaunch(): void;
}

export default function LobbyScrollCard({
  numPlayers,
  presetZh,
  summary,
  fillName,
  seed,
  tts,
  voice,
  narration,
  onVoice,
  onNarration,
  showNotes,
  canLaunch,
  creating,
  onLaunch,
}: LobbyScrollCardProps): JSX.Element {
  return (
    <aside className={`ah-wood ${styles.card}`} aria-label="开局卷轴">
      <span className={`card-kicker ${styles.kicker}`}>开局卷轴</span>
      <span className={styles.main}>{summaryMain(numPlayers, summary, fillName)}</span>
      <span className={styles.sub}>{summarySub(presetZh, seed)}</span>
      {tts.enabled && (
        <div className={styles.checks}>
          <label className={styles.check}>
            <input
              type="checkbox"
              checked={voice}
              disabled={!tts.ok}
              onChange={(e) => onVoice(e.target.checked)}
            />
            语音播报{tts.ok ? "" : `（TTS 不可用：${tts.detail ?? ""}）`}
          </label>
          <label className={styles.check}>
            <input
              type="checkbox"
              checked={voice && narration}
              disabled={!tts.ok || !voice}
              onChange={(e) => onNarration(e.target.checked)}
            />
            旁白（GM 播报阶段 / 结算 / 投票结果）
          </label>
        </div>
      )}
      <button
        type="button"
        className={`btn btn-primary ${styles.launch}`}
        disabled={!canLaunch || creating}
        onClick={onLaunch}
      >
        {creating ? "创建中…" : "点燃篝火 · 开局"}
      </button>
      {showNotes && (
        <div className={styles.notes}>
          <span>同一档案可放多个座位；配置了 memory_id 的档案只能占一个座位。</span>
          <span>「我自己」只能占一个座位；建局后你以该座位入座并直接进入玩家页。</span>
        </div>
      )}
    </aside>
  );
}
