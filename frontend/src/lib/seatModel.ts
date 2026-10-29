// 座位模型（规格 §4.2）：圆桌与卡牌皮肤共用的唯一座位数据——位置、角色可见性、状态、徽章、可选性。
// 纯函数，零 React。
//
// 零过滤：角色来自两处且都是服务端给的数据——(1) state 里已应用 ROLES_ASSIGNED 时的 player.role；
// (2) `knownRoles` 覆盖层，由 GamePage 用 PlayerObservation 的 my_role / private.teammates 组装
// （reducer 要求 ROLES_ASSIGNED 全量，座位视角的 state 里没有任何角色，只能靠观察补）。
// 夜间暗化规则只看「这个座位的角色是否已知」：狼看狼队亮、上帝全亮、观众全暗，不看 viewer。

import { isNight } from "../engine/phases";
import { rolesKnown } from "../engine/select";
import type { GameState, RoleType } from "../engine/types";
import { seatStatus, type SeatStatus } from "./seatStatus";

export interface SeatBadges {
  /** state.sheriff_seat === seat */
  sheriff: boolean;
  /** 竞选阶段的候选人（已报名且未退水） */
  candidate: boolean;
  /** 当前得票（> 0 才有），否则 null */
  votes: number | null;
  /** 预言家已验签 */
  mark: "好人" | "狼人" | null;
  /** 夜间红签：「被刀」/「目标 · 2 票」 */
  tag: string | null;
}

export interface SeatModel {
  seat: number;
  name: string;
  /** 已知角色；未知为 null */
  role: RoleType | null;
  alive: boolean;
  me: boolean;
  speaking: boolean;
  /** 夜间且角色未知且存活 → 沉入阴影 */
  dim: boolean;
  /** 存活且在本回合可选目标里 */
  selectable: boolean;
  selected: boolean;
  /** 百分比坐标（0 号顶部，顺时针） */
  x: number;
  y: number;
  badges: SeatBadges;
  /** 名字下方的状态行（规格 §4.1：发言中 / 已发言 / 待发言 / 已投 / 出局 …，空串占位）。 */
  status: SeatStatus;
}

export interface SeatModelInput {
  state: GameState;
  me?: number | null;
  /** 服务端观察给出的角色覆盖层：{ [seat]: role }。 */
  knownRoles?: Record<number, RoleType>;
  speaking?: number | null;
  votes?: Record<number, number>;
  marks?: Record<number, "好人" | "狼人">;
  tags?: Record<number, string>;
  selectable?: readonly number[];
  selected?: number | null;
  /** 投票类阶段的票箱 voter → target（null = 弃票），给状态行用；非投票阶段省略。 */
  voteTargets?: Record<number, number | null>;
}

export interface SeatPosition {
  seat: number;
  x: number;
  y: number;
}

/** 0 号在顶部顺时针：50 + 41·cos/sin(-90° + i·360°/n)，保留两位小数。 */
export function seatPositions(seats: readonly number[]): SeatPosition[] {
  const n = seats.length;
  return seats.map((seat, i) => {
    const a = ((-90 + (i * 360) / n) * Math.PI) / 180;
    return {
      seat,
      x: +(50 + 41 * Math.cos(a)).toFixed(2),
      y: +(50 + 41 * Math.sin(a)).toFixed(2),
    };
  });
}

const ELECTION_PHASES = new Set(["SHERIFF_ELECTION", "SHERIFF_PK"]);

export function seatModel(input: SeatModelInput): SeatModel[] {
  const {
    state,
    me = null,
    knownRoles = {},
    speaking = null,
    votes = {},
    marks = {},
    tags = {},
    selectable = [],
    selected = null,
    voteTargets = {},
  } = input;
  const players = [...state.players].sort((a, b) => a.seat - b.seat);
  const pos = new Map(seatPositions(players.map((p) => p.seat)).map((p) => [p.seat, p]));
  const allKnown = rolesKnown(state);
  const night = isNight(state.phase);
  const electing = ELECTION_PHASES.has(state.phase);
  const selectableSet = new Set(selectable);

  return players.map((p) => {
    const role: RoleType | null = allKnown ? p.role : (knownRoles[p.seat] ?? null);
    const at = pos.get(p.seat) as SeatPosition;
    const n = votes[p.seat];
    return {
      seat: p.seat,
      name: p.display_name,
      role,
      alive: p.alive,
      me: me === p.seat,
      speaking: speaking === p.seat,
      dim: night && p.alive && role === null,
      selectable: p.alive && selectableSet.has(p.seat),
      selected: selected === p.seat,
      x: at.x,
      y: at.y,
      badges: {
        sheriff: state.sheriff_seat === p.seat,
        candidate:
          electing &&
          state.sheriff_candidates.includes(p.seat) &&
          !state.sheriff_withdrawn.includes(p.seat),
        votes: typeof n === "number" && n > 0 ? n : null,
        mark: marks[p.seat] ?? null,
        tag: tags[p.seat] ?? null,
      },
      status: seatStatus(state, p.seat, { speaking, voteTargets }),
    };
  });
}
