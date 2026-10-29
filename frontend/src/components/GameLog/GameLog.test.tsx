// 对局记录（规格 §6.2）：倒序 / 日夜分隔 / 分组过滤 / 回放游标高亮 / 私有行 / 空态。

import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import fixture from "../../engine/__fixtures__/std_9_kill_all-3.json";
import type { Event, GameState } from "../../engine/types";
import { logEntries } from "../../lib/gameLog";
import GameLog from "./GameLog";

const events = fixture.events as unknown as Event[];
const states = fixture.states as unknown as GameState[];
const last = states[states.length - 1]!;

function mount(entries: ReturnType<typeof logEntries>, cursor: number | null = null): void {
  document.body.innerHTML = "";
  render(<GameLog entries={entries} state={last} cursor={cursor} />);
}

describe("GameLog（规格 §6.2）", () => {
  const entries = logEntries(events);

  it("最新在上、日夜分隔、验人页签按数据出现", () => {
    mount(entries);
    expect(screen.getByRole("region", { name: "对局记录" })).toBeInTheDocument();
    const arts = document.querySelectorAll("article[data-seq]");
    expect(arts.length).toBe(entries.length);
    expect(Number(arts[0]!.getAttribute("data-seq"))).toBe(entries[0]!.seq);
    expect(screen.getAllByTestId("log-day").length).toBeGreaterThan(2);
    expect(screen.getByRole("tab", { name: "验人" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "全部" })).toHaveAttribute("aria-selected", "true");
  });

  it("过滤：发言页签只剩 speech 组；无验人条目时没有验人页签", () => {
    mount(entries);
    fireEvent.click(screen.getByRole("tab", { name: "发言" }));
    const groups = new Set(
      [...document.querySelectorAll("article[data-group]")].map((a) => a.getAttribute("data-group")),
    );
    expect(groups).toEqual(new Set(["speech"]));
    expect(screen.getByRole("tab", { name: "发言" })).toHaveAttribute("aria-selected", "true");
    mount(entries.filter((e) => e.group !== "seer"));
    expect(screen.queryByRole("tab", { name: "验人" })).toBeNull();
  });

  it("发言行有座位名字与正文、自称签；事件行有签与 #seq", () => {
    // 随机 bot 不声明身份：把第一条发言改成自称预言家
    const first = entries.find((e) => e.type === "PLAYER_SPOKE")!;
    const spoke = { ...first, speech: { ...first.speech!, claim: "SEER" as const } };
    mount(entries.map((e) => (e.seq === spoke.seq ? spoke : e)));
    const art = document.querySelector(`article[data-seq="${spoke.seq}"]`)!;
    expect(art).toHaveTextContent(`${spoke.actor_seat}号`);
    expect(art).toHaveTextContent(spoke.speech!.content.slice(0, 10));
    expect(art).toHaveTextContent("自称 预言家");
    expect(art).toHaveTextContent(`#${spoke.seq}`);
    const dawn = entries.find((e) => e.type === "DEATH_ANNOUNCED")!;
    const art2 = document.querySelector(`article[data-seq="${dawn.seq}"]`)!;
    expect(art2).toHaveTextContent("天亮");
    expect(art2).toHaveTextContent(`#${dawn.seq}`);
  });

  it("回放游标处的条目 data-current；私有行 data-private；空态", () => {
    const seer = entries.find((e) => e.type === "SEER_CHECKED")!;
    mount(entries, seer.seq);
    const art = document.querySelector(`article[data-seq="${seer.seq}"]`)!;
    expect(art).toHaveAttribute("data-current", "true");
    expect(art).toHaveAttribute("data-private", "true");
    expect(document.querySelector('article[data-group="speech"]')).not.toHaveAttribute(
      "data-private",
    );
    mount([]);
    expect(screen.getByText("尚无记录")).toBeInTheDocument();
  });

  it("回放游标变化时列表回到顶部（最新 ≤ 游标的那条就在顶上），未读归零", () => {
    const seer = entries.find((e) => e.type === "SEER_CHECKED")!;
    document.body.innerHTML = "";
    const { rerender } = render(<GameLog entries={entries} state={last} cursor={seer.seq} />);
    const scroll = screen.getByRole("region", { name: "对局记录" }).querySelector("[data-testid='log-scroll']") as HTMLElement;
    scroll.scrollTop = 300;
    rerender(<GameLog entries={entries} state={last} cursor={seer.seq + 1} />);
    expect(scroll.scrollTop).toBe(0);
  });
});
