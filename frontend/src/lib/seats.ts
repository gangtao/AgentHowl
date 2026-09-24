// 座位分配 → 建局 `agents` 映射的纯函数（规格 §7.2）。零 IO、零 React，可单测。
//
// 约定（与 backend/app/agent/profile.py::profile_for 一致）：
//   座位专属档案 → 键 `"{seat}"`；「填满其余座位」→ 键 `"*"`；随机 bot 不写入。
//   memory_id 同局唯一（后端 validate_profiles 会 400），UI 用 memoryConflicts 提前禁用。

import type { AgentProfile, StoredAgent } from "../api/agents";

/** 一行座位的选择；`agentId` 为 null = 随机 bot（有 fill 时该座由 `"*"` 覆盖）。 */
export interface SeatSlot {
  seat: number;
  agentId: string | null;
}

const PROFILE_KEYS = [
  "name",
  "model",
  "model_speech",
  "reflection_model",
  "thinking",
  "temperature",
  "skills",
  "personality",
  "memory_id",
  "provider",
] as const;

/**
 * 只留 AgentProfile 的字段：库记录的 agent_id / created_at / updated_at 不进建局请求
 * （AgentProfile 是 extra="forbid"，多带字段会 422）。
 */
export function toProfilePayload(profile: AgentProfile): AgentProfile {
  const src = profile as unknown as Record<string, unknown>;
  const out: Record<string, unknown> = {};
  for (const key of PROFILE_KEYS) {
    if (src[key] !== undefined) out[key] = src[key];
  }
  return out as unknown as AgentProfile;
}

function indexById(library: StoredAgent[]): Map<string, StoredAgent> {
  return new Map(library.map((a) => [a.agent_id, a]));
}

/** 座位选择 → `POST /games` 的 `agents` 映射。库里查不到的 id 视为未分配（忽略）。 */
export function buildAgentsPayload(
  assignment: SeatSlot[],
  fill: string | null,
  library: StoredAgent[],
): Record<string, AgentProfile> {
  const byId = indexById(library);
  const out: Record<string, AgentProfile> = {};
  for (const slot of assignment) {
    if (slot.agentId === null) continue;
    const stored = byId.get(slot.agentId);
    if (stored === undefined) continue;
    out[String(slot.seat)] = toProfilePayload(stored.profile);
  }
  if (fill !== null) {
    const stored = byId.get(fill);
    if (stored !== undefined) out["*"] = toProfilePayload(stored.profile);
  }
  return out;
}

/**
 * 已被占用的记忆 → agentId ↦ 首个占用它的座位号。
 *
 * 座位 S 的下拉里，`conflicts.get(id)` 存在且 !== S 的档案要禁用并提示
 * 「该记忆已在 N号 使用」——两个座位共用一份 memory_id 会互相污染经验，后端也会 400。
 */
export function memoryConflicts(
  assignment: SeatSlot[],
  library: StoredAgent[],
): Map<string, number> {
  const byId = indexById(library);
  const seatOfMemory = new Map<string, number>();
  for (const slot of [...assignment].sort((a, b) => a.seat - b.seat)) {
    if (slot.agentId === null) continue;
    const memoryId = byId.get(slot.agentId)?.profile.memory_id;
    if (!memoryId) continue;
    if (!seatOfMemory.has(memoryId)) seatOfMemory.set(memoryId, slot.seat);
  }
  const out = new Map<string, number>();
  for (const stored of library) {
    const memoryId = stored.profile.memory_id;
    if (!memoryId) continue;
    const seat = seatOfMemory.get(memoryId);
    if (seat !== undefined) out.set(stored.agent_id, seat);
  }
  return out;
}

export interface AssignmentSummary {
  /** 显式分配了档案的座位数。 */
  agentSeats: number;
  /** 其余座位数（有 fill 时由 `"*"` 覆盖，否则是随机 bot）。 */
  restSeats: number;
  filled: boolean;
}

export function assignmentSummary(
  assignment: SeatSlot[],
  fill: string | null,
): AssignmentSummary {
  const agentSeats = assignment.filter((s) => s.agentId !== null).length;
  return {
    agentSeats,
    restSeats: assignment.length - agentSeats,
    filled: fill !== null,
  };
}

/** N 个座位的空分配（全随机 bot）。 */
export function emptyAssignment(numPlayers: number): SeatSlot[] {
  return Array.from({ length: numPlayers }, (_, seat) => ({ seat, agentId: null }));
}
