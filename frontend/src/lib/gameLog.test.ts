// logEntries（规格 §6.1）：事件 → 对局记录条目（倒序、分组 / 签、日夜标签、发言自称）。

import { describe, expect, it } from "vitest";
import fixture from "../engine/__fixtures__/std_9_kill_all-3.json";
import type { Event } from "../engine/types";
import { currentClaims, logEntries } from "./gameLog";

const events = fixture.events as unknown as Event[];

describe("logEntries（规格 §6.1）", () => {
  const entries = logEntries(events);

  it("倒序、跳过 ROUND_STARTED / PHASE_CHANGED / VOTE_STARTED，其余事件一条不少", () => {
    const kept = events.filter(
      (e) => !["ROUND_STARTED", "PHASE_CHANGED", "VOTE_STARTED"].includes(e.type),
    );
    expect(entries.map((x) => x.seq)).toEqual(kept.map((e) => e.seq).reverse());
  });

  it.each<[string, string, string]>([
    ["PLAYER_SPOKE", "发言", "speech"],
    ["LAST_WORDS", "遗言", "speech"],
    ["VOTE_CAST", "投票", "vote"],
    ["VOTE_RESULT", "票型", "vote"],
    ["PLAYER_EXILED", "放逐", "vote"],
    ["SHERIFF_CANDIDACY", "上警", "vote"],
    ["ELECTION_STAGE_CHANGED", "竞选", "vote"],
    ["SHERIFF_BADGE_LOST", "警徽", "vote"],
    ["DEATH_ANNOUNCED", "天亮", "flow"],
    ["HUNTER_SHOT", "开枪", "flow"],
    ["WOLF_SELF_DESTRUCT", "自爆", "flow"],
    ["WOLF_KILL_PROPOSED", "刀口", "night"],
    ["NIGHT_RESOLVED", "结算", "night"],
    ["SEER_CHECKED", "验人", "seer"],
    ["ROLES_ASSIGNED", "发牌", "flow"],
    ["GAME_OVER", "终局", "flow"],
  ])("%s → 签「%s」分组 %s", (type, label, group) => {
    // SHERIFF_CANDIDACY running=false 的签是「不上警」，这里只看上警的那条
    const x = entries.find((e) => e.type === type && e.label !== "不上警");
    expect(x).toBeDefined();
    expect(x!.label).toBe(label);
    expect(x!.group).toBe(group);
  });

  it("不上警的 SHERIFF_CANDIDACY 签「不上警」", () => {
    const x = entries.find(
      (e) =>
        e.type === "SHERIFF_CANDIDACY" &&
        (events.find((ev) => ev.seq === e.seq)?.payload as { running: boolean }).running === false,
    );
    expect(x).toBeDefined();
    expect(x!.label).toBe("不上警");
  });

  it("正文去掉【…】/ [GM] / 缩进前缀；发言条目带 speech 字段；票型自己拼", () => {
    for (const x of entries) {
      expect(x.text).not.toMatch(/^(【|\[GM\]|\s|💥)/);
    }
    const sp = entries.find((e) => e.type === "PLAYER_SPOKE")!;
    expect(sp.speech?.kind).toBe("speech");
    expect(sp.speech?.content.length).toBeGreaterThan(0);
    const lw = entries.find((e) => e.type === "LAST_WORDS")!;
    expect(lw.speech?.kind).toBe("last_words");
    const results = entries.filter((e) => e.type === "VOTE_RESULT");
    const withTally = results.find((e) => /^\d+号 ·/.test(e.text))!;
    expect(withTally).toBeDefined();
    expect(withTally.text).toMatch(/^\d+号 ·[\d.]+( ｜ \d+号 ·[\d.]+)* → (\d+号 出局|平票 .+|无人出局)$/);
    // 全员弃票（空票型）也要有可读文案
    const empty = results.find((e) => !/^\d+号 ·/.test(e.text));
    if (empty) expect(empty.text).toBe("无有效票 → 无人出局");
  });

  it("day 标签：SEER_CHECKED 在「第 N 夜」，PLAYER_SPOKE 在「第 N 天」，开局事件在「开局」", () => {
    expect(entries.find((e) => e.type === "SEER_CHECKED")!.day).toMatch(/^第 \d+ 夜$/);
    expect(entries.find((e) => e.type === "PLAYER_SPOKE")!.day).toMatch(/^第 \d+ 天$/);
    expect(entries.find((e) => e.type === "GAME_CREATED")!.day).toBe("开局");
  });

  it("过滤掉 GM_ONLY 的流：公开条目的 day 与全量流相同", () => {
    const full = new Map(entries.map((x) => [x.seq, x.day]));
    for (const x of logEntries(events.filter((e) => e.visibility !== "GM_ONLY"))) {
      expect(x.day).toBe(full.get(x.seq));
    }
  });

  it("currentClaims：只取最新一天的发言自称，按座位去重保留最新，座位升序", () => {
    const claims = currentClaims(entries);
    const day = entries[0]!.day;
    const expected = new Map<number, string>();
    for (const x of [...entries].reverse()) {
      if (x.day === day && x.speech?.kind === "speech" && x.speech.claim && x.actor_seat !== null) {
        expected.set(x.actor_seat, x.speech.claim);
      }
    }
    expect(claims).toEqual([...expected.entries()].sort((a, b) => a[0] - b[0]));
    expect(currentClaims([])).toEqual([]);
    // 构造：同一天同一座位先自称预言家再自称女巫 → 保留女巫
    const spoke = entries.filter((e) => e.type === "PLAYER_SPOKE" && e.day === day);
    if (spoke.length >= 2) {
      const [a, b] = spoke as [typeof spoke[0], typeof spoke[0]];
      const faked = [
        { ...a, speech: { ...a.speech!, claim: "WITCH" as const } },
        { ...b, actor_seat: a.actor_seat, speech: { ...b.speech!, claim: "SEER" as const } },
      ];
      expect(currentClaims(faked)).toEqual([[a.actor_seat!, "WITCH"]]);
    }
  });
});
