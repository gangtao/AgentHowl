// ActionBar（issue #115，PRD §7.3；UI 改版 PR ② 加 HUD 布局）：玩家视角的行动区，按 your_turn.available_tools 渲染。
// 零裁决：只做输入形态校验（必须选目标、内容非空），合法性由引擎裁决并经 action_result 回传。
// 倒计时到 0 不锁提交（客户端时钟可能快于服务端），只提示「可能已超时」。
//
// 目标座位可受控（selectedTarget / onSelectTarget）：GamePage 持有它，桌上点座位与这里点胶囊等价；
// onSelectableChange 把「当前分组可选的座位」上报给 GamePage 去点亮桌上座位。不传这些 props 时退回
// 内部状态，与旧行为逐字相同。

import { useEffect, useMemo, useRef, useState } from "react";
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
  /** 已受理、等裁决（同步窗口）：只显示等待文案。 */
  accepted?: boolean;
  lastResult: ActionResult | null;
  lastError: string | null;
  onSubmit(call: ToolCall): void;
  /** 当前时间（秒）；测试注入，缺省 Date.now()/1000。 */
  now?: () => number;
  /** 受控目标座位；传了就不用内部状态。 */
  selectedTarget?: number | null;
  onSelectTarget?(seat: number | null): void;
  /** 当前分组需要目标时上报可选座位，否则 null。 */
  onSelectableChange?(seats: number[] | null): void;
  /** hud：设计稿 3a 底部 HUD 布局；缺省 panel 不变。 */
  layout?: "panel" | "hud";
  /** 无 prompt 时的文案（缺省「等待其他玩家…」）。 */
  idleText?: string;
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

/** HUD 的标题（规格 §4.7）。 */
const HUD_HEADING: Record<string, string> = {
  vote: "把票投给谁？",
  kill: "今夜，狼群要咬谁？",
  check: "今夜查验谁？",
  guard: "今夜守护谁？",
  shoot: "带走谁？",
  witch: "救，还是毒？",
  vote_sheriff: "投给哪位候选人？",
  pass_badge: "警徽交给谁？",
};

const CLAIM_ROLES: RoleType[] = [
  "SEER",
  "WITCH",
  "HUNTER",
  "GUARD",
  "IDIOT",
  "VILLAGER",
  "WEREWOLF",
];

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
  hud,
}: {
  seats: number[];
  selected: number | null;
  onPick(seat: number): void;
  hud: boolean;
}): JSX.Element {
  return (
    <div className={styles.row}>
      {seats.map((s) => (
        <button
          key={s}
          type="button"
          className={
            hud
              ? `${styles.chip} ${selected === s ? styles.chipOn : ""}`
              : `btn btn-secondary ${styles.seatBtn} ${selected === s ? styles.seatOn : ""}`
          }
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

/** HUD 下夜间不用先点「刀 / 查验」再选人：有唯一需要目标的主动作就直接当作当前动作。 */
function defaultNightAction(options: NightActionType[]): NightActionType | null {
  for (const o of ["kill", "check", "guard", "shoot"] as const) if (options.includes(o)) return o;
  return null;
}

export default function ActionBar({
  prompt,
  pending,
  accepted = false,
  lastResult,
  lastError,
  onSubmit,
  now = defaultNow,
  selectedTarget,
  onSelectTarget,
  onSelectableChange,
  layout = "panel",
  idleText = "等待其他玩家…",
}: ActionBarProps): JSX.Element {
  const hud = layout === "hud";
  const tools = useMemo(
    () => (prompt?.available_tools ?? []).filter((t) => ACTION_TOOLS.has(t)),
    [prompt],
  );
  const [tab, setTab] = useState<string | null>(null);
  // 默认分组：警徽处置窗口先落在 sheriff_action（issue #141，窗口内发言会被拒）；
  // PK 发言待讲时落在 speak；否则取首个工具
  const preferred = prompt?.observation.badge_only
    ? "sheriff_action"
    : prompt?.observation.pk_speech_pending
      ? "speak"
      : null;
  const fallback = preferred !== null && tools.includes(preferred) ? preferred : (tools[0] ?? null);
  const active = tab !== null && tools.includes(tab) ? tab : fallback;
  const [text, setText] = useState("");
  const [claim, setClaim] = useState<RoleType | "">("");
  const [badgeFlow, setBadgeFlow] = useState("");
  const [innerTarget, setInnerTarget] = useState<number | null>(null);
  const [abstain, setAbstain] = useState(false);
  const [night, setNight] = useState<NightActionType | null>(null);
  const [confirmDestruct, setConfirmDestruct] = useState(false);
  const left = useCountdown(prompt?.deadline_ts ?? null, now);

  const controlled = selectedTarget !== undefined;
  const target = controlled ? selectedTarget : innerTarget;
  const setTarget = (v: number | null): void => {
    if (controlled) onSelectTarget?.(v);
    else setInnerTarget(v);
  };

  const selectTab = (t: string): void => {
    setTab(t);
    setTarget(null);
    setAbstain(false);
    setNight(null);
    setConfirmDestruct(false);
  };

  // 新回合（state_version 变化）重置全部输入
  const version = prompt?.observation.state_version ?? -1;
  // 时限总长：同一回合里见过的最大剩余秒数（服务端不单独下发时限）；HUD 进度条用。
  const limitRef = useRef<number>(0);
  useEffect(() => {
    setTab(null);
    setText("");
    setClaim("");
    setBadgeFlow("");
    setInnerTarget(null);
    setAbstain(false);
    setNight(null);
    setConfirmDestruct(false);
    limitRef.current = 0;
    // 受控目标也要在新回合清空；onSelectTarget 由父组件保证稳定与否都无所谓——只在 version 变化时调一次
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [version]);
  if (left !== null && left > limitRef.current) limitRef.current = left;
  // 受控模式：桌上点了座位（selectedTarget 非空）就取消「弃票」，否则桌面高亮与主按钮会互相矛盾（终审 Important 2）。
  useEffect(() => {
    if (controlled && selectedTarget !== null && selectedTarget !== undefined) setAbstain(false);
  }, [controlled, selectedTarget]);

  const obs = prompt?.observation ?? null;
  const options = obs !== null && active === "night_action" ? nightOptions(obs) : [];
  const nightAct: NightActionType | null =
    night ?? (hud && active === "night_action" ? defaultNightAction(options) : null);

  // 当前分组可选座位（上报给 GamePage 点亮桌上座位）
  const selectable = useMemo<number[] | null>(() => {
    if (obs === null) return null;
    if (active === "vote") {
      return obs.vote_candidates.length > 0 ? obs.vote_candidates : aliveTargets(obs, false);
    }
    if (active === "night_action") {
      if (nightAct === null || !needsTarget(nightAct)) return null;
      return aliveTargets(obs, nightAct === "kill" || nightAct === "guard");
    }
    if (active === "sheriff_action") {
      const so = obs.sheriff_options ?? [];
      if (so.includes("vote_sheriff")) return obs.sheriff_candidates;
      if (so.includes("pass_badge")) return aliveTargets(obs, false);
    }
    return null;
  }, [obs, active, nightAct]);
  const selectableKey = selectable === null ? "null" : selectable.join(",");
  const selectableRef = useRef(selectable);
  selectableRef.current = selectable;
  const onSelectableRef = useRef(onSelectableChange);
  onSelectableRef.current = onSelectableChange;
  useEffect(() => {
    onSelectableRef.current?.(selectableRef.current);
  }, [selectableKey]);

  if (prompt === null || obs === null) {
    return (
      <div className={hud ? styles.hudIdle : styles.idle} role="status">
        {hud ? <span className={styles.hudIdleTitle}>{idleText}</span> : idleText}
      </div>
    );
  }
  if (accepted) {
    return (
      <div className={hud ? styles.hudIdle : styles.idle} role="status">
        已提交，等待其他玩家行动后裁决…
      </div>
    );
  }
  const submit = (call: ToolCall): void => {
    if (!pending) onSubmit(call);
  };

  // ---- 各分组的主体（中间区域）与主按钮（HUD 右侧 / panel 内联） ----
  let body: JSX.Element | null = null;
  let primary: JSX.Element | null = null;
  let heading: { title: string; sub?: string } | null = null;
  const targetSub = `点圆桌上的座位选择${target !== null ? ` · 当前 ${target}号` : ""}`;

  if (active === "speak") {
    const showBadgeFlow = obs.phase === "SHERIFF_ELECTION" || obs.phase === "SHERIFF_PK";
    const flow = badgeFlow
      .split(/[,，\s]+/)
      .filter((s) => s !== "")
      .map(Number)
      .filter((n) => Number.isInteger(n));
    const isLastWords = obs.phase === "LAST_WORDS";
    const placeholder = isLastWords
      ? "写下遗言…"
      : showBadgeFlow
        ? "轮到你时在此陈述竞选理由…（草稿会保留）"
        : "轮到你发言…";
    primary = (
      <button
        type="button"
        className={`btn ${isLastWords && hud ? "btn-danger" : "btn-primary"}`}
        disabled={pending || text.trim() === ""}
        onClick={() => submit(speakCall(text.trim(), claim || null, showBadgeFlow ? flow : []))}
      >
        {isLastWords && hud ? "留下遗言" : "发送发言"}
      </button>
    );
    body = (
      <>
        {hud && (
          <div className={styles.row}>
            <label className={styles.info}>
              声明身份{" "}
              <select
                className={`input ${styles.select}`}
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
                警徽流{" "}
                <input
                  className={`input ${styles.flowInput}`}
                  aria-label="警徽流"
                  placeholder="3, 5"
                  value={badgeFlow}
                  onChange={(e) => setBadgeFlow(e.target.value)}
                />
              </label>
            )}
          </div>
        )}
        <textarea
          className={`input ${styles.textarea}`}
          aria-label="发言内容"
          value={text}
          placeholder={placeholder}
          onChange={(e) => setText(e.target.value)}
        />
        {!hud && (
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
            {primary}
          </div>
        )}
      </>
    );
  } else if (active === "vote") {
    const candidates =
      obs.vote_candidates.length > 0 ? obs.vote_candidates : aliveTargets(obs, false);
    heading = { title: HUD_HEADING.vote as string, sub: targetSub };
    primary = (
      <button
        type="button"
        className="btn btn-primary"
        disabled={pending || (target === null && !abstain)}
        onClick={() => submit(voteCall(abstain ? null : target))}
      >
        {hud
          ? abstain
            ? "确认 · 弃票"
            : target !== null
              ? `确认投票 · ${target}号`
              : "确认投票"
          : "确认投票"}
      </button>
    );
    body = (
      <>
        <SeatButtons
          hud={hud}
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
            className={
              hud
                ? `${styles.chip} ${styles.chipDashed} ${abstain ? styles.chipOn : ""}`
                : `btn btn-secondary ${abstain ? styles.seatOn : ""}`
            }
            aria-pressed={abstain}
            onClick={() => {
              setAbstain(true);
              setTarget(null);
            }}
          >
            弃票
          </button>
          {!hud && primary}
        </div>
      </>
    );
  } else if (active === "night_action") {
    const killed = privateNumber(obs, "tonight_killed_seat");
    const teammates = Array.isArray(obs.private.teammates)
      ? (obs.private.teammates as number[])
      : null;
    const proposals = obs.private.tonight_kill_proposals as Record<string, number> | undefined;
    const includeSelf = nightAct === "kill" || nightAct === "guard";
    const chosenTarget = nightAct === "save" ? killed : target;
    const isWitch = options.includes("save") || options.includes("poison");
    if (options.length === 0) {
      body = <span className={styles.info}>本阶段无需你行动。</span>;
    } else if (hud) {
      const skipZh: Record<string, string> = {
        kill: "空刀",
        check: "跳过",
        guard: "空守",
        shoot: "不开枪",
      };
      if (isWitch) {
        heading = {
          title: HUD_HEADING.witch as string,
          sub: night === "poison" ? targetSub : "毒药需点圆桌座位选目标",
        };
        body = (
          <>
            <div className={styles.row}>
              <button
                type="button"
                className="btn btn-ok"
                disabled={pending || killed === null}
                onClick={() => submit(nightActionCall("save", killed))}
              >
                {killed === null ? "解药 · 今夜无人被刀" : `解药 · 救 ${killed}号`}
              </button>
              <button
                type="button"
                className="btn btn-danger"
                aria-pressed={night === "poison"}
                disabled={pending || (night === "poison" && target === null)}
                onClick={() => {
                  if (night !== "poison") {
                    setNight("poison");
                    setTarget(null);
                  } else if (target !== null) {
                    submit(nightActionCall("poison", target));
                  }
                }}
              >
                {night === "poison" && target !== null ? `毒药 · ${target}号` : "毒药 · 选目标"}
              </button>
              <button
                type="button"
                className="btn btn-ghost"
                disabled={pending}
                onClick={() => submit(nightActionCall("skip", null))}
              >
                不用药
              </button>
            </div>
            {night === "poison" && (
              <SeatButtons
                hud
                seats={aliveTargets(obs, false)}
                selected={target}
                onPick={setTarget}
              />
            )}
          </>
        );
      } else if (nightAct !== null) {
        heading = { title: HUD_HEADING[nightAct] ?? NIGHT_ZH[nightAct], sub: targetSub };
        body = (
          <SeatButtons
            hud
            seats={aliveTargets(obs, includeSelf)}
            selected={target}
            onPick={setTarget}
          />
        );
        primary = (
          <>
            <button
              type="button"
              className={`btn ${nightAct === "kill" || nightAct === "shoot" ? "btn-danger" : "btn-primary"}`}
              disabled={pending || target === null}
              onClick={() => target !== null && submit(nightActionCall(nightAct, target))}
            >
              {NIGHT_ZH[nightAct]}
              {target !== null ? ` · ${target}号` : ""}
            </button>
            {options.includes("skip") && (
              <button
                type="button"
                className="btn btn-ghost"
                disabled={pending}
                onClick={() => submit(nightActionCall("skip", null))}
              >
                {skipZh[nightAct] ?? "跳过"}
              </button>
            )}
          </>
        );
      }
    } else {
      body = (
        <>
          <div className={styles.info}>
            {teammates !== null && (
              <span>
                狼队友：
                {teammates.length > 0 ? teammates.map((s) => `${s}号`).join("、") : "无"}{" "}
              </span>
            )}
            {proposals !== undefined && Object.keys(proposals).length > 0 && (
              <span>
                本轮提案：
                {Object.entries(proposals)
                  .map(([from, to]) => `${from}号→${to}号`)
                  .join("，")}{" "}
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
            <SeatButtons
              hud={false}
              seats={aliveTargets(obs, includeSelf)}
              selected={target}
              onPick={setTarget}
            />
          )}
          <div className={styles.row}>
            <button
              type="button"
              className="btn btn-primary"
              disabled={
                pending ||
                night === null ||
                (needsTarget(night) && target === null) ||
                (night === "save" && killed === null)
              }
              onClick={() => night !== null && submit(nightActionCall(night, chosenTarget))}
            >
              确认行动
            </button>
          </div>
        </>
      );
    }
  } else if (active === "sheriff_action") {
    // 零裁决（issue #126）：只渲染服务端 sheriff_options 里的行动；文案按阶段区分
    const so = obs.sheriff_options ?? [];
    const candidacy = obs.phase === "SHERIFF_ELECTION" && obs.election_stage === "candidacy";
    const buttons: JSX.Element[] = [];
    if (so.includes("run_for_sheriff")) {
      buttons.push(
        <button
          key="run"
          type="button"
          className="btn btn-primary"
          disabled={pending}
          onClick={() => submit(sheriffCall("run_for_sheriff"))}
        >
          {candidacy ? "上警" : "坚持竞选"}
        </button>,
      );
    }
    if (so.includes("withdraw")) {
      buttons.push(
        <button
          key="withdraw"
          type="button"
          className="btn btn-secondary"
          disabled={pending}
          onClick={() => submit(sheriffCall("withdraw"))}
        >
          {candidacy ? "不上" : "退水"}
        </button>,
      );
    }
    if (so.includes("vote_sheriff")) {
      if (hud) heading = { title: HUD_HEADING.vote_sheriff as string, sub: targetSub };
      buttons.push(
        <SeatButtons
          key="vote-seats"
          hud={hud}
          seats={obs.sheriff_candidates}
          selected={target}
          onPick={setTarget}
        />,
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
    if (so.includes("pass_badge")) {
      if (hud) heading = { title: HUD_HEADING.pass_badge as string, sub: targetSub };
      buttons.push(
        <SeatButtons
          key="pass-seats"
          hud={hud}
          seats={aliveTargets(obs, false)}
          selected={target}
          onPick={setTarget}
        />,
        <button
          key="pass"
          type="button"
          className="btn btn-primary"
          disabled={pending || target === null}
          onClick={() => target !== null && submit(sheriffCall("pass_badge", { target }))}
        >
          移交警徽
        </button>,
      );
    }
    if (so.includes("tear_badge")) {
      buttons.push(
        <button
          key="tear"
          type="button"
          className={hud ? "btn btn-danger" : `btn btn-secondary ${styles.danger}`}
          disabled={pending}
          onClick={() => submit(sheriffCall("tear_badge"))}
        >
          撕警徽
        </button>,
      );
    }
    if (so.includes("set_speech_direction")) {
      buttons.push(
        <button
          key="left"
          type="button"
          className="btn btn-secondary"
          disabled={pending}
          onClick={() => submit(sheriffCall("set_speech_direction", { direction: "LEFT" }))}
        >
          从左发言
        </button>,
        <button
          key="right"
          type="button"
          className="btn btn-secondary"
          disabled={pending}
          onClick={() => submit(sheriffCall("set_speech_direction", { direction: "RIGHT" }))}
        >
          从右发言
        </button>,
      );
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
          <button
            type="button"
            className={hud ? "btn btn-danger" : `btn btn-secondary ${styles.danger}`}
            disabled={pending}
            onClick={() => submit(selfDestructCall())}
          >
            确认自爆
          </button>
        ) : (
          <button
            type="button"
            className={hud ? "btn btn-ghost" : `btn btn-secondary ${styles.danger}`}
            disabled={pending}
            onClick={() => setConfirmDestruct(true)}
          >
            自爆
          </button>
        )}
      </div>
    );
  }

  const footer = (
    <div className={styles.footer}>
      <span>
        {pending
          ? "提交中…"
          : left === null
            ? ""
            : left === 0
              ? "可能已超时，以服务端裁决为准"
              : hud
                ? ""
                : `剩余 ${left} 秒`}
      </span>
      <span>
        {lastResult !== null && !lastResult.ok && lastResult.rejected_reason && (
          <span className={styles.error}>{lastResult.rejected_reason}</span>
        )}
        {lastError && <span className={styles.warn}> {lastError}</span>}
      </span>
    </div>
  );

  const tabs =
    tools.length > 1 ? (
      <div className={styles.tabs} role="tablist">
        {tools.map((t) => (
          <button
            key={t}
            type="button"
            role="tab"
            aria-selected={active === t}
            className={`${styles.tab} ${active === t ? styles.tabOn : ""}`}
            onClick={() => selectTab(t)}
          >
            {TOOL_ZH[t] ?? t}
          </button>
        ))}
      </div>
    ) : null;

  if (!hud) {
    return (
      <div className={styles.root} role="region" aria-label="行动区">
        {tabs}
        {body}
        {footer}
      </div>
    );
  }

  const limit = limitRef.current;
  const pct = left !== null && limit > 0 ? Math.round((left / limit) * 100) : null;
  return (
    <div className={styles.hud} role="region" aria-label="行动区">
      <div className={styles.hudMain}>
        {tabs}
        {heading !== null && (
          <div className={styles.hudHeadRow}>
            <div className={styles.hudHeading}>{heading.title}</div>
            {heading.sub && <div className={styles.hudSub}>{heading.sub}</div>}
          </div>
        )}
        {body}
        {footer}
      </div>
      <div className={styles.hudSide}>
        {left !== null && (
          <div className={styles.timer}>
            <div className={styles.timerTrack}>
              <span style={{ width: `${pct ?? 100}%` }} />
            </div>
            <span className={styles.timerText}>{left}s</span>
          </div>
        )}
        {primary !== null && <div className={styles.primary}>{primary}</div>}
      </div>
    </div>
  );
}
