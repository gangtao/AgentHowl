// 对局记录（规格 §6.2，设计稿 8a 右下）：当前视图可见的全部事件倒序混排——发言 / 投票 / 夜间 / 流程，
// 按日夜分隔，顶部按组过滤；回放时游标所在条目高亮并滚到可见。
// 零过滤：entries 是 GamePage 用已按游标截断的事件流算出来的全量映射；「验人」页签出不出现只看有没有 seer 条目。

import { useEffect, useMemo, useRef, useState } from "react";
import { ROLE_ZH } from "../../engine/phases";
import { rolesKnown } from "../../engine/select";
import type { GameState, RoleType } from "../../engine/types";
import type { LogEntry, LogGroup } from "../../lib/gameLog";
import RoleToken from "../RoleToken/RoleToken";
import { seatColor } from "../seatColor";
import styles from "./GameLog.module.css";

export interface GameLogProps {
  entries: LogEntry[];
  /** 只用于取座位名字、阵营色与角色是否全知。 */
  state: GameState;
  /** 回放游标；非 null 时 seq === cursor 的条目高亮。 */
  cursor: number | null;
  avatars?: Record<number, string>;
  /** 服务端观察给出的角色覆盖层（本人 / 狼队友）。 */
  knownRoles?: Record<number, RoleType>;
}

type Filter = "all" | LogGroup;

const TABS: [Filter, string][] = [
  ["all", "全部"],
  ["speech", "发言"],
  ["vote", "投票"],
  ["night", "夜晚"],
  ["seer", "验人"],
];

/** 事件行图标：flow / vote 用字形；night / seer 行由调用处换成角色徽记。 */
const GLYPH: Record<string, string> = {
  天亮: "☀",
  结算: "☾",
  警长: "★",
  警徽: "★",
  票型: "⚖",
  投票: "⚖",
  放逐: "✕",
  开枪: "➶",
  自爆: "💥",
  翻牌: "◇",
  竞选: "✦",
  上警: "✦",
  不上警: "✦",
  退水: "✦",
  方向: "✦",
  终局: "⚑",
};

const NIGHT_ROLE: Record<string, RoleType> = {
  守护: "GUARD",
  刀口: "WEREWOLF",
  解药: "WITCH",
  毒药: "WITCH",
  验人: "SEER",
};

/** 距顶部多少像素以内算「贴着顶」——否则新条目到达时只累计未读。 */
const STICK_PX = 48;

export default function GameLog({
  entries,
  state,
  cursor,
  avatars = {},
  knownRoles = {},
}: GameLogProps): JSX.Element {
  const [filter, setFilter] = useState<Filter>("all");
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const [unread, setUnread] = useState(0);
  const prevTopSeq = useRef<number | null>(null);

  const hasSeer = entries.some((e) => e.group === "seer");
  const shown = useMemo(
    () => (filter === "all" ? entries : entries.filter((e) => e.group === filter)),
    [entries, filter],
  );
  const nameOf = new Map(state.players.map((p) => [p.seat, p.display_name]));
  const allKnown = rolesKnown(state);
  const roleOf = (seat: number | null): RoleType | null => {
    if (seat === null) return null;
    if (allKnown) return state.players.find((p) => p.seat === seat)?.role ?? null;
    return knownRoles[seat] ?? null;
  };

  // 新条目在顶部：贴顶时什么都不做；用户滚到下面看旧记录时累计未读
  useEffect(() => {
    const top = entries[0]?.seq ?? null;
    const prev = prevTopSeq.current;
    prevTopSeq.current = top;
    const el = scrollRef.current;
    if (el === null || prev === null || top === null || top <= prev) return;
    if (el.scrollTop > STICK_PX) {
      setUnread((n) => n + entries.filter((e) => e.seq > prev).length);
    }
  }, [entries]);

  // 回放游标变化（拖动 / 单步 / 播放推进）：条目已按游标截断，最新 ≤ 游标的那条就在顶上，回到顶部即可见；
  // 直播（cursor 为 null）不动，用户滚到下面看旧记录时不被打断
  useEffect(() => {
    if (cursor === null) return;
    const el = scrollRef.current;
    if (el !== null) el.scrollTop = 0;
    setUnread(0);
  }, [cursor]);

  const toTop = (): void => {
    const el = scrollRef.current;
    if (el !== null) el.scrollTop = 0;
    setUnread(0);
  };
  const onScroll = (): void => {
    const el = scrollRef.current;
    if (el !== null && el.scrollTop <= STICK_PX) setUnread(0);
  };

  return (
    <section className={styles.root} aria-label="对局记录">
      <header className={styles.head}>
        <span className={styles.title}>对局记录</span>
        <span className={styles.sub}>你可见的全部事件 · 最新在上</span>
        <span className={styles.spacer} />
        <div className={styles.tabs} role="tablist" aria-label="记录过滤">
          {TABS.filter(([id]) => id !== "seer" || hasSeer).map(([id, label]) => (
            <button
              key={id}
              type="button"
              role="tab"
              className={styles.tab}
              aria-selected={filter === id}
              onClick={() => setFilter(id)}
            >
              {label}
            </button>
          ))}
        </div>
      </header>
      <div className={styles.scroll} ref={scrollRef} onScroll={onScroll} data-testid="log-scroll">
        {shown.length === 0 ? (
          <div className={styles.empty}>尚无记录</div>
        ) : (
          shown.map((e, i) => {
            const prevDay = i > 0 ? shown[i - 1]!.day : null;
            const divider = prevDay !== e.day;
            const isCurrent = cursor !== null && e.seq === cursor;
            const isPrivate = e.visibility !== "PUBLIC";
            const colorVar = `var(${e.color})`;
            return (
              <div key={e.seq}>
                {divider && (
                  <div className={styles.day} data-testid="log-day">
                    <span className={styles.dayLine} />
                    <span className={styles.dayText}>{e.day}</span>
                    <span className={styles.dayLine} />
                  </div>
                )}
                {e.speech !== undefined ? (
                  <article
                    className={styles.speech}
                    data-seq={e.seq}
                    data-group={e.group}
                    data-current={isCurrent ? "true" : undefined}
                    data-private={isPrivate ? "true" : undefined}
                    style={isPrivate ? { borderLeftColor: colorVar } : undefined}
                  >
                    <RoleToken
                      role={roleOf(e.actor_seat)}
                      size={36}
                      initial={e.actor_seat !== null ? (nameOf.get(e.actor_seat) ?? "").slice(0, 1) : "?"}
                      avatar={e.actor_seat !== null ? (avatars[e.actor_seat] ?? null) : null}
                    />
                    <div className={styles.speechBody}>
                      <div className={styles.speechHead}>
                        <span className={styles.who} style={{ color: seatColor(state, e.actor_seat) }}>
                          {e.actor_seat !== null ? `${e.actor_seat}号 ${nameOf.get(e.actor_seat) ?? ""}` : "—"}
                        </span>
                        {e.speech.kind === "last_words" && (
                          <span className={styles.tagWolf}>遗言</span>
                        )}
                        {e.speech.claim !== null && (
                          <span className={styles.tagGold}>自称 {ROLE_ZH[e.speech.claim]}</span>
                        )}
                        {e.speech.badgeFlow.length > 0 && (
                          <span className="tag tag-neutral">警徽流 {e.speech.badgeFlow.join(" → ")}</span>
                        )}
                        <span className={styles.seq}>#{e.seq}</span>
                      </div>
                      <p className={styles.speechText}>{e.speech.content}</p>
                    </div>
                  </article>
                ) : (
                  <article
                    className={styles.event}
                    data-seq={e.seq}
                    data-group={e.group}
                    data-current={isCurrent ? "true" : undefined}
                    data-private={isPrivate ? "true" : undefined}
                    style={isPrivate ? { borderLeftColor: colorVar } : undefined}
                  >
                    <span className={styles.icon} style={{ color: colorVar }} aria-hidden="true">
                      {NIGHT_ROLE[e.label] !== undefined ? (
                        <RoleToken role={NIGHT_ROLE[e.label] as RoleType} variant="outline" size={24} />
                      ) : (
                        (GLYPH[e.label] ?? "·")
                      )}
                    </span>
                    <span className={styles.eventBody}>
                      <span className={styles.label} style={{ borderColor: colorVar, color: colorVar }}>
                        {e.label}
                      </span>
                      <span className={styles.eventText}>{e.text}</span>
                      <span className={styles.seq}>#{e.seq}</span>
                    </span>
                  </article>
                )}
              </div>
            );
          })
        )}
      </div>
      {unread > 0 && (
        <button type="button" className={`btn btn-secondary ${styles.unread}`} onClick={toTop}>
          ↑ 有 {unread} 条新记录
        </button>
      )}
    </section>
  );
}

