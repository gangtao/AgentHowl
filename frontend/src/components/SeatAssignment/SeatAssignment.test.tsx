// SeatAssignment：选择档案后装成正确的 agents payload；同 memory_id 的档案在其它座位被禁用。

import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";
import type { StoredAgent } from "../../api/agents";
import { buildAgentsPayload, emptyAssignment, type SeatSlot } from "../../lib/seats";
import SeatAssignment from "./SeatAssignment";

function agent(id: string, name: string, memoryId: string | null): StoredAgent {
  return {
    agent_id: id,
    profile: {
      name,
      model: "qwen2.5:14b",
      temperature: 0.3,
      skills: [],
      memory_id: memoryId,
    },
    created_at: "2026-09-20T00:00:00+00:00",
    updated_at: "2026-09-20T00:00:00+00:00",
  };
}

const LIBRARY = [
  agent("a_fox", "狐语", "fox"),
  agent("a_nice", "老好人", null),
];

/** 受控组件的有状态外壳：把分配结果交给 onPayload 以便断言。 */
function Harness({ onPayload }: { onPayload(p: Record<string, unknown>): void }): JSX.Element {
  const [assignment, setAssignment] = useState<SeatSlot[]>(emptyAssignment(4));
  const [fill, setFill] = useState<string | null>(null);
  return (
    <>
      <SeatAssignment
        library={LIBRARY}
        assignment={assignment}
        fill={fill}
        onAssign={(seat, agentId) =>
          setAssignment((prev) => prev.map((s) => (s.seat === seat ? { ...s, agentId } : s)))
        }
        onFill={setFill}
        onAllRandom={() => setAssignment(emptyAssignment(4))}
        onShuffle={vi.fn()}
        onNewAgent={vi.fn()}
      />
      <button
        type="button"
        onClick={() => onPayload(buildAgentsPayload(assignment, fill, LIBRARY))}
      >
        dump
      </button>
    </>
  );
}

describe("SeatAssignment", () => {
  it("选择档案后 payload 正确（座位专属 / 填满 * / 随机 bot 不写）", () => {
    const onPayload = vi.fn();
    render(<Harness onPayload={onPayload} />);

    fireEvent.change(screen.getByLabelText("0号 座位"), { target: { value: "a_fox" } });
    fireEvent.change(screen.getByLabelText("2号 座位"), { target: { value: "a_nice" } });
    fireEvent.change(screen.getByLabelText("填满其余座位"), { target: { value: "a_nice" } });
    fireEvent.click(screen.getByRole("button", { name: "dump" }));

    const payload = onPayload.mock.calls.at(-1)?.[0] as Record<string, { name?: string | null }>;
    expect(Object.keys(payload).sort()).toEqual(["*", "0", "2"]);
    expect(payload["0"]?.name).toBe("狐语");
    expect(payload["*"]?.name).toBe("老好人");
    // 1、3 号未分配 → 随机 bot / 由 "*" 覆盖，不写入
    expect(payload["1"]).toBeUndefined();
  });

  it("同 memory_id 的档案在其它座位下拉中被禁用并提示座位号", () => {
    render(<Harness onPayload={vi.fn()} />);
    fireEvent.change(screen.getByLabelText("0号 座位"), { target: { value: "a_fox" } });

    const otherSeat = screen.getByLabelText("1号 座位");
    const foxOption = within(otherSeat).getByRole("option", { name: /狐语/ });
    expect(foxOption).toBeDisabled();
    expect(foxOption.textContent).toContain("记忆已在 0号 使用");

    // 无 memory_id 的档案不受限制
    expect(within(otherSeat).getByRole("option", { name: "老好人" })).not.toBeDisabled();
    // 自己那一座仍可选中
    expect(
      within(screen.getByLabelText("0号 座位")).getByRole("option", { name: "狐语" }),
    ).not.toBeDisabled();
  });

  it("含 memory_id 的档案不能用于「填满其余座位」", () => {
    render(<Harness onPayload={vi.fn()} />);
    const fillSelect = screen.getByLabelText("填满其余座位");
    expect(within(fillSelect).getByRole("option", { name: /狐语/ })).toBeDisabled();
    expect(within(fillSelect).getByRole("option", { name: "老好人" })).not.toBeDisabled();
  });

  it("「全部随机 bot」清空所有座位", () => {
    const onPayload = vi.fn();
    render(<Harness onPayload={onPayload} />);
    fireEvent.change(screen.getByLabelText("0号 座位"), { target: { value: "a_fox" } });
    fireEvent.click(screen.getByRole("button", { name: "全部随机 bot" }));
    fireEvent.click(screen.getByRole("button", { name: "dump" }));
    expect(onPayload.mock.calls.at(-1)?.[0]).toEqual({});
  });
});
