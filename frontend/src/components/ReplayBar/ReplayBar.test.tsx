// 冒烟测试：拖动 range 触发 onCursor；「回到直播」在 cursor=null 时禁用。

import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import ReplayBar from "./ReplayBar";

const segments = [
  { fromSeq: 1, toSeq: 20, kind: "night" as const },
  { fromSeq: 21, toSeq: 40, kind: "day" as const },
];

function renderBar(overrides: Partial<React.ComponentProps<typeof ReplayBar>> = {}): {
  onCursor: ReturnType<typeof vi.fn>;
} {
  const onCursor = vi.fn();
  render(
    <ReplayBar
      cursor={null}
      total={40}
      playing={false}
      speed={2}
      segments={segments}
      live={true}
      onCursor={onCursor}
      onPlay={vi.fn()}
      onPause={vi.fn()}
      onSpeed={vi.fn()}
      onStep={vi.fn()}
      onLive={vi.fn()}
      {...overrides}
    />,
  );
  return { onCursor };
}

describe("ReplayBar", () => {
  it("拖动 range 触发 onCursor", () => {
    const { onCursor } = renderBar();
    const slider = screen.getByRole("slider");
    fireEvent.change(slider, { target: { value: "17" } });
    expect(onCursor).toHaveBeenCalledWith(17);
  });

  it("cursor=null 时「回到直播」禁用，cursor 非 null 时可用", () => {
    const { unmount } = render(
      <ReplayBar
        cursor={null}
        total={40}
        playing={false}
        speed={2}
        segments={segments}
        live={true}
        onCursor={vi.fn()}
        onPlay={vi.fn()}
        onPause={vi.fn()}
        onSpeed={vi.fn()}
        onStep={vi.fn()}
        onLive={vi.fn()}
      />,
    );
    expect(screen.getByRole("button", { name: "回到直播" })).toBeDisabled();
    unmount();

    render(
      <ReplayBar
        cursor={17}
        total={40}
        playing={false}
        speed={2}
        segments={segments}
        live={true}
        onCursor={vi.fn()}
        onPlay={vi.fn()}
        onPause={vi.fn()}
        onSpeed={vi.fn()}
        onStep={vi.fn()}
        onLive={vi.fn()}
      />,
    );
    expect(screen.getByRole("button", { name: "回到直播" })).toBeEnabled();
  });
});
