// 对局记录条目选择器（规格 §6.1）：事件流 → 倒序的记录条目（分组 / 两字签 / 主色 / 正文 / 日夜标签）。
// 纯函数，零 React。零过滤：条目有多少只看传进来多少事件；「验人」是不是只有我的，由服务端可见性决定。
// 日夜标签来自 dayScan（只从事件流推导，规格 R12），上帝流与玩家流对同一条公开事件给同一标签。

import { ROLE_ZH } from "../engine/phases";
import { renderEventText } from "../engine/select";
import type {
  Event,
  EventType,
  LastWordsPayload,
  PlayerSpokePayload,
  RoleType,
  SheriffCandidacyPayload,
  Visibility,
  VoteResultPayload,
} from "../engine/types";
import { NIGHT_EVENT_TYPES, dayLabel, dayMarks } from "./dayScan";

export type LogGroup = "speech" | "vote" | "night" | "seer" | "flow";

export interface LogSpeech {
  content: string;
  claim: RoleType | null;
  badgeFlow: number[];
  kind: "speech" | "last_words";
}

export interface LogEntry {
  seq: number;
  type: EventType;
  group: LogGroup;
  /** 两字签：发言 / 遗言 / 上警 / 退水 / 竞选 / 警长 / 方向 / 警徽 / 投票 / 票型 / 放逐 / 天亮 / 开枪 / 自爆 / 翻牌 /
   *  守护 / 刀口 / 解药 / 毒药 / 验人 / 结算 / 发牌 / 跳过 / 开局 / 终局 */
  label: string;
  /** 行的主色（CSS 变量名，如 "--ah-wolf"）：签边框 / 图标 / 私有行左边线共用。 */
  color: string;
  /** renderEventText 去掉【…】/ [GM] / 缩进前缀后的正文（发言 / 遗言行不用，正文在 speech.content）。 */
  text: string;
  actor_seat: number | null;
  visibility: Visibility;
  speech?: LogSpeech;
  /** 「开局」/「第 N 夜」/「第 N 天」：这条事件发生时所处的日夜。 */
  day: string;
}

/** 不入记录：日夜由分隔线承担，投票开始由票型行承担。 */
const SKIPPED: ReadonlySet<EventType> = new Set<EventType>([
  "ROUND_STARTED",
  "PHASE_CHANGED",
  "VOTE_STARTED",
]);

interface Tagging {
  label: string;
  group: LogGroup;
  color: string;
}

const MUTED = "--ah-text-muted";

const TAGS: Partial<Record<EventType, Tagging>> = {
  PLAYER_SPOKE: { label: "发言", group: "speech", color: "--ah-gold" },
  LAST_WORDS: { label: "遗言", group: "speech", color: "--ah-wolf" },

  SHERIFF_CANDIDACY: { label: "上警", group: "vote", color: "--ah-gold" },
  SHERIFF_WITHDREW: { label: "退水", group: "vote", color: "--ah-gold" },
  ELECTION_STAGE_CHANGED: { label: "竞选", group: "vote", color: "--ah-gold" },
  SHERIFF_VOTE_STARTED: { label: "竞选", group: "vote", color: "--ah-gold" },
  SHERIFF_VOTE_CAST: { label: "投票", group: "vote", color: "--ah-gold" },
  SHERIFF_ELECTED: { label: "警长", group: "vote", color: "--ah-gold" },
  SHERIFF_DIRECTION_SET: { label: "方向", group: "vote", color: "--ah-gold" },
  BADGE_PASSED: { label: "警徽", group: "vote", color: "--ah-gold" },
  SHERIFF_BADGE_LOST: { label: "警徽", group: "vote", color: "--ah-gold" },

  VOTE_CAST: { label: "投票", group: "vote", color: "--ah-fire" },
  VOTE_RESULT: { label: "票型", group: "vote", color: "--ah-fire" },
  PLAYER_EXILED: { label: "放逐", group: "vote", color: "--ah-wolf" },
  IDIOT_REVEALED: { label: "翻牌", group: "vote", color: "--ah-fire" },

  DEATH_ANNOUNCED: { label: "天亮", group: "flow", color: "--ah-ok" },
  HUNTER_SHOT: { label: "开枪", group: "flow", color: "--ah-god" },
  WOLF_SELF_DESTRUCT: { label: "自爆", group: "flow", color: "--ah-wolf" },

  GUARD_PROTECTED: { label: "守护", group: "night", color: "--ah-line-guard" },
  WOLF_KILL_PROPOSED: { label: "刀口", group: "night", color: "--ah-wolf" },
  WOLF_KILL_DECIDED: { label: "刀口", group: "night", color: "--ah-wolf" },
  WOLF_KILL_REVOTE: { label: "刀口", group: "night", color: "--ah-wolf" },
  WITCH_SAVED: { label: "解药", group: "night", color: "--ah-line-save" },
  WITCH_POISONED: { label: "毒药", group: "night", color: "--ah-line-poison" },
  WITCH_POTION_CONSUMED: { label: "毒药", group: "night", color: "--ah-line-poison" },
  NIGHT_RESOLVED: { label: "结算", group: "night", color: "--ah-ok" },
  SEER_CHECKED: { label: "验人", group: "seer", color: "--ah-line-seer" },

  GAME_CREATED: { label: "开局", group: "flow", color: MUTED },
  GAME_STARTED: { label: "开局", group: "flow", color: MUTED },
  ROLES_ASSIGNED: { label: "发牌", group: "flow", color: MUTED },
  ROLE_SKIPPED: { label: "跳过", group: "flow", color: MUTED },
  GAME_OVER: { label: "终局", group: "flow", color: "--ah-gold" },
};

const FALLBACK: Tagging = { label: "事件", group: "flow", color: MUTED };

/** 去掉 render.py 风格的前缀：【阶段】/ [GM] / 两空格缩进 / 💥。 */
const PREFIX = /^(【[^】]*】|\[GM\] |\s+|💥 )+/;

function seatsZh(xs: readonly number[]): string {
  return xs.map((s) => `${s}号`).join("、");
}

function tagOf(e: Event): Tagging {
  const base = TAGS[e.type] ?? FALLBACK;
  if (e.type === "SHERIFF_CANDIDACY" && !(e.payload as SheriffCandidacyPayload).running) {
    return { ...base, label: "不上警" };
  }
  if (e.type === "DEATH_ANNOUNCED" && (e.payload as { seats: number[] }).seats.length > 0) {
    return { ...base, color: "--ah-wolf" };
  }
  if (e.type === "NIGHT_RESOLVED" && (e.payload as { deaths: number[] }).deaths.length > 0) {
    return { ...base, color: "--ah-err" };
  }
  if (NIGHT_EVENT_TYPES.has(e.type) && base.group !== "night" && base.group !== "seer") {
    return { ...base, group: "night" };
  }
  return base;
}

function textOf(e: Event): string {
  if (e.type === "VOTE_RESULT") {
    const vr = e.payload as VoteResultPayload;
    const tally = vr.tally.map(([t, n]) => `${t}号 ·${n}`).join(" ｜ ");
    if (tally.length === 0) return "无有效票 → 无人出局";
    const outcome =
      vr.exiled !== null
        ? `→ ${vr.exiled}号 出局`
        : vr.tie_seats.length > 0
          ? `→ 平票 ${seatsZh(vr.tie_seats)}`
          : "→ 无人出局";
    return `${tally} ${outcome}`;
  }
  return renderEventText(e).replace(PREFIX, "");
}

function speechOf(e: Event): LogSpeech | undefined {
  if (e.type === "PLAYER_SPOKE") {
    const sp = e.payload as PlayerSpokePayload;
    return {
      content: sp.content,
      claim: sp.claim_role ?? null,
      badgeFlow: sp.badge_flow ?? [],
      kind: "speech",
    };
  }
  if (e.type === "LAST_WORDS") {
    const lw = e.payload as LastWordsPayload;
    return { content: lw.content, claim: null, badgeFlow: [], kind: "last_words" };
  }
  return undefined;
}

/** 倒序（最新在上）；跳过 ROUND_STARTED / PHASE_CHANGED / VOTE_STARTED。 */
export function logEntries(events: readonly Event[]): LogEntry[] {
  const marks = dayMarks(events);
  const out: LogEntry[] = [];
  events.forEach((e, i) => {
    if (SKIPPED.has(e.type)) return;
    const tag = tagOf(e);
    const entry: LogEntry = {
      seq: e.seq,
      type: e.type,
      group: tag.group,
      label: tag.label,
      color: tag.color,
      text: textOf(e),
      actor_seat: e.type === "LAST_WORDS" ? (e.payload as LastWordsPayload).seat : e.actor_seat,
      visibility: e.visibility,
      day: dayLabel(marks[i] ?? { kind: "start", n: 0 }),
    };
    const speech = speechOf(e);
    if (speech !== undefined) entry.speech = speech;
    out.push(entry);
  });
  return out.reverse();
}

/** 与 entries[0] 同一 day 的发言条目的自称，按座位去重保留最新，按座位升序（规格 R6）。 */
export function currentClaims(entries: readonly LogEntry[]): [number, RoleType][] {
  const first = entries[0];
  if (first === undefined) return [];
  const seen = new Map<number, RoleType>();
  // entries 是倒序：先遇到的就是最新的，后面的同座位不覆盖
  for (const x of entries) {
    if (x.day !== first.day) continue;
    if (x.speech?.kind !== "speech" || x.speech.claim === null || x.actor_seat === null) continue;
    if (!seen.has(x.actor_seat)) seen.set(x.actor_seat, x.speech.claim);
  }
  return [...seen.entries()].sort((a, b) => a[0] - b[0]);
}

/** 自称文案「5号 警长、2号 预言家」；供发言台提示行用。 */
export function claimsZh(claims: readonly [number, RoleType][]): string {
  return claims.map(([seat, role]) => `${seat}号 ${ROLE_ZH[role]}`).join("、");
}
