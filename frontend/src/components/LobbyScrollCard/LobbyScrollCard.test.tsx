import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import LobbyScrollCard from "./LobbyScrollCard";

const base = {
  numPlayers: 12,
  presetZh: "12 人预女猎白",
  fillName: null,
  seed: "",
  summary: { agentSeats: 3, restSeats: 8, filled: false, humanSeat: 0 },
  tts: { enabled: true, ok: true, url: null, detail: null, supports_style: false },
  voice: false,
  narration: false,
  onVoice: vi.fn(),
  onNarration: vi.fn(),
  showNotes: false,
  canLaunch: false,
  creating: false,
  onLaunch: vi.fn(),
};

describe("LobbyScrollCard", () => {
  it("汇总两行 + 开局按钮禁用态", () => {
    render(<LobbyScrollCard {...base} />);
    expect(screen.getByText("开局卷轴")).toBeInTheDocument();
    expect(screen.getByText("12 座位 · 3 个 Agent · 我在 0号 · 8 个随机 bot")).toBeInTheDocument();
    expect(screen.getByText("12 人预女猎白 · seed 随机")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "点燃篝火 · 开局" })).toBeDisabled();
    expect(screen.queryByText(/同一档案可放多个座位/)).toBeNull();
  });

  it("可开局时按钮可用并回调；第 2 步显示说明；创建中文案", () => {
    const onLaunch = vi.fn();
    const { rerender } = render(
      <LobbyScrollCard {...base} canLaunch showNotes onLaunch={onLaunch} />,
    );
    fireEvent.click(screen.getByRole("button", { name: "点燃篝火 · 开局" }));
    expect(onLaunch).toHaveBeenCalled();
    expect(screen.getByText(/「我自己」只能占一个座位/)).toBeInTheDocument();
    rerender(<LobbyScrollCard {...base} canLaunch creating onLaunch={onLaunch} />);
    expect(screen.getByRole("button", { name: "创建中…" })).toBeDisabled();
  });

  it("语音 / 旁白复选：旁白依赖语音；tts 未开启时不渲染", () => {
    const onVoice = vi.fn();
    const { rerender } = render(<LobbyScrollCard {...base} onVoice={onVoice} />);
    expect(screen.getByLabelText(/^旁白/)).toBeDisabled();
    fireEvent.click(screen.getByLabelText(/语音播报/));
    expect(onVoice).toHaveBeenCalledWith(true);
    rerender(<LobbyScrollCard {...base} tts={{ ...base.tts, enabled: false }} />);
    expect(screen.queryByLabelText(/语音播报/)).toBeNull();
  });
});
