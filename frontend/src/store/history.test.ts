import { beforeEach, describe, expect, it, vi } from "vitest";
import { useHistory } from "./history";

const rows = [
  {
    game_id: "g_new",
    preset: "std_9_kill_side",
    num_players: 9,
    status: "finished",
    started_at: "2026-10-02T03:00:00+00:00",
    ended_at: "2026-10-02T03:10:00+00:00",
    winner: "GOOD",
    rounds: 3,
    seats: [],
    seq: 120,
  },
  {
    game_id: "g_live",
    preset: "std_12_yn_hunter_guard",
    num_players: 12,
    status: "live",
    started_at: "2026-10-02T02:00:00+00:00",
    ended_at: null,
    winner: null,
    rounds: 1,
    seats: [],
    seq: 30,
  },
];

describe("useHistory", () => {
  beforeEach(() => {
    useHistory.setState({ items: [], loading: false, error: null });
  });
  it("refresh 拉取 /api/v1/games", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(
        async () =>
          new Response(JSON.stringify(rows), {
            status: 200,
            headers: { "content-type": "application/json" },
          }),
      ),
    );
    await useHistory.getState().refresh();
    expect(useHistory.getState().items.map((r) => r.game_id)).toEqual(["g_new", "g_live"]);
    expect((fetch as unknown as ReturnType<typeof vi.fn>).mock.calls[0]?.[0]).toContain(
      "/api/v1/games",
    );
  });
  it("失败落 error", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response(JSON.stringify({ detail: "缺少 Bearer token" }), { status: 401 })),
    );
    await useHistory.getState().refresh();
    expect(useHistory.getState().error).toContain("缺少 Bearer token");
  });
});
