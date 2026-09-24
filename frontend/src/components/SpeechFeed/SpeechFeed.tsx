// 发言流（设计稿 1c/1d/1g/1h）：底部对齐 + 自动滚动 + 「↓ 有 N 条新消息」+ 回放截断提示。
// 零过滤：items 是 store 里已有事件的全量映射；cursor 之后的条目按回放语义截断（不是信息隔离）。

import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { ROLE_ZH, factionColorVar } from "../../engine/phases";
import type { SpeechItem } from "../../engine/select";
import type { Player } from "../../engine/types";
import type { Viewer } from "../../store/game";
import styles from "./SpeechFeed.module.css";

export interface SpeechFeedProps {
  items: SpeechItem[];
  /** 回放游标：非 null 时只渲染 seq ≤ cursor 的条目。 */
  cursor: number | null;
  players: Player[];
  viewer: Viewer;
  speakingSeat: number | null;
}

/** 距底部多少像素以内算「贴着底」——超过则暂停自动滚动并显示新消息胶囊。 */
const STICK_PX = 48;

export default function SpeechFeed({
  items,
  cursor,
  players,
  viewer,
  speakingSeat,
}: SpeechFeedProps): JSX.Element {
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const [stick, setStick] = useState(true);
  const [unread, setUnread] = useState(0);

  const shown = cursor === null ? items : items.filter((it) => it.seq <= cursor);
  const hidden = items.length - shown.length;
  const nameOf = new Map(players.map((p) => [p.seat, p.display_name]));
  const colorOf = (seat: number | null): string => {
    if (seat === null || viewer !== "GM") return "var(--color-neutral-300)";
    const p = players.find((x) => x.seat === seat);
    return p ? `var(${factionColorVar(p.role)})` : "var(--color-neutral-300)";
  };

  // 新条目到达：贴底则滚到底，否则累计未读数。
  useLayoutEffect(() => {
    const el = scrollRef.current;
    if (el === null) return;
    if (stick) {
      el.scrollTop = el.scrollHeight;
      setUnread(0);
    } else {
      setUnread((n) => n + 1);
    }
    // 只在条目数变化时触发（stick 变化由 onScroll 处理）
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [shown.length]);

  useEffect(() => {
    if (stick) setUnread(0);
  }, [stick]);

  const onScroll = (): void => {
    const el = scrollRef.current;
    if (el === null) return;
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight <= STICK_PX;
    setStick(atBottom);
  };

  const toBottom = (): void => {
    const el = scrollRef.current;
    if (el === null) return;
    el.scrollTop = el.scrollHeight;
    setStick(true);
    setUnread(0);
  };

  return (
    <div className={styles.root}>
      <div className={styles.scroll} ref={scrollRef} onScroll={onScroll}>
        <div className={styles.list}>
          {shown.map((it) => {
            if (it.kind === "system") {
              return (
                <div key={it.seq} className={styles.system} data-kind="system">
                  {it.text}
                </div>
              );
            }
            if (it.kind === "gm") {
              return (
                <div key={it.seq} className={styles.gm} data-kind="gm">
                  <span className={styles.gmTag}>[GM]</span>
                  <span>{it.text.replace(/^\[GM\]\s*/, "")}</span>
                </div>
              );
            }
            const seat = it.actor_seat;
            const speaking = seat !== null && seat === speakingSeat && it.kind === "speech";
            return (
              <div
                key={it.seq}
                className={`${styles.card} ${speaking ? styles.cardSpeaking : ""}`}
                data-kind={it.kind}
              >
                <div className={styles.who}>
                  <span className={styles.seat} style={{ color: colorOf(seat) }}>
                    {seat !== null ? `${seat}号` : "—"}
                  </span>
                  <span className={styles.name}>
                    {seat !== null ? (nameOf.get(seat) ?? "") : ""}
                  </span>
                </div>
                <div className={styles.body}>
                  <div className={styles.tags}>
                    {it.kind === "last_words" && (
                      <span className={`tag ${styles.tagLastWords}`}>遗言</span>
                    )}
                    {it.claim && (
                      <span className={`tag ${styles.tagClaim}`}>自称{ROLE_ZH[it.claim]}</span>
                    )}
                    {it.badgeFlow && it.badgeFlow.length > 0 && (
                      <span className="tag tag-neutral">警徽流 {it.badgeFlow.join(" → ")}</span>
                    )}
                    {speaking && <span className={`tag ${styles.tagSpeaking}`}>发言中</span>}
                  </div>
                  <p className={styles.text}>{it.content ?? it.text}</p>
                </div>
              </div>
            );
          })}
          {hidden > 0 && (
            <div className={styles.truncated}>— 之后 {hidden} 条事件在回放游标之后 —</div>
          )}
        </div>
      </div>
      {unread > 0 && !stick && (
        <button type="button" className={`btn btn-secondary ${styles.unread}`} onClick={toBottom}>
          ↓ 有 {unread} 条新消息
        </button>
      )}
    </div>
  );
}
