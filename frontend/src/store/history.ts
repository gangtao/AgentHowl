// 历史对局 store（issue #98 设计 §3）：与 useProviders 同形 {items, loading, error, refresh}。

import { create } from "zustand";
import { deleteGame, listGames, type GameSummary } from "../api/history";
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
  /** 删除一局（issue #100）：成功即从列表移除；失败落 error 并抛出（与 useProviders.remove 同形）。 */
  remove(gameId: string): Promise<void>;
}

export const useHistory = create<HistoryState>((set, get) => ({
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

  async remove(gameId) {
    try {
      await deleteGame(gameId);
      set({ items: get().items.filter((r) => r.game_id !== gameId), error: null });
    } catch (err) {
      set({ error: messageOf(err) });
      throw err;
    }
  },
}));
