import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import NightOverlay from "./NightOverlay";

describe("NightOverlay 座位视角（issue #115）", () => {
  it("非本人行动阶段遮罩「请闭眼」；本人行动中不遮罩；白天不渲染", () => {
    const { rerender, container } = render(<NightOverlay phase="NIGHT_WEREWOLF" viewer={3} />);
    expect(screen.getByText("请闭眼，等待其他角色行动")).toBeInTheDocument();
    rerender(<NightOverlay phase="NIGHT_WEREWOLF" viewer={3} acting />);
    expect(container).toBeEmptyDOMElement();
    rerender(<NightOverlay phase="DAY_SPEECH" viewer={3} />);
    expect(container).toBeEmptyDOMElement();
  });
});
