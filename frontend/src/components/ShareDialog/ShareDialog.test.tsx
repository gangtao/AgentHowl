import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import ShareDialog from "./ShareDialog";

describe("ShareDialog", () => {
  it("观众链接为 #/g/{id}?share=S", () => {
    render(<ShareDialog gameId="g_1" gmToken="G" shareToken="S" onEnter={vi.fn()} onLater={vi.fn()} />);
    expect((screen.getByLabelText(/观众链接/) as HTMLInputElement).value).toMatch(/#\/g\/g_1\?share=S$/);
    expect((screen.getByLabelText(/上帝视角链接/) as HTMLInputElement).value).toMatch(/\?gm=G$/);
  });
  it("shareToken=null 不显示观众链接；gmToken=null 不显示 GM 链接", () => {
    render(<ShareDialog gameId="g_1" gmToken={null} shareToken={null} onEnter={vi.fn()} onLater={vi.fn()} />);
    expect(screen.queryByLabelText(/观众链接/)).toBeNull();
    expect(screen.queryByLabelText(/上帝视角链接/)).toBeNull();
  });
});
