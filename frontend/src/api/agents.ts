// Agent 档案库 + 建局辅助端点薄封装（对应 backend/app/api/agents.py，规格 §2b/§6）。

import { req } from "./rest";

export interface PersonalitySpec {
  [key: string]: unknown;
}

/** 与 app/agent/profile.py::AgentProfile 对应（extra=forbid，字段名逐一对齐）。 */
export interface AgentProfile {
  name?: string | null;
  model: string;
  model_speech?: string | null;
  reflection_model?: string | null;
  thinking?: boolean;
  temperature?: number;
  skills?: string[];
  personality?: PersonalitySpec | null;
  memory_id?: string | null;
  provider?: string | null;
}

export interface StoredAgent {
  agent_id: string;
  profile: AgentProfile;
  created_at: string;
  updated_at: string;
}

export interface SkillInfo {
  name: string;
  description: string;
  roles: string[];
  phases: string[];
}

export interface PresetRole {
  role: string;
  count: number;
}

export interface PresetInfo {
  name: string;
  num_players: number;
  roles: PresetRole[];
  sheriff: boolean;
  win_condition: string;
  description_zh: string;
}

export function listAgents(): Promise<StoredAgent[]> {
  return req<StoredAgent[]>("GET", "/agents");
}

export function createAgent(profile: AgentProfile): Promise<StoredAgent> {
  return req<StoredAgent>("POST", "/agents", { body: profile });
}

export function getAgent(agentId: string): Promise<StoredAgent> {
  return req<StoredAgent>("GET", `/agents/${agentId}`);
}

export function updateAgent(agentId: string, profile: AgentProfile): Promise<StoredAgent> {
  return req<StoredAgent>("PUT", `/agents/${agentId}`, { body: profile });
}

export function deleteAgent(agentId: string): Promise<void> {
  return req<void>("DELETE", `/agents/${agentId}`);
}

export function listSkills(): Promise<SkillInfo[]> {
  return req<SkillInfo[]>("GET", "/skills");
}

export function listPresets(): Promise<PresetInfo[]> {
  return req<PresetInfo[]>("GET", "/presets");
}
