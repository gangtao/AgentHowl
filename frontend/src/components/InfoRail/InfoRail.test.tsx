import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import fixture from "../../engine/__fixtures__/std_9_kill_side-3.json";
import { initialState } from "../../engine/reduce";
import type { Event, GameMeta, GameState } from "../../engine/types";
import InfoRail from "./InfoRail";
import { NightFlow } from "./NightFlow";

const meta = fixture.meta as unknown as GameMeta;
const events = fixture.events as unknown as Event[];
const states = fixture.states as unknown as GameState[];
const blank = initialState(meta);
const last = states[states.length - 1] as GameState;

const base = { state: last, events, speakingSeat: null, nightRows: [] };

describe("InfoRail（规格 §4.5）", () => {
  it("按 cards 顺序渲染对应标题", () => {
    render(<InfoRail {...base} cards={["news", "graveyard"]} />);
    const rail = screen.getByRole("complementary", { name: "信息栏" });
    const heads = within(rail).getAllByRole("heading");
    expect(heads.map((h) => h.textContent)).toEqual(["村镇公告", "墓地 · 按出局顺序"]);
  });

  it("墓地：角色全知显示角色名，未知显示 ✕", () => {
    const { unmount } = render(<InfoRail {...base} cards={["graveyard"]} />);
    expect(screen.getAllByText(/第 \d+ (天|夜)/).length).toBeGreaterThan(0);
    expect(screen.queryByText("✕")).toBeNull();
    unmount();
    const unknown: GameState = {
      ...last,
      players: last.players.map((p) => ({
        ...p,
        role: "VILLAGER" as const,
        faction: "GOOD" as const,
      })),
    };
    render(<InfoRail {...base} state={unknown} cards={["graveyard"]} />);
    expect(screen.getAllByRole("img", { name: "已出局" }).length).toBeGreaterThan(0);
  });

  it("药瓶：未使用 / 已使用", () => {
    render(<InfoRail {...base} cards={["potions"]} potions={{ antidote: true, poison: false }} />);
    expect(screen.getByText("解药").nextSibling).toHaveTextContent("未使用");
    expect(screen.getByText("毒药").nextSibling).toHaveTextContent("已使用");
  });

  it("验人记录：好人绿 / 狼人红", () => {
    const st: GameState = {
      ...blank,
      seer_log: {
        "0": [
          { round: 1, seat: 7, result: "GOOD" },
          { round: 2, seat: 3, result: "WOLF" },
        ],
      },
    };
    render(<InfoRail {...base} state={st} cards={["seerLog"]} />);
    expect(screen.getByText("好人")).toHaveAttribute("data-result", "GOOD");
    expect(screen.getByText("狼人")).toHaveAttribute("data-result", "WOLF");
    expect(screen.getByText(/第 2 夜 · 3号/)).toBeInTheDocument();
  });

  it("PK 发言回顾：PK 双方最近一条发言", () => {
    const pk: GameState = { ...last, phase: "VOTE_PK", vote_candidates: [0, 8] };
    render(<InfoRail {...base} state={pk} cards={["pkRecap"]} />);
    expect(screen.getByRole("heading", { name: "PK 发言回顾" })).toBeInTheDocument();
    expect(screen.getByText(/^0号/)).toBeInTheDocument();
    expect(screen.getByText(/^8号/)).toBeInTheDocument();
  });

  it("旧卡换皮后仍能渲染：order / election / votes / nightActs", () => {
    render(<InfoRail {...base} cards={["order", "election", "votes", "nightActs"]} />);
    expect(screen.getByText("发言顺序")).toBeInTheDocument();
    expect(screen.getByText("警长竞选")).toBeInTheDocument();
    expect(screen.getByText(/投票 · 第/)).toBeInTheDocument();
    expect(screen.getByText("夜晚")).toBeInTheDocument();
  });
});

describe("NightFlow", () => {
  const cfg = { ...blank.config, night_order: ["WEREWOLF", "WITCH", "SEER", "HUNTER"] };

  it("NIGHT_WITCH：狼人已行动、女巫行动中、预言家待行动", () => {
    render(<NightFlow state={{ ...blank, phase: "NIGHT_WITCH", config: cfg }} />);
    expect(screen.getByText(/狼人 · 已行动/)).toBeInTheDocument();
    expect(screen.getByText(/女巫 · 行动中/)).toHaveAttribute("data-now", "true");
    expect(screen.getByText(/预言家 · 待行动/)).toBeInTheDocument();
  });

  it("折叠夜晚 NIGHT：全部进行中，不崩", () => {
    render(<NightFlow state={{ ...blank, phase: "NIGHT", config: cfg }} />);
    expect(screen.getAllByText(/进行中/)).toHaveLength(4);
  });

  it("config 没有 night_order：按 roles 里出现的神职兜底", () => {
    const { night_order: _drop, ...noOrder } = blank.config as Record<string, unknown>;
    void _drop;
    render(
      <NightFlow
        state={{ ...blank, phase: "NIGHT_SEER", config: noOrder as GameState["config"] }}
      />,
    );
    expect(screen.getByText(/狼人/)).toBeInTheDocument();
    expect(screen.getByText(/预言家 · 行动中/)).toBeInTheDocument();
  });
});
