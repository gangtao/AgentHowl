// 回放条（设计稿 1c/1g/1j）：轮次分段着色的轨道 + 播放控制 + 倍速 + 「回到直播」+ 键盘。

import { useEffect, useRef, useState } from "react";
import type { RoundSegment } from "../../engine/select";
import styles from "./ReplayBar.module.css";

/** 倍速档位（设计稿 1g：0.5 / 1 / 2 / 4 / 8×）。 */
const SPEEDS = [0.5, 1, 2, 4, 8];

export interface ReplayBarProps {
  /** 回放游标 seq；null = 跟随最新。 */
  cursor: number | null;
  /** 事件流最后一条的 seq。 */
  total: number;
  playing: boolean;
  speed: number;
  segments: RoundSegment[];
  /** 是否直播模式（决定「回到直播」是否有意义）。 */
  live: boolean;
  onCursor(seq: number): void;
  onPlay(): void;
  onPause(): void;
  onSpeed(speed: number): void;
  onStep(delta: 1 | -1): void;
  onLive(): void;
}

/** 键盘快捷键在输入控件上不生效（含 contentEditable）。 */
function isTyping(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  const tag = target.tagName;
  return (
    tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || target.isContentEditable === true
  );
}

export default function ReplayBar({
  cursor,
  total,
  playing,
  speed,
  segments,
  live,
  onCursor,
  onPlay,
  onPause,
  onSpeed,
  onStep,
  onLive,
}: ReplayBarProps): JSX.Element {
  const [speedOpen, setSpeedOpen] = useState(false);
  const at = cursor ?? total;
  // 进度圆点与分段共用同一套坐标：都以事件流首个 seq 为原点，长度为 span，
  // 否则 firstSeq > 0 时圆点与分段边界会有系统性偏移。
  const firstSeq = segments.length > 0 ? (segments[0] as RoundSegment).fromSeq : 1;
  const span = Math.max(total - firstSeq + 1, 1);
  const pct = total > 0 ? Math.min(Math.max(((at - firstSeq + 1) / span) * 100, 0), 100) : 100;

  // 键盘回调存在 ref 里：GamePage 每次 render 都传新的箭头函数，直接进依赖会导致
  // 每帧解绑/重绑 document 监听器。
  const handlersRef = useRef({ playing, onPlay, onPause, onStep });
  handlersRef.current = { playing, onPlay, onPause, onStep };

  useEffect(() => {
    const onKey = (ev: KeyboardEvent): void => {
      if (isTyping(ev.target)) return;
      const h = handlersRef.current;
      if (ev.key === " ") {
        ev.preventDefault();
        if (h.playing) h.onPause();
        else h.onPlay();
      } else if (ev.key === "ArrowLeft") {
        ev.preventDefault();
        h.onStep(-1);
      } else if (ev.key === "ArrowRight") {
        ev.preventDefault();
        h.onStep(1);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  return (
    <div className={styles.root}>
      <span className={styles.buttons}>
        <button
          type="button"
          className={`btn btn-icon ${styles.icon}`}
          aria-label="回到开头"
          onClick={() => onCursor(0)}
        >
          ⏮
        </button>
        <button
          type="button"
          className={`btn btn-icon ${styles.icon}`}
          aria-label="上一条"
          onClick={() => onStep(-1)}
        >
          ◀
        </button>
        <button
          type="button"
          className={`btn btn-icon ${styles.icon} ${playing ? styles.iconActive : ""}`}
          aria-label={playing ? "暂停" : "播放"}
          onClick={() => (playing ? onPause() : onPlay())}
        >
          {playing ? "❚❚" : "▶"}
        </button>
        <button
          type="button"
          className={`btn btn-icon ${styles.icon}`}
          aria-label="下一条"
          onClick={() => onStep(1)}
        >
          ▶▶
        </button>
      </span>

      <div className={styles.track}>
        <div className={styles.ticks} aria-hidden="true">
          {segments.map((s) => (
            <span
              key={`${s.kind}-${s.fromSeq}`}
              className={s.kind === "night" ? styles.tickNight : styles.tickDay}
              style={{ width: `${((s.toSeq - s.fromSeq + 1) / span) * 100}%` }}
            />
          ))}
        </div>
        <span className={styles.progress} style={{ width: `${pct}%` }} aria-hidden="true" />
        <span
          className={`${styles.knob} ${cursor !== null ? styles.knobActive : ""}`}
          style={{ left: `calc(${pct}% - 7px)` }}
          aria-hidden="true"
        />
        <input
          className={styles.range}
          type="range"
          min={0}
          max={total}
          step={1}
          value={at}
          aria-label="回放进度"
          onChange={(e) => onCursor(Number(e.target.value))}
        />
      </div>

      <span className={styles.seq}>
        seq {at}/{total}
      </span>

      <span className={styles.speedWrap}>
        <button
          type="button"
          className={`btn btn-secondary ${styles.speed}`}
          aria-label="播放速度"
          aria-expanded={speedOpen}
          onClick={() => setSpeedOpen((v) => !v)}
        >
          {speed}× ▾
        </button>
        {speedOpen && (
          <span className={styles.speedMenu}>
            {SPEEDS.map((s) => (
              <button
                key={s}
                type="button"
                className={`btn ${styles.speedOpt} ${s === speed ? styles.speedOn : ""}`}
                onClick={() => {
                  onSpeed(s);
                  setSpeedOpen(false);
                }}
              >
                {s}×
              </button>
            ))}
          </span>
        )}
      </span>

      <button
        type="button"
        className={`btn btn-primary ${styles.live}`}
        disabled={!live || cursor === null}
        onClick={onLive}
      >
        回到直播
      </button>
      <span className={styles.hint}>空格 播放/暂停 · ←/→ 步进</span>
    </div>
  );
}
