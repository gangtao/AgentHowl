// 模型服务 Provider store（规格 §6）：进入 Lobby / Providers 页时拉取。

import { create } from "zustand";
import {
  createProvider,
  deleteProvider,
  listModels as apiListModels,
  listProviders,
  testProvider,
  updateProvider,
  type ProviderInput,
  type ProviderModelsResult,
  type ProviderPublic,
  type ProviderTestResult,
} from "../api/providers";
import { ApiError } from "../api/rest";

function messageOf(err: unknown): string {
  if (err instanceof ApiError) return err.detail;
  if (err instanceof Error) return err.message;
  return String(err);
}

interface ProvidersState {
  items: ProviderPublic[];
  loading: boolean;
  error: string | null;

  refresh(): Promise<void>;
  create(body: ProviderInput): Promise<ProviderPublic>;
  update(providerId: string, body: ProviderInput): Promise<ProviderPublic>;
  remove(providerId: string): Promise<void>;
  test(providerId: string, model?: string): Promise<ProviderTestResult>;
  listModels(providerId: string): Promise<ProviderModelsResult>;
}

export const useProviders = create<ProvidersState>((set, get) => ({
  items: [],
  loading: false,
  error: null,

  async refresh() {
    set({ loading: true, error: null });
    try {
      const items = await listProviders();
      set({ items, loading: false });
    } catch (err) {
      set({ error: messageOf(err), loading: false });
    }
  },

  async create(body) {
    const provider = await createProvider(body);
    set({ items: [provider, ...get().items] });
    return provider;
  },

  async update(providerId, body) {
    const provider = await updateProvider(providerId, body);
    set({ items: get().items.map((p) => (p.provider_id === providerId ? provider : p)) });
    return provider;
  },

  async remove(providerId) {
    await deleteProvider(providerId);
    set({ items: get().items.filter((p) => p.provider_id !== providerId) });
  },

  test(providerId, model) {
    return testProvider(providerId, model);
  },

  listModels(providerId) {
    return apiListModels(providerId);
  },
}));
