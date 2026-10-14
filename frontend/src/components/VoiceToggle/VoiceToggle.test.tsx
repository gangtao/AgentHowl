import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { useVoice } from "../../store/voice";
import VoiceToggle from "./VoiceToggle";

beforeEach(() => {
  useVoice.setState({ enabled: false, available: false, playing: null, queue: [] });
});

describe("VoiceToggle", () => {
  it("available=false 不渲染", () => {
    const { container } = render(<VoiceToggle />);
    expect(container).toBeEmptyDOMElement();
  });

  it("可用时渲染，点击切换 enabled 并显示「语音 开/关」", () => {
    useVoice.getState().markAvailable();
    render(<VoiceToggle />);

    const button = screen.getByRole("button");
    expect(button).toHaveTextContent("语音 关");
    expect(button).toHaveAttribute("aria-pressed", "false");

    fireEvent.click(button);

    expect(useVoice.getState().enabled).toBe(true);
    expect(button).toHaveTextContent("语音 开");
    expect(button).toHaveAttribute("aria-pressed", "true");
  });
});
