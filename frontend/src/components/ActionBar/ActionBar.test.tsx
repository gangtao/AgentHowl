import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
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
    seats: [0, 1, 2, 3].map((seat) => ({
      seat,
      alive: seat !== 3,
      is_sheriff: false,
      idiot_revealed: false,
    })),
    sheriff_seat: null,
    badge_flow_claims: {},
    private: {},
    election_stage: "",
    sheriff_candidates: [],
    vote_candidates: [],
    pk_speech_pending: false,
    badge_only: false,
    sheriff_options: [],
    available_actions: [],
    ...extra,
  };
}

function prompt(
  tools: string[],
  extra: Partial<PlayerObservation> = {},
  deadline = 10_000,
): YourTurn {
  return {
    observation: obs(extra),
    available_tools: [...tools, "get_state"],
    deadline_ts: deadline,
  };
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
    expect(onSubmit).toHaveBeenCalledWith({
      tool: "speak",
      arguments: { content: "我是好人", claim_role: "SEER" },
    });
  });

  it("vote：未选目标禁用；选弃票提交 abstain；选座位提交 target_seat", () => {
    const onSubmit = vi.fn();
    render(
      <ActionBar
        {...base}
        prompt={prompt(["vote", "speak"], { phase: "VOTE" })}
        onSubmit={onSubmit}
      />,
    );
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
        prompt={prompt(["sheriff_action", "speak"], {
          phase: "SHERIFF_ELECTION",
          election_stage: "candidacy",
          sheriff_options: ["run_for_sheriff", "withdraw"],
        })}
        onSubmit={onSubmit}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "上警" }));
    expect(onSubmit).toHaveBeenLastCalledWith({
      tool: "sheriff_action",
      arguments: { action_type: "run_for_sheriff" },
    });
    rerender(
      <ActionBar
        {...base}
        prompt={prompt(["sheriff_action"], {
          phase: "LAST_WORDS",
          badge_only: true,
          sheriff_seat: 2,
          state_version: 2,
          sheriff_options: ["pass_badge", "tear_badge"],
        })}
        onSubmit={onSubmit}
      />,
    );
    expect(screen.queryByRole("button", { name: "上警" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "撕警徽" }));
    expect(onSubmit).toHaveBeenLastCalledWith({
      tool: "sheriff_action",
      arguments: { action_type: "tear_badge" },
    });
  });

  it("sheriff_action：报名阶段非候选人可选「不上」→ withdraw", () => {
    const onSubmit = vi.fn();
    render(
      <ActionBar
        {...base}
        prompt={prompt(["sheriff_action"], {
          phase: "SHERIFF_ELECTION",
          election_stage: "candidacy",
          sheriff_options: ["run_for_sheriff", "withdraw"],
        })}
        onSubmit={onSubmit}
      />,
    );
    expect(screen.getByRole("button", { name: "上警" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "不上" }));
    expect(onSubmit).toHaveBeenLastCalledWith({
      tool: "sheriff_action",
      arguments: { action_type: "withdraw" },
    });
  });

  it("sheriff_action：退水子阶段候选人可选「坚持竞选」→ run_for_sheriff", () => {
    const onSubmit = vi.fn();
    render(
      <ActionBar
        {...base}
        prompt={prompt(["sheriff_action"], {
          phase: "SHERIFF_ELECTION",
          election_stage: "withdraw",
          sheriff_candidates: [1, 2],
          sheriff_options: ["run_for_sheriff", "withdraw"],
        })}
        onSubmit={onSubmit}
      />,
    );
    expect(screen.getByRole("button", { name: "退水" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "上警" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "坚持竞选" }));
    expect(onSubmit).toHaveBeenLastCalledWith({
      tool: "sheriff_action",
      arguments: { action_type: "run_for_sheriff" },
    });
  });

  it("默认分组：PK 发言待讲落在 speak；仅警徽窗口落在 sheriff_action", () => {
    const { rerender } = render(
      <ActionBar
        {...base}
        prompt={prompt(["vote", "speak"], { phase: "VOTE_PK", pk_speech_pending: true })}
        onSubmit={vi.fn()}
      />,
    );
    expect(screen.getByLabelText("发言内容")).toBeInTheDocument();
    rerender(
      <ActionBar
        {...base}
        prompt={prompt(["speak", "sheriff_action"], {
          phase: "LAST_WORDS",
          badge_only: true,
          sheriff_seat: 2,
          sheriff_options: ["pass_badge", "tear_badge"],
          state_version: 2,
        })}
        onSubmit={vi.fn()}
      />,
    );
    expect(screen.getByRole("button", { name: "撕警徽" })).toBeInTheDocument();
    expect(screen.queryByLabelText("发言内容")).toBeNull();
  });

  it("issue #141：警徽窗口即使 pk_speech_pending 为真也默认落在警长页签", () => {
    render(
      <ActionBar
        {...base}
        prompt={prompt(["speak", "sheriff_action"], {
          phase: "LAST_WORDS",
          badge_only: true,
          pk_speech_pending: true,
          sheriff_seat: 2,
          sheriff_options: ["pass_badge", "tear_badge"],
          state_version: 2,
        })}
        onSubmit={vi.fn()}
      />,
    );
    expect(screen.getByRole("button", { name: "撕警徽" })).toBeInTheDocument();
    expect(screen.queryByLabelText("发言内容")).toBeNull();
  });

  it("死亡警长的普通遗言窗口不展示移交 / 撕警徽", () => {
    render(
      <ActionBar
        {...base}
        prompt={prompt(["speak", "sheriff_action"], {
          phase: "LAST_WORDS",
          badge_only: false,
          sheriff_seat: 2,
          my_status: "DEAD",
        })}
        onSubmit={vi.fn()}
      />,
    );
    expect(screen.getByLabelText("发言内容")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "警长" }));
    expect(screen.queryByRole("button", { name: "撕警徽" })).toBeNull();
    expect(screen.queryByRole("button", { name: "移交警徽" })).toBeNull();
    // issue #126：发言方向只在服务端给出 set_speech_direction 时显示
    expect(screen.queryByRole("button", { name: "从左发言" })).toBeNull();
    expect(screen.getByText("当前没有可用的警长行动。")).toBeInTheDocument();
  });

  it("sheriff_action：只渲染服务端 sheriff_options 给出的行动（警长方向 / 警下投票）", () => {
    const onSubmit = vi.fn();
    const { rerender } = render(
      <ActionBar
        {...base}
        prompt={prompt(["sheriff_action"], {
          phase: "SHERIFF_ELECTION",
          election_stage: "direction",
          sheriff_seat: 2,
          sheriff_options: ["set_speech_direction"],
        })}
        onSubmit={onSubmit}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "从右发言" }));
    expect(onSubmit).toHaveBeenLastCalledWith({
      tool: "sheriff_action",
      arguments: { action_type: "set_speech_direction", direction: "RIGHT" },
    });
    rerender(
      <ActionBar
        {...base}
        prompt={prompt(["sheriff_action"], {
          phase: "SHERIFF_ELECTION",
          election_stage: "vote",
          sheriff_candidates: [0, 1],
          sheriff_options: ["vote_sheriff"],
        })}
        onSubmit={onSubmit}
      />,
    );
    expect(screen.queryByRole("button", { name: "从右发言" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "1号" }));
    fireEvent.click(screen.getByRole("button", { name: "投给候选人" }));
    expect(onSubmit).toHaveBeenLastCalledWith({
      tool: "sheriff_action",
      arguments: { action_type: "vote_sheriff", target_seat: 1 },
    });
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
        lastResult={{
          ok: false,
          event_id: null,
          state_version: null,
          rejected_reason: "夜里不能发言",
        }}
        lastError="行动窗口已关闭"
        prompt={prompt(["speak"])}
        onSubmit={onSubmit}
      />,
    );
    expect(screen.getByRole("button", { name: "发送发言" })).toBeDisabled();
    expect(screen.getByText("夜里不能发言")).toBeInTheDocument();
    expect(screen.getByText("行动窗口已关闭")).toBeInTheDocument();
  });

  it("切换 tab 会清掉其他分组选中的目标", () => {
    const onSubmit = vi.fn();
    render(
      <ActionBar
        {...base}
        prompt={prompt(["vote", "sheriff_action"], {
          phase: "SHERIFF_ELECTION",
          election_stage: "vote",
          sheriff_candidates: [0, 1],
          vote_candidates: [0, 1],
          sheriff_options: ["vote_sheriff"],
        })}
        onSubmit={onSubmit}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "1号" }));
    fireEvent.click(screen.getByRole("tab", { name: "警长" }));
    expect(screen.getByRole("button", { name: "投给候选人" })).toBeDisabled();
  });

  it("一次只展示一个工具分组", () => {
    render(
      <ActionBar
        {...base}
        prompt={prompt(["speak", "vote"], { phase: "VOTE" })}
        onSubmit={vi.fn()}
      />,
    );
    expect(screen.getByLabelText("发言内容")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "确认投票" })).toBeNull();
    fireEvent.click(screen.getByRole("tab", { name: "投票" }));
    expect(screen.queryByLabelText("发言内容")).toBeNull();
    expect(screen.getByRole("button", { name: "确认投票" })).toBeInTheDocument();
  });

  it("state_version 变化重置文本、目标与自爆确认", () => {
    const mk = (v: number) =>
      prompt(["speak", "vote", "self_destruct"], { phase: "VOTE", state_version: v });
    const { rerender } = render(<ActionBar {...base} prompt={mk(1)} onSubmit={vi.fn()} />);
    fireEvent.change(screen.getByLabelText("发言内容"), { target: { value: "hello" } });
    fireEvent.click(screen.getByRole("tab", { name: "投票" }));
    fireEvent.click(screen.getByRole("button", { name: "1号" }));
    fireEvent.click(screen.getByRole("tab", { name: "自爆" }));
    fireEvent.click(screen.getByRole("button", { name: "自爆" }));
    expect(screen.getByRole("button", { name: "确认自爆" })).toBeInTheDocument();
    rerender(<ActionBar {...base} prompt={mk(2)} onSubmit={vi.fn()} />);
    expect(screen.getByLabelText("发言内容")).toHaveValue("");
    fireEvent.click(screen.getByRole("tab", { name: "投票" }));
    expect(screen.getByRole("button", { name: "确认投票" })).toBeDisabled();
    fireEvent.click(screen.getByRole("tab", { name: "自爆" }));
    expect(screen.queryByRole("button", { name: "确认自爆" })).toBeNull();
  });

  it("女巫缺少刀口时 save 不可提交", () => {
    render(
      <ActionBar
        {...base}
        prompt={prompt(["night_action"], {
          my_role: "WITCH",
          phase: "NIGHT_WITCH",
          private: { antidote_available: true, poison_available: true },
        })}
        onSubmit={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "救人" }));
    expect(screen.getByRole("button", { name: "确认行动" })).toBeDisabled();
  });

  describe("倒计时", () => {
    afterEach(() => vi.useRealTimers());

    it("每秒更新剩余秒数，卸载后清除 interval", () => {
      vi.useFakeTimers();
      let t = 9_000;
      const { unmount } = render(
        <ActionBar {...base} now={() => t} prompt={prompt(["speak"])} onSubmit={vi.fn()} />,
      );
      expect(screen.getByText("剩余 1000 秒")).toBeInTheDocument();
      t = 9_990;
      act(() => {
        vi.advanceTimersByTime(1000);
      });
      expect(screen.getByText("剩余 10 秒")).toBeInTheDocument();
      unmount();
      expect(vi.getTimerCount()).toBe(0);
    });
  });
});

describe("ActionBar · HUD 受控模式（UI 改版 PR ②）", () => {
  it("受控目标：点胶囊调用 onSelectTarget，不改内部状态；onSelectableChange 上报可选座位", () => {
    const onSelectTarget = vi.fn();
    const onSelectableChange = vi.fn();
    const { rerender } = render(
      <ActionBar
        {...base}
        prompt={prompt(["vote"])}
        onSubmit={vi.fn()}
        selectedTarget={null}
        onSelectTarget={onSelectTarget}
        onSelectableChange={onSelectableChange}
      />,
    );
    expect(onSelectableChange).toHaveBeenLastCalledWith([0, 1]);
    fireEvent.click(screen.getByRole("button", { name: "1号" }));
    expect(onSelectTarget).toHaveBeenCalledWith(1);
    expect(screen.getByRole("button", { name: "1号" })).toHaveAttribute("aria-pressed", "false");
    rerender(
      <ActionBar
        {...base}
        prompt={prompt(["vote"])}
        onSubmit={vi.fn()}
        selectedTarget={1}
        onSelectTarget={onSelectTarget}
        onSelectableChange={onSelectableChange}
      />,
    );
    expect(screen.getByRole("button", { name: "1号" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "确认投票" })).toBeEnabled();
  });

  it("发言分组不需要目标：onSelectableChange 上报 null", () => {
    const onSelectableChange = vi.fn();
    render(
      <ActionBar
        {...base}
        prompt={prompt(["speak"])}
        onSubmit={vi.fn()}
        onSelectableChange={onSelectableChange}
      />,
    );
    expect(onSelectableChange).toHaveBeenLastCalledWith(null);
  });

  it("layout=hud：投票主按钮文案「确认投票 · 2号」，无 prompt 时显示 idleText", () => {
    const { rerender } = render(
      <ActionBar {...base} prompt={null} onSubmit={vi.fn()} layout="hud" idleText="旁听中" />,
    );
    expect(screen.getByRole("status")).toHaveTextContent("旁听中");
    rerender(
      <ActionBar
        {...base}
        prompt={prompt(["vote"])}
        onSubmit={vi.fn()}
        layout="hud"
        selectedTarget={2}
        onSelectTarget={vi.fn()}
      />,
    );
    expect(screen.getByRole("button", { name: "确认投票 · 2号" })).toBeInTheDocument();
    expect(screen.getByText("把票投给谁？")).toBeInTheDocument();
  });

  it("layout=hud：狼刀主按钮「刀 · N号」+「空刀」；查验「查验 · N号」+「跳过」", () => {
    const onSubmit = vi.fn();
    const { rerender } = render(
      <ActionBar
        {...base}
        prompt={prompt(["night_action"], { my_role: "WEREWOLF", phase: "NIGHT_WEREWOLF" })}
        onSubmit={onSubmit}
        layout="hud"
        selectedTarget={1}
        onSelectTarget={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "刀 · 1号" }));
    expect(onSubmit).toHaveBeenLastCalledWith({
      tool: "night_action",
      arguments: { action_type: "kill", target_seat: 1 },
    });
    fireEvent.click(screen.getByRole("button", { name: "空刀" }));
    expect(onSubmit).toHaveBeenLastCalledWith({
      tool: "night_action",
      arguments: { action_type: "skip" },
    });
    rerender(
      <ActionBar
        {...base}
        prompt={prompt(["night_action"], { my_role: "SEER", phase: "NIGHT_SEER" })}
        onSubmit={onSubmit}
        layout="hud"
        selectedTarget={0}
        onSelectTarget={vi.fn()}
      />,
    );
    expect(screen.getByRole("button", { name: "查验 · 0号" })).toBeInTheDocument();
    expect(screen.getByText("今夜查验谁？")).toBeInTheDocument();
  });

  it("已出局玩家收到 shoot prompt 仍渲染行动区（Review Focus 3）", () => {
    render(
      <ActionBar
        {...base}
        prompt={prompt(["night_action"], {
          my_role: "HUNTER",
          my_status: "DEAD",
          phase: "HUNTER_SHOOT",
        })}
        onSubmit={vi.fn()}
        layout="hud"
        selectedTarget={1}
        onSelectTarget={vi.fn()}
      />,
    );
    expect(screen.getByText("带走谁？")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "开枪 · 1号" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "不开枪" })).toBeInTheDocument();
  });

  it("受控：先点「弃票」再从桌上选座位 → 弃票取消，主按钮变「确认投票 · N号」（Important 2）", () => {
    const onSelectTarget = vi.fn();
    const { rerender } = render(
      <ActionBar
        {...base}
        prompt={prompt(["vote"])}
        onSubmit={vi.fn()}
        layout="hud"
        selectedTarget={null}
        onSelectTarget={onSelectTarget}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "弃票" }));
    expect(screen.getByRole("button", { name: "确认 · 弃票" })).toBeInTheDocument();
    // 桌上点了 1 号：GamePage 把 selectedTarget 改成 1
    rerender(
      <ActionBar
        {...base}
        prompt={prompt(["vote"])}
        onSubmit={vi.fn()}
        layout="hud"
        selectedTarget={1}
        onSelectTarget={onSelectTarget}
      />,
    );
    expect(screen.getByRole("button", { name: "确认投票 · 1号" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "弃票" })).toHaveAttribute("aria-pressed", "false");
    expect(screen.getByRole("button", { name: "1号" })).toHaveAttribute("aria-pressed", "true");
  });
});
