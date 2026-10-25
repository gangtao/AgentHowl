// ActionBar（issue #115，PRD §7.3）：玩家视角的行动区，按 your_turn.available_tools 渲染。
// 零裁决：只做输入形态校验（必须选目标、内容非空），合法性由引擎裁决并经 action_result 回传。
// 倒计时到 0 不锁提交（客户端时钟可能快于服务端），只提示「可能已超时」。

import { useEffect, useMemo, useState } from "react";
import type { ActionResult, PlayerObservation, ToolCall, YourTurn } from "../../api/player";
import { ROLE_ZH } from "../../engine/phases";
import type { RoleType } from "../../engine/types";
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
  type NightActionType,
} from "../../lib/toolCalls";
import styles from "./ActionBar.module.css";

export interface ActionBarProps {
  prompt: YourTurn | null;
  pending: boolean;
  lastResult: ActionResult | null;
  lastError: string | null;
  onSubmit(call: ToolCall): void;
  /** 当前时间（秒）；测试注入，缺省 Date.now()/1000。 */
  now?: () => number;
}

const TOOL_ZH: Record<string, string> = {
  speak: "发言",
  vote: "投票",
  night_action: "夜间行动",
  sheriff_action: "警长",
  self_destruct: "自爆",
};

const NIGHT_ZH: Record<NightActionType, string> = {
  kill: "刀",
  check: "查验",
  save: "救人",
  poison: "毒",
  guard: "守护",
  shoot: "开枪",
  skip: "跳过",
};

const CLAIM_ROLES: RoleType[] = ["SEER", "WITCH", "HUNTER", "GUARD", "IDIOT", "VILLAGER", "WEREWOLF"];

const defaultNow = (): number => Date.now() / 1000;

function useCountdown(deadline: number | null, now: () => number): number | null {
  const [left, setLeft] = useState<number | null>(null);
  useEffect(() => {
    if (deadline === null) {
      setLeft(null);
      return;
    }
    const tick = (): void => setLeft(Math.max(0, Math.ceil(deadline - now())));
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, [deadline, now]);
  return left;
}

function SeatButtons({
  seats,
  selected,
  onPick,
}: {
  seats: number[];
  selected: number | null;
  onPick(seat: number): void;
}): JSX.Element {
  return (
    <div className={styles.row}>
      {seats.map((s) => (
        <button
          key={s}
          type="button"
          className={`btn btn-secondary ${styles.seatBtn} ${selected === s ? styles.seatOn : ""}`}
          aria-pressed={selected === s}
          onClick={() => onPick(s)}
        >
          {s}号
        </button>
      ))}
    </div>
  );
}

function privateNumber(obs: PlayerObservation, key: string): number | null {
  const v = obs.private[key];
  return typeof v === "number" ? v : null;
}

export default function ActionBar({
  prompt,
  pending,
  lastResult,
  lastError,
  onSubmit,
  now = defaultNow,
}: ActionBarProps): JSX.Element {
  const tools = useMemo(
    () => (prompt?.available_tools ?? []).filter((t) => ACTION_TOOLS.has(t)),
    [prompt],
  );
  const [tab, setTab] = useState<string | null>(null);
  const active = tab !== null && tools.includes(tab) ? tab : (tools[0] ?? null);
  const [text, setText] = useState("");
  const [claim, setClaim] = useState<RoleType | "">("");
  const [badgeFlow, setBadgeFlow] = useState("");
  const [target, setTarget] = useState<number | null>(null);
  const [abstain, setAbstain] = useState(false);
  const [night, setNight] = useState<NightActionType | null>(null);
  const [confirmDestruct, setConfirmDestruct] = useState(false);
  const left = useCountdown(prompt?.deadline_ts ?? null, now);

  // 新回合（state_version 变化）重置全部输入
  const version = prompt?.observation.state_version ?? -1;
  useEffect(() => {
    setTab(null);
    setText("");
    setClaim("");
    setBadgeFlow("");
    setTarget(null);
    setAbstain(false);
    setNight(null);
    setConfirmDestruct(false);
  }, [version]);

  if (prompt === null) {
    return (
      <div className={styles.idle} role="status">
        等待其他玩家…
      </div>
    );
  }
  const obs = prompt.observation;
  const submit = (call: ToolCall): void => {
    if (!pending) onSubmit(call);
  };

  let body: JSX.Element | null = null;
  if (active === "speak") {
    const showBadgeFlow = obs.phase === "SHERIFF_ELECTION" || obs.phase === "SHERIFF_PK";
    const flow = badgeFlow
      .split(/[,，\s]+/)
      .filter((s) => s !== "")
      .map(Number)
      .filter((n) => Number.isInteger(n));
    body = (
      <>
        <textarea
          className={`input ${styles.textarea}`}
          aria-label="发言内容"
          value={text}
          placeholder="轮到你发言…"
          onChange={(e) => setText(e.target.value)}
        />
        <div className={styles.row}>
          <label className={styles.info}>
            声明身份{" "}
            <select
              className="input"
              aria-label="声明身份"
              value={claim}
              onChange={(e) => setClaim(e.target.value as RoleType | "")}
            >
              <option value="">不声明</option>
              {CLAIM_ROLES.map((r) => (
                <option key={r} value={r}>
                  {ROLE_ZH[r]}
                </option>
              ))}
            </select>
          </label>
          {showBadgeFlow && (
            <label className={styles.info}>
              警徽流（座位号，逗号分隔）{" "}
              <input
                className="input"
                aria-label="警徽流"
                value={badgeFlow}
                onChange={(e) => setBadgeFlow(e.target.value)}
              />
            </label>
          )}
          <button
            type="button"
            className="btn btn-primary"
            disabled={pending || text.trim() === ""}
            onClick={() => submit(speakCall(text.trim(), claim || null, showBadgeFlow ? flow : []))}
          >
            发送发言
          </button>
        </div>
      </>
    );
  } else if (active === "vote") {
    const candidates = obs.vote_candidates.length > 0 ? obs.vote_candidates : aliveTargets(obs, false);
    body = (
      <>
        <SeatButtons
          seats={candidates}
          selected={abstain ? null : target}
          onPick={(s) => {
            setTarget(s);
            setAbstain(false);
          }}
        />
        <div className={styles.row}>
          <button
            type="button"
            className={`btn btn-secondary ${abstain ? styles.seatOn : ""}`}
            aria-pressed={abstain}
            onClick={() => {
              setAbstain(true);
              setTarget(null);
            }}
          >
            弃票
          </button>
          <button
            type="button"
            className="btn btn-primary"
            disabled={pending || (target === null && !abstain)}
            onClick={() => submit(voteCall(abstain ? null : target))}
          >
            确认投票
          </button>
        </div>
      </>
    );
  } else if (active === "night_action") {
    const options = nightOptions(obs);
    const killed = privateNumber(obs, "tonight_killed_seat");
    const teammates = Array.isArray(obs.private.teammates) ? (obs.private.teammates as number[]) : null;
    const proposals = obs.private.tonight_kill_proposals as Record<string, number> | undefined;
    const includeSelf = night === "kill" || night === "guard";
    const chosenTarget = night === "save" ? killed : target;
    body =
      options.length === 0 ? (
        <span className={styles.info}>本阶段无需你行动。</span>
      ) : (
        <>
          <div className={styles.info}>
            {teammates !== null && <span>狼队友：{teammates.length > 0 ? teammates.map((s) => `${s}号`).join("、") : "无"}{" "}</span>}
            {proposals !== undefined && Object.keys(proposals).length > 0 && (
              <span>
                本轮提案：
                {Object.entries(proposals)
                  .map(([from, to]) => `${from}号→${to}号`)
                  .join("，")}
                {" "}
              </span>
            )}
            {obs.my_role === "WITCH" && (
              <span>
                今晚刀口：{killed === null ? "未知" : `${killed}号`} · 解药
                {obs.private.antidote_available ? "可用" : "已用"} · 毒药
                {obs.private.poison_available ? "可用" : "已用"}
              </span>
            )}
          </div>
          <div className={styles.row}>
            {options.map((o) => (
              <button
                key={o}
                type="button"
                className={`btn btn-secondary ${night === o ? styles.seatOn : ""}`}
                aria-pressed={night === o}
                onClick={() => {
                  setNight(o);
                  setTarget(null);
                }}
              >
                {NIGHT_ZH[o]}
              </button>
            ))}
          </div>
          {night !== null && needsTarget(night) && (
            <SeatButtons seats={aliveTargets(obs, includeSelf)} selected={target} onPick={setTarget} />
          )}
          <div className={styles.row}>
            <button
              type="button"
              className="btn btn-primary"
              disabled={pending || night === null || (needsTarget(night) && target === null)}
              onClick={() => night !== null && submit(nightActionCall(night, chosenTarget))}
            >
              确认行动
            </button>
          </div>
        </>
      );
  } else if (active === "sheriff_action") {
    const isSheriff = obs.sheriff_seat === obs.my_seat;
    const isCandidate = obs.sheriff_candidates.includes(obs.my_seat);
    const voting =
      (obs.phase === "SHERIFF_ELECTION" && obs.election_stage === "vote") || obs.phase === "SHERIFF_PK";
    const badgeWindow = obs.badge_only || (isSheriff && obs.phase === "LAST_WORDS");
    const buttons: JSX.Element[] = [];
    if (badgeWindow) {
      buttons.push(
        <SeatButtons key="pass-seats" seats={aliveTargets(obs, false)} selected={target} onPick={setTarget} />,
        <button
          key="pass"
          type="button"
          className="btn btn-primary"
          disabled={pending || target === null}
          onClick={() => target !== null && submit(sheriffCall("pass_badge", { target }))}
        >
          移交警徽
        </button>,
        <button key="tear" type="button" className={`btn btn-secondary ${styles.danger}`} disabled={pending} onClick={() => submit(sheriffCall("tear_badge"))}>
          撕警徽
        </button>,
      );
    } else {
      if (obs.phase === "SHERIFF_ELECTION" && obs.election_stage === "candidacy" && !isCandidate) {
        buttons.push(
          <button key="run" type="button" className="btn btn-primary" disabled={pending} onClick={() => submit(sheriffCall("run_for_sheriff"))}>
            上警
          </button>,
        );
      }
      if (isCandidate) {
        buttons.push(
          <button key="withdraw" type="button" className="btn btn-secondary" disabled={pending} onClick={() => submit(sheriffCall("withdraw"))}>
            退水
          </button>,
        );
      }
      if (voting && !isCandidate && obs.sheriff_candidates.length > 0) {
        buttons.push(
          <SeatButtons key="vote-seats" seats={obs.sheriff_candidates} selected={target} onPick={setTarget} />,
          <button
            key="vote"
            type="button"
            className="btn btn-primary"
            disabled={pending || target === null}
            onClick={() => target !== null && submit(sheriffCall("vote_sheriff", { target }))}
          >
            投给候选人
          </button>,
        );
      }
      if (isSheriff) {
        buttons.push(
          <button key="left" type="button" className="btn btn-secondary" disabled={pending} onClick={() => submit(sheriffCall("set_speech_direction", { direction: "LEFT" }))}>
            从左发言
          </button>,
          <button key="right" type="button" className="btn btn-secondary" disabled={pending} onClick={() => submit(sheriffCall("set_speech_direction", { direction: "RIGHT" }))}>
            从右发言
          </button>,
        );
      }
    }
    body =
      buttons.length === 0 ? (
        <span className={styles.info}>当前没有可用的警长行动。</span>
      ) : (
        <div className={styles.row}>{buttons}</div>
      );
  } else if (active === "self_destruct") {
    body = (
      <div className={styles.row}>
        <span className={styles.info}>狼人自爆：立即出局并跳过本轮白天发言。</span>
        {confirmDestruct ? (
          <button type="button" className={`btn btn-secondary ${styles.danger}`} disabled={pending} onClick={() => submit(selfDestructCall())}>
            确认自爆
          </button>
        ) : (
          <button type="button" className={`btn btn-secondary ${styles.danger}`} disabled={pending} onClick={() => setConfirmDestruct(true)}>
            自爆
          </button>
        )}
      </div>
    );
  }

  return (
    <div className={styles.root} role="region" aria-label="行动区">
      {tools.length > 1 && (
        <div className={styles.tabs} role="tablist">
          {tools.map((t) => (
            <button
              key={t}
              type="button"
              role="tab"
              aria-selected={active === t}
              className={`${styles.tab} ${active === t ? styles.tabOn : ""}`}
              onClick={() => setTab(t)}
            >
              {TOOL_ZH[t] ?? t}
            </button>
          ))}
        </div>
      )}
      {body}
      <div className={styles.footer}>
        <span>
          {pending
            ? "提交中…"
            : left === null
              ? ""
              : left === 0
                ? "可能已超时，以服务端裁决为准"
                : `剩余 ${left} 秒`}
        </span>
        <span>
          {lastResult !== null && !lastResult.ok && lastResult.rejected_reason && (
            <span className={styles.error}>{lastResult.rejected_reason}</span>
          )}
          {lastError && <span className={styles.warn}> {lastError}</span>}
        </span>
      </div>
    </div>
  );
}
