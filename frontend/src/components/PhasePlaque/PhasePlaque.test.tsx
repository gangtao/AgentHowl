import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import fixture from "../../engine/__fixtures__/std_9_kill_side-3.json";
import { initialState } from "../../engine/reduce";
import type { GameMeta, GameState } from "../../engine/types";
import { plaqueLines } from "../../lib/phaseText";
import PhasePlaque from "./PhasePlaque";

const meta = fixture.meta as unknown as GameMeta;
const states = fixture.states as unknown as GameState[];
const blank = initialState(meta);
const daySpeech = states.find((s) => s.phase === "DAY_SPEECH" && s.round === 2) as GameState;
const wolfNight = states.find((s) => s.phase === "NIGHT_WEREWOLF") as GameState;

describe("plaqueLines（规格 §4.1 阶段木牌）", () => {

  it("白天发言副标按本轮实际方向：基准顺时针的偶数轮标「逆时针」（用户反馈：顺序和标签对不上号）", () => {
    const even: GameState = {
      ...daySpeech,
      round: 2,
      sheriff_seat: 3,
      sheriff_speech_direction: "RIGHT",
      config: { ...daySpeech.config, speech_order_rule: "SHERIFF_DECIDES" },
    };
    expect(plaqueLines(even, [], null, 100).sub).toContain("警长 3号 · 逆时针");
    expect(plaqueLines({ ...even, round: 3 }, [], null, 100).sub).toContain("警长 3号 · 顺时针");
  });
  it("白天发言：标题与副标", () => {
    const l = plaqueLines(daySpeech, [], null, 100);
    expect(l.title).toBe("第 2 轮 · 白天 · 发言");
    expect(l.sub).toMatch(/^(警长 \d+号|无警长) · (顺时针|逆时针) · \d+\/9 存活$/);
  });

  it("狼人夜：第 N 夜 · 狼人行动，副标「天黑请闭眼 · 狼人请睁眼」", () => {
    const l = plaqueLines(wolfNight, [], null, 100);
    expect(l.title).toBe(`第 ${wolfNight.round} 夜 · 狼人行动`);
    expect(l.sub).toMatch(/^天黑请闭眼 · 狼人请睁眼 · \d+\/9 存活$/);
  });

  it("折叠夜晚 NIGHT：第 N 夜 · 夜晚", () => {
    const l = plaqueLines({ ...blank, phase: "NIGHT", round: 3 }, [], null, 10);
    expect(l.title).toBe("第 3 夜 · 夜晚");
    expect(l.sub).toMatch(/^天黑请闭眼 · 9\/9 存活$/);
  });

  it("投票：已投 / 票权 / 存活", () => {
    const vote = states.find((s) => s.phase === "VOTE") as GameState;
    const i = states.indexOf(vote);
    const events = (fixture.events as unknown as GameState[]).slice(0, i + 1);
    const l = plaqueLines(vote, events as never, null, 100);
    expect(l.title).toBe(`第 ${vote.round} 轮 · 白天 · 投票`);
    expect(l.sub).toMatch(/^已投 \d+\/\d+ · 警长 1\.5 票 · \d+\/9 存活$/);
  });

  it("竞选：子阶段 + 上警人数", () => {
    const st: GameState = {
      ...blank,
      phase: "SHERIFF_ELECTION",
      election_stage: "speech",
      sheriff_declared: [1, 2, 3],
      round: 1,
    };
    const l = plaqueLines(st, [], null, 10);
    expect(l.title).toBe("第 1 轮 · 白天 · 警长竞选");
    expect(l.sub).toBe("上警发言 · 3 人上警 · 9/9 存活");
  });

  it("终局：游戏结束", () => {
    const over = states[states.length - 1] as GameState;
    expect(plaqueLines(over, [], null, 129).title).toBe(`第 ${over.round} 轮 · 游戏结束`);
  });

  it("回放时追加 回放到 seq", () => {
    expect(plaqueLines(daySpeech, [], 40, 100).sub).toMatch(/ · 回放到 seq 40 \/ 100$/);
    expect(plaqueLines(daySpeech, [], 100, 100).sub).not.toMatch(/回放到/);
  });

  it("组件渲染两行", () => {
    render(<PhasePlaque state={daySpeech} events={[]} cursor={null} total={100} />);
    expect(screen.getByText("第 2 轮 · 白天 · 发言")).toBeInTheDocument();
  });
});
