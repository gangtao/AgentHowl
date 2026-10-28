// 村镇选择器（规格 §4.5）：村镇公告 townNews 与墓地 graveyard。纯函数，只收 events + state（+ 服务端
// 观察给的 knownRoles 覆盖层），零 React、零视角判断。
//
// 出局轮次取事件之前最近一次 ROUND_STARTED 的 round（开局前按 1）；fixture 里 ROUND_STARTED 发生在
// 上一轮遗言 / 竞选之后、夜晚之前，所以「第 N 夜死亡」与「第 N 天放逐」用的是同一个 round 计数。

import { aliveSeats, rolesKnown } from "../engine/select";
import type {
  DeathAnnouncedPayload,
  Event,
  GameState,
  HunterShotPayload,
  PlayerExiledPayload,
  RoleType,
  RoundStartedPayload,
  WolfSelfDestructPayload,
} from "../engine/types";

export type DeathCause = "night" | "exiled" | "shot" | "self_destruct";

export interface GraveRow {
  seat: number;
  name: string;
  role: RoleType | null;
  round: number;
  cause: DeathCause;
  /** 「第 N 夜死亡 / 第 N 天放逐 / 第 N 天被带走 / 第 N 天自爆」 */
  when: string;
}

function whenOf(cause: DeathCause, round: number): string {
  switch (cause) {
    case "night":
      return `第 ${round} 夜死亡`;
    case "exiled":
      return `第 ${round} 天放逐`;
    case "shot":
      return `第 ${round} 天被带走`;
    case "self_destruct":
      return `第 ${round} 天自爆`;
  }
}

function roleOf(
  state: GameState,
  seat: number,
  knownRoles: Record<number, RoleType>,
): RoleType | null {
  if (rolesKnown(state)) return state.players.find((p) => p.seat === seat)?.role ?? null;
  return knownRoles[seat] ?? null;
}

function nameOf(state: GameState, seat: number): string {
  return state.players.find((p) => p.seat === seat)?.display_name ?? "";
}

/** 按出局事件顺序列出墓地；角色全知用 state，否则用 knownRoles，都没有则 null。 */
export function graveyard(
  events: readonly Event[],
  state: GameState,
  knownRoles: Record<number, RoleType> = {},
): GraveRow[] {
  const rows: GraveRow[] = [];
  let round = 1;
  const push = (seat: number, cause: DeathCause): void => {
    rows.push({
      seat,
      name: nameOf(state, seat),
      role: roleOf(state, seat, knownRoles),
      round,
      cause,
      when: whenOf(cause, round),
    });
  };
  for (const e of events) {
    switch (e.type) {
      case "ROUND_STARTED":
        round = (e.payload as RoundStartedPayload).round;
        break;
      case "WOLF_SELF_DESTRUCT":
        push((e.payload as WolfSelfDestructPayload).seat, "self_destruct");
        break;
      case "DEATH_ANNOUNCED":
        for (const s of (e.payload as DeathAnnouncedPayload).seats) push(s, "night");
        break;
      case "HUNTER_SHOT": {
        const v = (e.payload as HunterShotPayload).victim;
        if (v !== null) push(v, "shot");
        break;
      }
      case "PLAYER_EXILED": {
        const s = (e.payload as PlayerExiledPayload).seat;
        if (s !== null) push(s, "exiled");
        break;
      }
      default:
        break;
    }
  }
  return rows;
}

export interface NewsRow {
  k: string;
  v: string;
  tone: "normal" | "wolf" | "gold" | "muted";
}

function seatsZh(xs: readonly number[]): string {
  return xs.map((s) => `${s}号`).join("、");
}

/**
 * 村镇公告：昨夜（最近一次 DEATH_ANNOUNCED）→ 今日（最近一次 ROUND_STARTED 之后的放逐 / 带走 / 自爆）
 * → 警长 → 存活 → 阵营（仅角色全知）。
 */
export function townNews(events: readonly Event[], state: GameState): NewsRow[] {
  const rows: NewsRow[] = [];

  let lastDeaths: number[] | null = null;
  let roundStartIdx = -1;
  events.forEach((e, i) => {
    if (e.type === "DEATH_ANNOUNCED") lastDeaths = (e.payload as DeathAnnouncedPayload).seats;
    if (e.type === "ROUND_STARTED") roundStartIdx = i;
  });
  if (lastDeaths !== null) {
    const deaths: number[] = lastDeaths;
    rows.push(
      deaths.length === 0
        ? { k: "昨夜", v: "平安夜", tone: "muted" }
        : { k: "昨夜", v: `${seatsZh(deaths)} 死亡`, tone: "wolf" },
    );
  }

  const today: string[] = [];
  for (const e of events.slice(roundStartIdx + 1)) {
    if (e.type === "PLAYER_EXILED") {
      const s = (e.payload as PlayerExiledPayload).seat;
      today.push(s === null ? "无人出局" : `${s}号 被放逐`);
    } else if (e.type === "HUNTER_SHOT") {
      const v = (e.payload as HunterShotPayload).victim;
      if (v !== null) today.push(`${v}号 被带走`);
    } else if (e.type === "WOLF_SELF_DESTRUCT") {
      today.push(`${(e.payload as WolfSelfDestructPayload).seat}号 自爆`);
    }
  }
  if (today.length > 0) rows.push({ k: "今日", v: today.join(" · "), tone: "normal" });

  rows.push({
    k: "警长",
    v: state.sheriff_seat !== null ? `${state.sheriff_seat}号` : "无",
    tone: state.sheriff_seat !== null ? "gold" : "muted",
  });
  rows.push({
    k: "存活",
    v: `${aliveSeats(state).length}/${state.players.length}`,
    tone: "normal",
  });
  if (rolesKnown(state)) {
    const wolvesAlive = state.players.filter((p) => p.alive && p.faction === "WOLF").length;
    const goodAlive = aliveSeats(state).length - wolvesAlive;
    rows.push({ k: "阵营", v: `狼 ${wolvesAlive} / 好人 ${goodAlive}`, tone: "wolf" });
  }
  return rows;
}

