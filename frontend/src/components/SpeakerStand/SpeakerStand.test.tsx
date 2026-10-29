// 发言台（规格 §5，设计稿 8a / 8b）：当前发言人 / 正文 / 计时环 / 队列 / 提示。

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { SpeechItem } from "../../engine/select";
import type { RoleType } from "../../engine/types";
import SpeakerStand from "./SpeakerStand";

const item: SpeechItem = {
  seq: 9,
  type: "PLAYER_SPOKE",
  kind: "speech",
  actor_seat: 5,
  text: "5号发言：我是警长",
  content: "我是警长",
  claim: "SEER",
  badgeFlow: [2, 7],
};
const base = {
  seat: 5,
  name: "火药桶",
  role: null,
  avatar: null,
  kind: "speech" as const,
  mine: false,
  deadline: null,
  limit: null,
  voicing: false,
  queue: [8, 9, 0],
  claims: [] as [number, RoleType][],
};

describe("SpeakerStand（规格 §5）", () => {
  it("他人发言：正文、自称签、警徽流签、队列；无 agent 不渲染模型行", () => {
    render(<SpeakerStand {...base} item={item} />);
    expect(screen.getByRole("status", { name: "5号 火药桶 发言中" })).toHaveAttribute(
      "data-layout",
      "full",
    );
    expect(screen.getByTestId("stand-text")).toHaveTextContent("我是警长");
    expect(screen.getByText("自称 预言家")).toBeInTheDocument();
    expect(screen.getByText("警徽流 2 → 7")).toBeInTheDocument();
    expect(screen.getByTestId("stand-queue")).toHaveTextContent("之后 8号 → 9号 → 0号");
    expect(screen.queryByTestId("stand-agent")).toBeNull();
    expect(screen.queryByTestId("stand-bars")).toBeNull();
  });

  it("未开口：占位「正在组织语言…」；本人未开口切紧凑版「轮到你」+ 提示", () => {
    const { rerender } = render(<SpeakerStand {...base} item={null} />);
    expect(screen.getByTestId("stand-text")).toHaveTextContent("正在组织语言…");
    rerender(
      <SpeakerStand
        {...base}
        item={null}
        mine
        queue={[]}
        claims={[
          [5, "SEER"],
          [2, "WITCH"],
        ]}
      />,
    );
    expect(screen.getByRole("status", { name: "5号 火药桶 轮到你" })).toHaveAttribute(
      "data-layout",
      "compact",
    );
    expect(screen.getByTestId("stand-hint")).toHaveTextContent("本轮自称：5号 预言家、2号 女巫");
    expect(screen.getByTestId("stand-queue")).toHaveTextContent("最后一位 · 发完即进入投票");
    rerender(<SpeakerStand {...base} item={null} mine queue={[]} claims={[]} kind="campaign" />);
    expect(screen.getByTestId("stand-hint")).toHaveTextContent("本轮尚无人声明身份");
    expect(screen.getByTestId("stand-queue")).toHaveTextContent("最后一位 · 发完即进入下一阶段");
    // 本人说完回到标准版
    rerender(<SpeakerStand {...base} item={item} mine queue={[]} />);
    expect(screen.getByRole("status", { name: "5号 火药桶 发言中" })).toHaveAttribute(
      "data-layout",
      "full",
    );
  });

  it("配音中：音柱 + 光标；遗言 / 竞选胶囊文案", () => {
    const { rerender } = render(<SpeakerStand {...base} item={item} voicing kind="last_words" />);
    expect(screen.getByTestId("stand-bars")).toBeInTheDocument();
    expect(screen.getByTestId("stand-text")).toHaveTextContent("▍");
    expect(screen.getByRole("status", { name: /遗言$/ })).toBeInTheDocument();
    rerender(<SpeakerStand {...base} item={item} kind="campaign" />);
    expect(screen.getByRole("status", { name: /竞选发言$/ })).toBeInTheDocument();
  });

  it("agent 行与声线文案；倒计时与进度环", () => {
    render(
      <SpeakerStand
        {...base}
        item={item}
        agent={{ model: "claude-sonnet", voice: "低沉" }}
        deadline={1030}
        limit={60}
        now={() => 1000}
      />,
    );
    expect(screen.getByTestId("stand-agent")).toHaveTextContent("claude-sonnet · 声线：低沉");
    expect(screen.getByTestId("stand-timer")).toHaveTextContent("30s");
    const ring = screen.getByTestId("stand-ring");
    expect(ring.getAttribute("style")).toContain("50%");
  });

  it("无时限：不显示计时，环满格", () => {
    render(<SpeakerStand {...base} item={item} />);
    expect(screen.queryByTestId("stand-timer")).toBeNull();
    expect(screen.getByTestId("stand-ring").getAttribute("style")).toContain("100%");
  });

  it("不挂全局 .ah-wood（它的 display:flex column 会把两栏 grid 压成一列）", () => {
    render(<SpeakerStand {...base} item={item} />);
    expect(screen.getByRole("status").className).not.toMatch(/\bah-wood\b/);
  });
});
