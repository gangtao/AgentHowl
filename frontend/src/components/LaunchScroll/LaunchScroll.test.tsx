import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import LaunchScroll from "./LaunchScroll";

const preset = {
  name: "std_9_kill_side",
  num_players: 9,
  roles: [],
  sheriff: true,
  win_condition: "KILL_SIDE",
  description_zh: "标准 9 人局",
};
const base = {
  preset,
  me: 3,
  seatTags: [
    { seat: 3, kind: "me" as const, text: "我自己" },
    { seat: 5, kind: "agent" as const, text: "狐语" },
  ],
  rest: 7,
  fillName: null,
  seed: "",
  displayName: "",
  displayNamePlaceholder: "alice",
  onDisplayName: vi.fn(),
  speechTimeout: "120",
  onSpeechTimeout: vi.fn(),
  actionTimeout: "60",
  onActionTimeout: vi.fn(),
  voice: true,
  narration: false,
  ttsEnabled: true,
  error: null,
  canDiscard: false,
  onDiscard: vi.fn(),
  canLaunch: true,
  creating: false,
  onBack: vi.fn(),
  onLaunch: vi.fn(),
};

describe("LaunchScroll（规格 §5 第 3 步）", () => {
  it("我自己入座：副标 / 座位签 / 时限输入 / 开局按钮", () => {
    render(<LaunchScroll {...base} />);
    expect(screen.getByRole("heading", { name: "开 局 卷 轴" })).toBeInTheDocument();
    expect(
      screen.getByText("你将以 3号 入座 · 创建后直接进入玩家页 · 对局结束前看不到上帝视角"),
    ).toBeInTheDocument();
    expect(screen.getByText("标准 9 人局")).toBeInTheDocument();
    expect(screen.getByText("std_9_kill_side")).toBeInTheDocument();
    expect(screen.getByText("3号 我自己")).toBeInTheDocument();
    expect(screen.getByText("5号 狐语")).toBeInTheDocument();
    expect(screen.getByText(/其余 7 座随机 bot/)).toBeInTheDocument();
    expect(screen.getByText("随机")).toBeInTheDocument();
    expect(screen.getByLabelText("我的显示名")).toHaveAttribute("placeholder", "alice");
    expect(screen.getByLabelText("发言时限")).toHaveValue("120");
    expect(screen.getByLabelText("行动时限")).toHaveValue("60");
    expect(screen.getByText(/秒 · 一根蜡烛/)).toBeInTheDocument();
    expect(screen.getByText(/☑ 语音播报/)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("发言时限"), { target: { value: "90" } });
    expect(base.onSpeechTimeout).toHaveBeenCalledWith("90");
    fireEvent.click(screen.getByRole("button", { name: "点燃篝火 · 开局" }));
    expect(base.onLaunch).toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "← 上一步 · 分配座位" }));
    expect(base.onBack).toHaveBeenCalled();
  });

  it("全 AI：副标改写，没有显示名输入；fill 文案；错误 + 删除这局；按钮禁用", () => {
    render(
      <LaunchScroll
        {...base}
        me={null}
        seatTags={[]}
        rest={9}
        fillName="狐语"
        ttsEnabled={false}
        error="409 · 座位被占"
        canDiscard
        canLaunch={false}
      />,
    );
    expect(screen.getByText("全 AI 对局 · 创建后进入上帝视角")).toBeInTheDocument();
    expect(screen.queryByLabelText("我的显示名")).toBeNull();
    expect(screen.queryByLabelText("发言时限")).toBeNull();
    expect(screen.getByText(/其余 9 座由「狐语」填满/)).toBeInTheDocument();
    expect(screen.queryByText(/语音播报/)).toBeNull();
    expect(screen.getByText("409 · 座位被占")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "删除这局" }));
    expect(base.onDiscard).toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "点燃篝火 · 开局" })).toBeDisabled();
  });
});
