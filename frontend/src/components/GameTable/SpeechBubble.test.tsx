import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { SpeechItem } from "../../engine/select";
import { SpeechBubble } from "./SpeechBubble";

const item: SpeechItem = {
  seq: 10,
  type: "PLAYER_SPOKE",
  kind: "speech",
  actor_seat: 0,
  text: "0号发言：我不确定",
  content: "我不确定，但我更在意一点",
};

const base = { seat: 0, name: "Gang", deadline: null, voicing: false, anchor: { x: 50, y: 9 } };

describe("SpeechBubble（规格 §4.3）", () => {
  it("有正文时显示 content 与「发言中」头行", () => {
    render(<SpeechBubble {...base} item={item} kind="speech" />);
    expect(screen.getByRole("status", { name: /0号 Gang 发言中/ })).toBeInTheDocument();
    expect(screen.getByText("我不确定，但我更在意一点")).toBeInTheDocument();
  });

  it.each([
    ["speech", "轮到你发言…"],
    ["campaign", "轮到你时在此陈述竞选理由…（草稿会保留）"],
    ["last_words", "写下遗言…"],
  ] as const)("无 item 时按 kind 显示占位：%s", (kind, placeholder) => {
    render(<SpeechBubble {...base} item={null} kind={kind} />);
    expect(screen.getByText(placeholder)).toBeInTheDocument();
  });

  it("voicing 时显示「语音播报 · 正在朗读」与光标", () => {
    render(<SpeechBubble {...base} item={item} kind="speech" voicing />);
    expect(screen.getByText("语音播报 · 正在朗读")).toBeInTheDocument();
    expect(screen.getByText("▍")).toBeInTheDocument();
  });

  it("deadline 给进度条；now 注入", () => {
    const now = (): number => 1000;
    const { container } = render(
      <SpeechBubble {...base} item={item} kind="speech" deadline={1030} now={now} limit={120} />,
    );
    const bar = container.querySelector("[data-progress]") as HTMLElement;
    expect(bar).not.toBeNull();
    expect(bar.getAttribute("data-progress")).toBe("25"); // 剩 30 / 120
    expect(screen.getByText("30s")).toBeInTheDocument();
  });

  it("锚点在上半圈 → 气泡在座位下方（data-side=below），下半圈 → above", () => {
    const { rerender } = render(<SpeechBubble {...base} item={item} kind="speech" />);
    expect(screen.getByRole("status")).toHaveAttribute("data-side", "below");
    rerender(<SpeechBubble {...base} anchor={{ x: 50, y: 91 }} item={item} kind="speech" />);
    expect(screen.getByRole("status")).toHaveAttribute("data-side", "above");
  });
});
