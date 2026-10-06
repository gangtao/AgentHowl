import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import fixture from "../../engine/__fixtures__/std_9_kill_side-3.json";
import { useVoice } from "../../store/voice";
import type { GameState } from "../../engine/types";
import SpeakerSpotlight from "./SpeakerSpotlight";

const states = fixture.states as unknown as GameState[];
const state = states[states.length - 1] as GameState;

beforeEach(() => {
  useVoice.setState({ enabled: false, available: false, playing: null, queue: [] });
});

describe("SpeakerSpotlight", () => {
  it("无发言者不渲染", () => {
    const { container } = render(<SpeakerSpotlight state={state} seat={null} avatars={{}} />);
    expect(container).toBeEmptyDOMElement();
  });
  it("有头像时放大显示头像与座位名", () => {
    const seat = state.players[2]!.seat;
    render(
      <SpeakerSpotlight
        state={state}
        seat={seat}
        avatars={{ [seat]: "3f9a1c0b7e2d4a66.png" }}
      />,
    );
    expect(screen.getByRole("img")).toHaveAttribute("src", "/api/v1/avatars/3f9a1c0b7e2d4a66.png");
    expect(screen.getByRole("status")).toHaveTextContent(`${seat}号`);
    expect(screen.getByText("发言中")).toBeInTheDocument();
  });
  it("无头像时退回首字占位", () => {
    const p = state.players[0]!;
    render(<SpeakerSpotlight state={state} seat={p.seat} avatars={{}} />);
    expect(screen.queryByRole("img")).toBeNull();
    expect(screen.getByText(Array.from(p.display_name)[0] as string)).toBeInTheDocument();
  });
  it("useVoice.playing 非空时标签追加 🔊（issue #103）", () => {
    useVoice.setState({ playing: { seq: 1, part: 0 } });
    const seat = state.players[2]!.seat;
    render(<SpeakerSpotlight state={state} seat={seat} avatars={{}} />);
    expect(screen.getByText("发言中 🔊")).toBeInTheDocument();
  });
});
