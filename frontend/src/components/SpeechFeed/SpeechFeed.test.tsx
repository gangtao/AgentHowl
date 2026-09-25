// 冒烟测试：发言流渲染发言卡与 [GM] 行；cursor 截断后条目变少。

import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import fixture from "../../engine/__fixtures__/std_9_kill_side-3.json";
import { speechItems } from "../../engine/select";
import type { Event, GameState } from "../../engine/types";
import SpeechFeed from "./SpeechFeed";

const events = fixture.events as unknown as Event[];
const states = fixture.states as unknown as GameState[];
const finalState = states[states.length - 1] as GameState;
const items = speechItems(events);

describe("SpeechFeed", () => {
  it("渲染发言卡与 [GM] 行", () => {
    const { container } = render(
      <SpeechFeed items={items} cursor={null} state={finalState} speakingSeat={null} />,
    );
    const speeches = items.filter((it) => it.kind === "speech");
    expect(container.querySelectorAll('[data-kind="speech"]')).toHaveLength(speeches.length);
    expect(screen.getAllByText("[GM]").length).toBeGreaterThan(0);
  });

  it("cursor 截断后条目数减少并提示剩余条数", () => {
    const cursor = items[Math.floor(items.length / 2)]!.seq;
    const { container } = render(
      <SpeechFeed items={items} cursor={cursor} state={finalState} speakingSeat={null} />,
    );
    const shown = container.querySelectorAll("[data-kind]");
    expect(shown.length).toBeLessThan(items.length);
    expect(shown.length).toBe(items.filter((it) => it.seq <= cursor).length);
    expect(screen.getByText(/回放游标之后/)).toBeInTheDocument();
  });
});
