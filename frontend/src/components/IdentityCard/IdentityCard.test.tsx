import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { PlayerObservation } from "../../api/player";
import fixture from "../../engine/__fixtures__/std_9_kill_side-3.json";
import { initialState } from "../../engine/reduce";
import type { GameMeta, GameState } from "../../engine/types";
import { identityLines } from "../../lib/identityLines";
import IdentityCard from "./IdentityCard";

const meta = fixture.meta as unknown as GameMeta;
const blank = initialState(meta);

function obsWith(
  priv: Record<string, unknown>,
  extra: Partial<PlayerObservation> = {},
): PlayerObservation {
  return {
    game_id: "g",
    state_version: 1,
    my_seat: 0,
    my_role: "VILLAGER",
    my_status: "ALIVE",
    phase: "DAY_SPEECH",
    round: 1,
    seats: [],
    sheriff_seat: null,
    badge_flow_claims: {},
    private: priv,
    election_stage: "",
    sheriff_candidates: [],
    vote_candidates: [],
    pk_speech_pending: false,
    badge_only: false,
    sheriff_options: [],
    available_actions: [],
    ...extra,
  };
}

const stateWith = (cfg: Record<string, unknown>, extra: Partial<GameState> = {}): GameState => ({
  ...blank,
  config: { ...blank.config, ...cfg },
  ...extra,
});

describe("identityLines（规格 §4.7 身份牌）", () => {
  it("狼：队友与屠边", () => {
    expect(
      identityLines(
        "WEREWOLF",
        obsWith({ teammates: [3, 9] }),
        stateWith({ win_condition: "kill_side" }),
      ),
    ).toEqual(["队友 3号 · 9号", "目标：屠边"]);
  });
  it("狼：无队友信息也不崩；屠城", () => {
    expect(identityLines("WEREWOLF", null, stateWith({ win_condition: "kill_all" }))).toEqual([
      "目标：屠城",
    ]);
  });
  it("女巫：药瓶 + 不能自救", () => {
    expect(
      identityLines(
        "WITCH",
        obsWith({ antidote_available: true, poison_available: false }),
        stateWith({ witch_self_save: false }),
      ),
    ).toEqual(["解药 1 · 毒药 0", "不能自救"]);
  });
  it("预言家：已验 2 人 · 1 狼 + 本人警徽流", () => {
    const st = stateWith(
      {},
      {
        seer_log: {
          "0": [
            { round: 1, seat: 7, result: "GOOD" },
            { round: 2, seat: 3, result: "WOLF" },
          ],
        },
        badge_flow_claims: { "0": [3, 5] },
      },
    );
    expect(identityLines("SEER", obsWith({}), st)).toEqual(["已验 2 人 · 1 狼", "警徽流 3 → 5"]);
  });
  it("猎人：可开枪；守卫 / 民：空", () => {
    expect(identityLines("HUNTER", obsWith({ can_shoot: true }), blank)).toEqual(["可开枪"]);
    expect(identityLines("GUARD", obsWith({}), blank)).toEqual([]);
    expect(identityLines("VILLAGER", null, blank)).toEqual([]);
  });
  it("竞选中本人已上警 → 追加「已上警 · 可退水」", () => {
    const st = stateWith({}, { phase: "SHERIFF_ELECTION", sheriff_candidates: [0, 2] });
    expect(identityLines("VILLAGER", obsWith({}), st)).toEqual(["已上警 · 可退水"]);
  });
});

describe("IdentityCard", () => {
  it("存活：角色名与说明行", () => {
    render(
      <IdentityCard
        seat={0}
        name="Gang"
        role="WEREWOLF"
        alive
        lines={["队友 3号 · 9号", "目标：屠边"]}
      />,
    );
    expect(screen.getByText("0号 · Gang")).toBeInTheDocument();
    expect(screen.getByText("狼人")).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "狼人" })).toBeInTheDocument();
    expect(screen.getByText("目标：屠边")).toBeInTheDocument();
  });
  it("出局：标题「已出局」+ 徽记 dead", () => {
    render(<IdentityCard seat={0} name="Gang" role="HUNTER" alive={false} lines={[]} />);
    expect(screen.getByText("已出局")).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "已出局" })).toBeInTheDocument();
  });
  it("角色未知：「身份未知」", () => {
    render(<IdentityCard seat={4} name="Bot4" role={null} alive lines={[]} />);
    expect(screen.getByRole("img", { name: "身份未知" })).toBeInTheDocument();
  });
});
