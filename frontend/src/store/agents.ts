// Agent 档案库小 store（规格 §6）：进入 Lobby / AgentLibrary 页时拉取。零 IO 的 API 调用委托给
// src/api/agents.ts；本文件不 import React 组件。

import { create } from "zustand";
import {
  createAgent,
  deleteAgent,
  listAgents,
  listPresets,
  listSkills,
  updateAgent,
  type AgentProfile,
  type PresetInfo,
  type SkillInfo,
  type StoredAgent,
} from "../api/agents";
import { ApiError } from "../api/rest";

function messageOf(err: unknown): string {
  if (err instanceof ApiError) return err.detail;
  if (err instanceof Error) return err.message;
  return String(err);
}

interface AgentLibraryState {
  items: StoredAgent[];
  skills: SkillInfo[];
  presets: PresetInfo[];
  loading: boolean;
  error: string | null;

  refresh(): Promise<void>;
  create(profile: AgentProfile): Promise<StoredAgent>;
  update(agentId: string, profile: AgentProfile): Promise<StoredAgent>;
  remove(agentId: string): Promise<void>;
}

export const useAgentLibrary = create<AgentLibraryState>((set, get) => ({
  items: [],
  skills: [],
  presets: [],
  loading: false,
  error: null,

  async refresh() {
    set({ loading: true, error: null });
    try {
      const [items, skills, presets] = await Promise.all([
        listAgents(),
        listSkills(),
        listPresets(),
      ]);
      set({ items, skills, presets, loading: false });
    } catch (err) {
      set({ error: messageOf(err), loading: false });
    }
  },

  async create(profile) {
    try {
      const stored = await createAgent(profile);
      set({ items: [stored, ...get().items] });
      return stored;
    } catch (err) {
      set({ error: messageOf(err) });
      throw err; // 页面可能想自己 catch 再弹提示，这里只负责落 error，不吞异常
    }
  },

  async update(agentId, profile) {
    try {
      const stored = await updateAgent(agentId, profile);
      set({ items: get().items.map((a) => (a.agent_id === agentId ? stored : a)) });
      return stored;
    } catch (err) {
      set({ error: messageOf(err) });
      throw err;
    }
  },

  async remove(agentId) {
    try {
      await deleteAgent(agentId);
      set({ items: get().items.filter((a) => a.agent_id !== agentId) });
    } catch (err) {
      set({ error: messageOf(err) });
      throw err;
    }
  },
}));
