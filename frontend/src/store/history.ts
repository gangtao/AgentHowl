// 历史对局 store（issue #98 设计 §3）：与 useProviders 同形 {items, loading, error, refresh}。

import { create } from "zustand";
import { listGames, type GameSummary } from "../api/history";
import { ApiError } from "../api/rest";

function messageOf(err: unknown): string {
  if (err instanceof ApiError) return err.detail;
  if (err instanceof Error) return err.message;
  return String(err);
}

interface HistoryState {
  items: GameSummary[];
  loading: boolean;
  error: string | null;

  refresh(): Promise<void>;
}

export const useHistory = create<HistoryState>((set) => ({
  items: [],
  loading: false,
  error: null,

  async refresh() {
    set({ loading: true, error: null });
    try {
      const items = await listGames();
      set({ items, loading: false });
    } catch (err) {
      set({ error: messageOf(err), loading: false });
    }
  },
}));
