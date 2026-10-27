// 玩家视角的数据形状（issue #115）：对应 backend/app/engine/observation.py::PlayerObservation
// 与 app/api/rest.py::_your_turn_payload / ws.py 的 your_turn、action_result 帧。
// 零裁决：只是类型，前端不据此判断任何合法性。

import type { ElectionStage, RoleType } from "../engine/types";

/** `/state`（PLAYER 视角）把展示名补进 seats；WS your_turn 里的 observation 没有 display_name。 */
export interface ObservedSeat {
  seat: number;
  alive: boolean;
  is_sheriff: boolean;
  idiot_revealed: boolean;
  display_name?: string;
}

export interface PlayerObservation {
  game_id: string;
  state_version: number;
  my_seat: number;
  my_role: RoleType;
  my_status: "ALIVE" | "DEAD";
  /** 后端阶段名（含 HUNTER_SHOOT 等前端 Phase 枚举之外的值），按字符串处理。 */
  phase: string;
  round: number;
  seats: ObservedSeat[];
  sheriff_seat: number | null;
  badge_flow_claims: Record<string, number[]>;
  /** 私有信息：狼的 teammates / tonight_kill_proposals / tonight_kill_proposal、女巫的
   * antidote_available / poison_available / tonight_killed_seat、预言家 check_results、猎人 can_shoot…
   * 服务端给什么就是什么。 */
  private: Record<string, unknown>;
  election_stage: ElectionStage | string;
  sheriff_candidates: number[];
  vote_candidates: number[];
  pk_speech_pending: boolean;
  badge_only: boolean;
  /** 服务端按引擎校验给出的当前可用警长行动（issue #126）；前端只渲染这个集合。 */
  sheriff_options: string[];
  available_actions: number[];
}

/** 提交给 WS / `POST /actions` 的工具调用（PRD §4.1）。 */
export interface ToolCall {
  tool: string;
  arguments: Record<string, unknown>;
}

export interface YourTurn {
  observation: PlayerObservation;
  available_tools: string[];
  /** 服务端截止时间（秒，Unix 时间戳）。 */
  deadline_ts: number;
}

export interface ActionResult {
  ok: boolean;
  event_id: string | null;
  state_version: number | null;
  rejected_reason: string | null;
}
