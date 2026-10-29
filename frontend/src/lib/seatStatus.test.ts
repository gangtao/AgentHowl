// seatStatus（规格 §4.1 / R11）：座位名字下方那一行状态文案。

import { describe, expect, it } from "vitest";
import fixture from "../engine/__fixtures__/std_9_kill_all-3.json";
import type { GameState } from "../engine/types";
import { seatStatus } from "./seatStatus";

const states = fixture.states as unknown as GameState[];
const pick = (f: (s: GameState) => boolean): GameState => {
  const s = states.find(f);
  if (!s) throw new Error("fixture 里没有这样的状态");
  return s;
};
const none = { speaking: null, voteTargets: {} };

describe("seatStatus（规格 §4.1 / R11）", () => {
  it("发言阶段：speaking 优先；speech_idx 之前已发言、之后待发言；不在顺序里为空", () => {
    const s = pick(
      (x) => x.phase === "DAY_SPEECH" && x.speech_idx >= 1 && x.speech_order.length > 2,
    );
    const prev = s.speech_order[s.speech_idx - 1]!;
    const cur = s.speech_order[s.speech_idx]!;
    const later = s.speech_order[s.speech_order.length - 1]!;
    // 配音还在读上一位：上一位「发言中」、轮到的那位「待发言」
    expect(seatStatus(s, prev, { speaking: prev, voteTargets: {} })).toEqual({
      text: "发言中",
      tone: "now",
    });
    expect(seatStatus(s, cur, { speaking: prev, voteTargets: {} })).toEqual({
      text: "待发言",
      tone: "wait",
    });
    // 静音：轮到谁谁「发言中」，上一位「已发言」
    expect(seatStatus(s, cur, { speaking: cur, voteTargets: {} })).toEqual({
      text: "发言中",
      tone: "now",
    });
    expect(seatStatus(s, prev, { speaking: cur, voteTargets: {} })).toEqual({
      text: "已发言",
      tone: "done",
    });
    expect(seatStatus(s, later, { speaking: cur, voteTargets: {} }).text).toBe("待发言");
    const outside = s.players.find((p) => p.alive && !s.speech_order.includes(p.seat));
    if (outside) {
      expect(seatStatus(s, outside.seat, { speaking: cur, voteTargets: {} })).toEqual({
        text: "",
        tone: "none",
      });
    }
  });

  it("出局永远「出局」", () => {
    const s = pick((x) => x.players.some((p) => !p.alive) && x.phase === "DAY_SPEECH");
    const dead = s.players.find((p) => !p.alive)!;
    expect(seatStatus(s, dead.seat, { speaking: dead.seat, voteTargets: {} })).toEqual({
      text: "出局",
      tone: "dead",
    });
  });

  it("投票阶段：已投 / 弃票 / 未投 / 无票", () => {
    const s = pick((x) => x.phase === "VOTE");
    const voters = s.players.filter((p) => p.alive && p.can_vote).map((p) => p.seat);
    const [a, b, c] = voters as [number, number, number];
    expect(seatStatus(s, a, { speaking: null, voteTargets: { [a]: c } })).toEqual({
      text: `已投 ${c}号`,
      tone: "done",
    });
    expect(seatStatus(s, b, { speaking: null, voteTargets: { [b]: null } })).toEqual({
      text: "弃票",
      tone: "done",
    });
    expect(seatStatus(s, c, none)).toEqual({ text: "未投", tone: "wait" });
    const noVote = {
      ...s,
      players: s.players.map((p) => (p.seat === a ? { ...p, can_vote: false } : p)),
    };
    expect(seatStatus(noVote, a, none)).toEqual({ text: "无票", tone: "none" });
  });

  it("PK 投票：候选人「PK 中」", () => {
    const base = pick((x) => x.phase === "VOTE");
    const [a, b] = base.players.filter((p) => p.alive).map((p) => p.seat) as [number, number];
    const s: GameState = { ...base, phase: "VOTE_PK", vote_candidates: [a, b] };
    expect(seatStatus(s, a, none)).toEqual({ text: "PK 中", tone: "now" });
    expect(seatStatus(s, b, { speaking: null, voteTargets: { [b]: a } })).toEqual({
      text: "PK 中",
      tone: "now",
    });
  });

  it("竞选报名：上警 / 退水 / 空", () => {
    const s = pick(
      (x) =>
        x.phase === "SHERIFF_ELECTION" &&
        x.election_stage === "candidacy" &&
        x.sheriff_declared.length > 0,
    );
    const up = s.sheriff_declared.find((d) => !s.sheriff_withdrawn.includes(d))!;
    expect(seatStatus(s, up, none)).toEqual({ text: "上警", tone: "now" });
    const withdrawn: GameState = { ...s, sheriff_withdrawn: [up] };
    expect(seatStatus(withdrawn, up, none)).toEqual({ text: "退水", tone: "done" });
    const other = s.players.find((p) => p.alive && !s.sheriff_declared.includes(p.seat));
    if (other) expect(seatStatus(s, other.seat, none)).toEqual({ text: "", tone: "none" });
  });

  it("竞选发言阶段走发言规则；竞选投票阶段走投票规则", () => {
    const sp = pick(
      (x) => x.phase === "SHERIFF_ELECTION" && x.election_stage === "speech" && x.speech_order.length > 0,
    );
    const cur = sp.speech_order[sp.speech_idx] ?? sp.speech_order[0]!;
    expect(seatStatus(sp, cur, { speaking: cur, voteTargets: {} }).text).toBe("发言中");
    const vt: GameState = { ...sp, election_stage: "vote" };
    const voter = vt.players.find((p) => p.alive && p.can_vote && !vt.sheriff_candidates.includes(p.seat))!;
    expect(seatStatus(vt, voter.seat, none)).toEqual({ text: "未投", tone: "wait" });
  });

  it("夜间与公布死讯：空", () => {
    const n = pick((x) => x.phase === "NIGHT_WEREWOLF");
    const alive = n.players.find((p) => p.alive)!;
    expect(seatStatus(n, alive.seat, none)).toEqual({ text: "", tone: "none" });
  });
});
