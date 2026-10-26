import { describe, expect, it } from "vitest";
import type { PlayerObservation } from "../api/player";
import {
  ACTION_TOOLS,
  aliveTargets,
  needsTarget,
  nightActionCall,
  nightOptions,
  selfDestructCall,
  sheriffCall,
  speakCall,
  voteCall,
} from "./toolCalls";

function obs(extra: Partial<PlayerObservation>): PlayerObservation {
  return {
    game_id: "g",
    state_version: 1,
    my_seat: 2,
    my_role: "VILLAGER",
    my_status: "ALIVE",
    phase: "DAY_SPEECH",
    round: 1,
    seats: [0, 1, 2, 3].map((seat) => ({ seat, alive: seat !== 3, is_sheriff: false, idiot_revealed: false })),
    sheriff_seat: null,
    badge_flow_claims: {},
    private: {},
    election_stage: "",
    sheriff_candidates: [],
    vote_candidates: [],
    pk_speech_pending: false,
    badge_only: false,
    available_actions: [],
    ...extra,
  };
}

describe("toolCalls", () => {
  it("speak：content 必带，claim_role / badge_flow 可选", () => {
    expect(speakCall("你好")).toEqual({ tool: "speak", arguments: { content: "你好" } });
    expect(speakCall("我是预言家", "SEER", [1, 3])).toEqual({
      tool: "speak",
      arguments: { content: "我是预言家", claim_role: "SEER", badge_flow: [1, 3] },
    });
    expect(speakCall("x", null, [])).toEqual({ tool: "speak", arguments: { content: "x" } });
  });

  it("vote：目标或弃票，二者必有其一", () => {
    expect(voteCall(3)).toEqual({ tool: "vote", arguments: { target_seat: 3 } });
    expect(voteCall(null)).toEqual({ tool: "vote", arguments: { abstain: true } });
  });

  it("night_action / sheriff_action / self_destruct", () => {
    expect(nightActionCall("kill", 1)).toEqual({ tool: "night_action", arguments: { action_type: "kill", target_seat: 1 } });
    expect(nightActionCall("skip", null)).toEqual({ tool: "night_action", arguments: { action_type: "skip" } });
    expect(sheriffCall("run_for_sheriff")).toEqual({ tool: "sheriff_action", arguments: { action_type: "run_for_sheriff" } });
    expect(sheriffCall("vote_sheriff", { target: 4 })).toEqual({
      tool: "sheriff_action",
      arguments: { action_type: "vote_sheriff", target_seat: 4 },
    });
    expect(sheriffCall("set_speech_direction", { direction: "LEFT" })).toEqual({
      tool: "sheriff_action",
      arguments: { action_type: "set_speech_direction", direction: "LEFT" },
    });
    expect(selfDestructCall()).toEqual({ tool: "self_destruct", arguments: {} });
  });

  it("nightOptions 按角色与阶段", () => {
    expect(nightOptions(obs({ my_role: "WEREWOLF", phase: "NIGHT_WEREWOLF" }))).toEqual(["kill", "skip"]);
    expect(nightOptions(obs({ my_role: "SEER", phase: "NIGHT_SEER" }))).toEqual(["check"]);
    expect(nightOptions(obs({ my_role: "WITCH", phase: "NIGHT_WITCH" }))).toEqual(["save", "poison", "skip"]);
    expect(nightOptions(obs({ my_role: "GUARD", phase: "NIGHT_GUARD" }))).toEqual(["guard", "skip"]);
    expect(nightOptions(obs({ my_role: "HUNTER", phase: "HUNTER_SHOOT" }))).toEqual(["shoot", "skip"]);
    expect(nightOptions(obs({ my_role: "VILLAGER", phase: "NIGHT_WEREWOLF" }))).toEqual([]);
    expect(needsTarget("save")).toBe(false);
    expect(needsTarget("poison")).toBe(true);
  });

  it("aliveTargets 排除死者，可选排除自己", () => {
    expect(aliveTargets(obs({}), false)).toEqual([0, 1]);
    expect(aliveTargets(obs({}), true)).toEqual([0, 1, 2]);
    expect(ACTION_TOOLS.has("speak") && !ACTION_TOOLS.has("get_state")).toBe(true);
  });
});
