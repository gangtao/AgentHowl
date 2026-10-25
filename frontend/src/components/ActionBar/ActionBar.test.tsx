import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { PlayerObservation, YourTurn } from "../../api/player";
import ActionBar from "./ActionBar";

function obs(extra: Partial<PlayerObservation>): PlayerObservation {
  return {
    game_id: "g",
    state_version: 1,
    my_seat: 2,
    my_role: "VILLAGER",
    my_status: "ALIVE",
    phase: "DAY_SPEECH",
    round: 1,
    seats: [0, 1, 2, 3].map((seat) => ({ seat, alive: seat !== 3, is_sheriff: false, idiot_revealed: false })),
    sheriff_seat: null,
    badge_flow_claims: {},
    private: {},
    election_stage: "",
    sheriff_candidates: [],
    vote_candidates: [],
    pk_speech_pending: false,
    badge_only: false,
    available_actions: [],
    ...extra,
  };
}

function prompt(tools: string[], extra: Partial<PlayerObservation> = {}, deadline = 10_000): YourTurn {
  return { observation: obs(extra), available_tools: [...tools, "get_state"], deadline_ts: deadline };
}

const base = { pending: false, lastResult: null, lastError: null, now: () => 9_000 };

describe("ActionBar", () => {
  it("没有 prompt 时只显示等待文字", () => {
    render(<ActionBar {...base} prompt={null} onSubmit={vi.fn()} />);
    expect(screen.getByRole("status")).toHaveTextContent("等待其他玩家…");
  });

  it("speak：输入内容后提交 speak 调用；空内容禁用", () => {
    const onSubmit = vi.fn();
    render(<ActionBar {...base} prompt={prompt(["speak", "self_destruct"])} onSubmit={onSubmit} />);
    const btn = screen.getByRole("button", { name: "发送发言" });
    expect(btn).toBeDisabled();
    fireEvent.change(screen.getByLabelText("发言内容"), { target: { value: "我是好人" } });
    fireEvent.change(screen.getByLabelText("声明身份"), { target: { value: "SEER" } });
    fireEvent.click(btn);
    expect(onSubmit).toHaveBeenCalledWith({ tool: "speak", arguments: { content: "我是好人", claim_role: "SEER" } });
  });

  it("vote：未选目标禁用；选弃票提交 abstain；选座位提交 target_seat", () => {
    const onSubmit = vi.fn();
    render(<ActionBar {...base} prompt={prompt(["vote", "speak"], { phase: "VOTE" })} onSubmit={onSubmit} />);
    const btn = screen.getByRole("button", { name: "确认投票" });
    expect(btn).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "弃票" }));
    fireEvent.click(btn);
    expect(onSubmit).toHaveBeenLastCalledWith({ tool: "vote", arguments: { abstain: true } });
    fireEvent.click(screen.getByRole("button", { name: "1号" }));
    fireEvent.click(btn);
    expect(onSubmit).toHaveBeenLastCalledWith({ tool: "vote", arguments: { target_seat: 1 } });
    // 死者 3 号不在候选里
    expect(screen.queryByRole("button", { name: "3号" })).toBeNull();
  });

  it("night_action：女巫看到刀口，save 不需选目标，poison 需要", () => {
    const onSubmit = vi.fn();
    render(
      <ActionBar
        {...base}
        prompt={prompt(["night_action"], {
          my_role: "WITCH",
          phase: "NIGHT_WITCH",
          private: { antidote_available: true, poison_available: true, tonight_killed_seat: 0 },
        })}
        onSubmit={onSubmit}
      />,
    );
    expect(screen.getByText(/今晚刀口：0号/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "救人" }));
    fireEvent.click(screen.getByRole("button", { name: "确认行动" }));
    expect(onSubmit).toHaveBeenLastCalledWith({
      tool: "night_action",
      arguments: { action_type: "save", target_seat: 0 },
    });
    fireEvent.click(screen.getByRole("button", { name: "毒" }));
    expect(screen.getByRole("button", { name: "确认行动" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "1号" }));
    fireEvent.click(screen.getByRole("button", { name: "确认行动" }));
    expect(onSubmit).toHaveBeenLastCalledWith({
      tool: "night_action",
      arguments: { action_type: "poison", target_seat: 1 },
    });
  });

  it("sheriff_action：报名阶段上警一键提交；警徽窗口只给移交 / 撕", () => {
    const onSubmit = vi.fn();
    const { rerender } = render(
      <ActionBar
        {...base}
        prompt={prompt(["sheriff_action", "speak"], { phase: "SHERIFF_ELECTION", election_stage: "candidacy" })}
        onSubmit={onSubmit}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "上警" }));
    expect(onSubmit).toHaveBeenLastCalledWith({ tool: "sheriff_action", arguments: { action_type: "run_for_sheriff" } });
    rerender(
      <ActionBar
        {...base}
        prompt={prompt(["sheriff_action"], { phase: "LAST_WORDS", badge_only: true, sheriff_seat: 2, state_version: 2 })}
        onSubmit={onSubmit}
      />,
    );
    expect(screen.queryByRole("button", { name: "上警" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "撕警徽" }));
    expect(onSubmit).toHaveBeenLastCalledWith({ tool: "sheriff_action", arguments: { action_type: "tear_badge" } });
  });

  it("self_destruct 需二次确认", () => {
    const onSubmit = vi.fn();
    render(<ActionBar {...base} prompt={prompt(["speak", "self_destruct"])} onSubmit={onSubmit} />);
    fireEvent.click(screen.getByRole("tab", { name: "自爆" }));
    fireEvent.click(screen.getByRole("button", { name: "自爆" }));
    expect(onSubmit).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "确认自爆" }));
    expect(onSubmit).toHaveBeenCalledWith({ tool: "self_destruct", arguments: {} });
  });

  it("deadline 已过：显示超时提示但仍可提交；pending 禁用；拒因与错误展示", () => {
    const onSubmit = vi.fn();
    const { rerender } = render(
      <ActionBar {...base} now={() => 20_000} prompt={prompt(["speak"])} onSubmit={onSubmit} />,
    );
    expect(screen.getByText(/可能已超时/)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("发言内容"), { target: { value: "x" } });
    expect(screen.getByRole("button", { name: "发送发言" })).not.toBeDisabled();
    rerender(
      <ActionBar
        {...base}
        pending
        lastResult={{ ok: false, event_id: null, state_version: null, rejected_reason: "夜里不能发言" }}
        lastError="行动窗口已关闭"
        prompt={prompt(["speak"])}
        onSubmit={onSubmit}
      />,
    );
    expect(screen.getByRole("button", { name: "发送发言" })).toBeDisabled();
    expect(screen.getByText("夜里不能发言")).toBeInTheDocument();
    expect(screen.getByText("行动窗口已关闭")).toBeInTheDocument();
  });
});
