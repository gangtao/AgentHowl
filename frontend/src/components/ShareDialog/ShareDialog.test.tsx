import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import ShareDialog from "./ShareDialog";

describe("ShareDialog", () => {
  it("观众链接为 #/g/{id}?share=S", () => {
    render(
      <ShareDialog gameId="g_1" gmToken="G" shareToken="S" onEnter={vi.fn()} onLater={vi.fn()} />,
    );
    expect((screen.getByLabelText(/观众链接/) as HTMLInputElement).value).toMatch(
      /#\/g\/g_1\?share=S$/,
    );
    expect((screen.getByLabelText(/上帝视角链接/) as HTMLInputElement).value).toMatch(/\?gm=G$/);
  });
  it("shareToken=null 不显示观众链接；gmToken=null 不显示 GM 链接", () => {
    render(
      <ShareDialog
        gameId="g_1"
        gmToken={null}
        shareToken={null}
        onEnter={vi.fn()}
        onLater={vi.fn()}
      />,
    );
    expect(screen.queryByLabelText(/观众链接/)).toBeNull();
    expect(screen.queryByLabelText(/上帝视角链接/)).toBeNull();
  });
  it("主按钮文案：有 GM 链接「进入上帝视角」，无 GM 链接「进入对局」（issue #120）", () => {
    const { unmount } = render(
      <ShareDialog gameId="g_1" gmToken="G" shareToken="S" onEnter={vi.fn()} onLater={vi.fn()} />,
    );
    expect(screen.getByRole("button", { name: "进入上帝视角 →" })).toBeInTheDocument();
    unmount();
    render(
      <ShareDialog
        gameId="g_1"
        gmToken={null}
        shareToken="S"
        onEnter={vi.fn()}
        onLater={vi.fn()}
      />,
    );
    expect(screen.getByRole("button", { name: "进入对局 →" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "进入上帝视角 →" })).toBeNull();
  });
  it("标题统一为「传 · 分享对局」", () => {
    render(
      <ShareDialog gameId="g_1" gmToken="G" shareToken="S" onEnter={vi.fn()} onLater={vi.fn()} />,
    );
    expect(screen.getByRole("dialog", { name: "传 · 分享对局" })).toBeInTheDocument();
  });
  it("没有观众链接时不显示观众说明行", () => {
    render(
      <ShareDialog
        gameId="g_1"
        gmToken="G"
        shareToken={null}
        onEnter={vi.fn()}
        onLater={vi.fn()}
      />,
    );
    expect(screen.queryByText(/不含任何身份/)).toBeNull();
  });
});
