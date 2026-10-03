// 历史页删除流程（issue #100）：点「删除」→ 确认框 → 确认后发 DELETE 并移除该行；取消不发请求。

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useHistory } from "../store/history";
import History from "./History";

const rows = [
  {
    game_id: "g_done",
    preset: "std_9_kill_side",
    num_players: 9,
    status: "finished",
    started_at: "2026-10-02T03:00:00+00:00",
    ended_at: "2026-10-02T03:10:00+00:00",
    winner: "GOOD",
    rounds: 3,
    seats: [{ seat: 0, display_name: "夜枭", agent: true }],
    seq: 120,
  },
];

function stubFetch(): ReturnType<typeof vi.fn> {
  const fetchMock = vi.fn(async (_url: string, init?: RequestInit) => {
    if (init?.method === "DELETE") return new Response(null, { status: 204 });
    return new Response(JSON.stringify(rows), {
      status: 200,
      headers: { "content-type": "application/json" },
    });
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

describe("History 删除", () => {
  beforeEach(() => {
    useHistory.setState({ items: [], loading: false, error: null });
  });

  it("确认后删除并移除该行", async () => {
    const fetchMock = stubFetch();
    render(<History />);
    await screen.findByText(/g_done/);
    fireEvent.click(screen.getByRole("button", { name: /删除/ }));
    const dialog = screen.getByRole("alertdialog");
    expect(dialog).toHaveTextContent(/g_done/);
    fireEvent.click(screen.getByRole("button", { name: /确认删除/ }));
    await waitFor(() => expect(screen.queryByText(/g_done/)).toBeNull());
    const deleteCall = fetchMock.mock.calls.find(
      (c) => (c as unknown as [string, RequestInit])[1]?.method === "DELETE",
    ) as unknown as [string, RequestInit] | undefined;
    expect(deleteCall?.[0]).toContain("/api/v1/games/g_done");
    expect(screen.queryByRole("alertdialog")).toBeNull();
  });

  it("取消不发请求", async () => {
    const fetchMock = stubFetch();
    render(<History />);
    await screen.findByText(/g_done/);
    fireEvent.click(screen.getByRole("button", { name: /删除/ }));
    fireEvent.click(screen.getByRole("button", { name: /取消/ }));
    expect(screen.queryByRole("alertdialog")).toBeNull();
    expect(screen.getByText(/g_done/)).toBeInTheDocument();
    expect(
      fetchMock.mock.calls.some((c) => (c as unknown as [string, RequestInit])[1]?.method === "DELETE"),
    ).toBe(false);
  });
});
