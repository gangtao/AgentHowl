// 对局页（规格 §4，设计稿 3a 全景圆桌）：直播 + 回放同一页面，GM / 观众 / 座位三种视角只差数据；
// 视角只决定底部是 HUD 还是回放绳索条，以及顶栏标签——桌子 / 右栏 / 结算页的 props 里没有 viewer。
//
// 引导流程（规格 §6 + 后端实况）：
//   凭据（issue #114）：token（Bearer）→ share（?share=）→ 都没有则靠登录 cookie（GM）。
//   1. GET /meta —— 后端只在终局后开放（rest.py::meta_endpoint 与 /replay 同门槛）。
//      200 ⇒ 对局已结束 ⇒ 直接 GET /replay 一次性装入，mode="replay"、cursor=0。
//      404 ⇒ 对局不存在（4404）；401 ⇒ 凭据无效/未登录（auth 错误态）；403 ⇒ 对局进行中或未开局，转第 2 步。
//   2. GET /state —— 直播期唯一能拿到名单/配置的端点。
//      200 ⇒ 由快照补出 GameMeta（GM 拿完整 state，观众拿 SpectatorView）并订阅 WS 直播。
//      409 ⇒ 尚未开局：显示「等待开局」，每 2 秒只重试 /state（issue #81：不再每轮都打 /meta 吃 403）。
//   3. 直播收尾（issue #81）：head 到 GAME_OVER 后 /meta 开放，GM / 观众视角自动改走第 1 步
//      装入完整回放（含角色翻牌），游标停在终局；真人玩家保留「查看全局回放」按钮。

import { useEffect, useMemo, useRef, useState } from "react";
import {
  ApiError,
  getAudioManifest,
  getGameAvatars,
  getMeta,
  getReplay,
  getState,
  viewerFrom,
} from "../api/rest";
import type { AudioPartInfo, GameAuth } from "../api/rest";
import type { PlayerObservation, YourTurn } from "../api/player";
import type { ViewerHint } from "../api/tokens";
import { useLiveEvents } from "../api/ws";
import { createDwell } from "../lib/dwell";
import { readingDwellMs } from "../lib/readingDwell";
import { replayControls } from "../lib/replayControls";
import { usePrefs } from "../store/prefs";
import { useVoice } from "../store/voice";
import { isNight } from "../engine/phases";
import {
  currentSpeaker,
  nightSummary,
  roundSegments,
  sheriffVoteTally,
  speechItems,
  voteTally,
} from "../engine/select";
import type { Event, Phase, RoleType } from "../engine/types";
import { agentLine } from "../lib/agentLine";
import { currentClaims, logEntries } from "../lib/gameLog";
import { identityLines } from "../lib/identityLines";
import { railCards } from "../lib/railCards";
import { seatModel } from "../lib/seatModel";
import { stageContent } from "../lib/stageContent";
import { currentSpeechItem } from "../lib/tableText";
import { graveyard } from "../lib/village";
import { useAuth } from "../store/auth";
import { useGameStore } from "../store/game";
import { useTurn } from "../store/turn";
import type { Viewer } from "../store/game";
import ActionBar from "../components/ActionBar/ActionBar";
import ErrorState from "../components/ErrorState/ErrorState";
import type { ErrorKind } from "../components/ErrorState/ErrorState";
import EventDrawer from "../components/EventDrawer/EventDrawer";
import GameLog from "../components/GameLog/GameLog";
import GameOverScreen from "../components/GameOverScreen/GameOverScreen";
import CardBoard from "../components/GameTable/CardBoard";
import GameTable from "../components/GameTable/GameTable";
import IdentityCard from "../components/IdentityCard/IdentityCard";
import InfoRail from "../components/InfoRail/InfoRail";
import PhaseBar from "../components/PhaseBar/PhaseBar";
import TableStyleToggle from "../components/PhaseBar/TableStyleToggle";
import PhasePlaque from "../components/PhasePlaque/PhasePlaque";
import ReplayBar from "../components/ReplayBar/ReplayBar";
import SpeakerStand, { type StandKind } from "../components/SpeakerStand/SpeakerStand";
import VoiceToggle from "../components/VoiceToggle/VoiceToggle";
import styles from "./GamePage.module.css";
import { metaFromState } from "./metaFromState";

export interface GamePageProps {
  gameId?: string;
  token?: string;
  viewer?: ViewerHint;
  /** 分享链接 token（`?share=`，issue #114）：匿名观众（SPECTATOR）。 */
  share?: string;
}

/** 未开局轮询间隔（毫秒，规格 §7.3：4409 每 2s 重试）。 */
const POLL_MS = 2000;

/** 回放阅读停留的可取消 sleep（模块级：与回放门控同生命周期，不需要响应式）。 */
const dwell = createDwell();

/** 回放控制条的「打断」：停配音 + 取消阅读等待（lib/replayControls 的 VoiceClearControl）。 */
const stopPlayback = {
  clear(): void {
    useVoice.getState().clear();
    dwell.cancel();
  },
};

/** 会出现「当前发言者」的阶段。 */
const SPEAKING_PHASES: ReadonlySet<Phase> = new Set([
  "DAY_SPEECH",
  "LAST_WORDS",
  "SHERIFF_ELECTION",
  "SHERIFF_PK",
]);

export default function GamePage({ gameId, token, share, viewer }: GamePageProps): JSX.Element {
  const auth = useMemo<GameAuth>(() => {
    const a: GameAuth = {};
    if (token) a.token = token;
    if (share) a.share = share;
    return a;
  }, [token, share]);
  const [ready, setReady] = useState(false);
  const [errorKind, setErrorKind] = useState<ErrorKind | null>(null);
  const [attempt, setAttempt] = useState(0);
  const [detail, setDetail] = useState<string | null>(null);
  const [avatars, setAvatars] = useState<Record<number, string>>({});
  /** 发言音频清单 {seq: [{part, duration}]}（issue #103）：回放门控据此判断某个 seq 要不要
   * 等配音播完才放行；拿不到（没开语音/探测失败）就是空对象，门控天然退化成不卡任何 seq。 */
  const [manifest, setManifest] = useState<Record<string, AudioPartInfo[]>>({});
  // 门控 effect（下方）读这个 ref 而不是直接读 manifest state：清单在拉取完成前短暂为
  // 空对象、之后被 setManifest 换成真正内容，如果把 manifest 放进该 effect 的依赖数组，
  // 这次刷新会把 gate 拆了重装一遍——若恰好卡在某个 seq 的配音中途，相当于半路换了一个新
  // 的 gate 闭包，没有真正打断旧 playSeq（fix round 2 的 Minor 项）。ref 让 effect 的依赖
  // 只剩 [mode, gameId, token]，manifest 更新不触发重装，gate 闭包始终读到最新清单。
  const manifestRef = useRef<Record<string, AudioPartInfo[]>>(manifest);
  // 视角由服务端决定（issue #115）：/state、/meta 的 viewer 字段；URL 里的 ?gm= / ?share= 只是提示。
  const [resolvedViewer, setResolvedViewer] = useState<Viewer | null>(null);
  // 玩家视角的身份：来自 /state 的 PlayerObservation.my_role（Task 10 的 ActionBar 也会更新它）。
  const [myRole, setMyRole] = useState<RoleType | null>(null);
  // 最近一次服务端观察（/state 快照或 your_turn）：队友 / 药瓶 / 存亡等私有信息从这里读，而不是从提交后
  // 就被清空的 turnPrompt——否则狼人一提交刀口队友就「消失」（终审 Important 1 / 3）。
  const [lastObs, setLastObs] = useState<PlayerObservation | null>(null);
  const pollRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const switchedRef = useRef(false);

  const events = useGameStore((s) => s.events);
  const meta = useGameStore((s) => s.meta);
  const head = useGameStore((s) => s.head);
  const cursor = useGameStore((s) => s.cursor);
  const mode = useGameStore((s) => s.mode);
  const connection = useGameStore((s) => s.connection);
  const storeError = useGameStore((s) => s.error);
  const playing = useGameStore((s) => s.playing);
  const speed = useGameStore((s) => s.speed);

  // ---- 引导：/meta →（403）/state ----
  useEffect(() => {
    if (!gameId) {
      setErrorKind("auth");
      return;
    }

    let cancelled = false;
    let tries = 0;

    const fail = (err: unknown): boolean => {
      // 返回 true 表示已处理（终态），false 表示可继续退回 /state
      if (!(err instanceof ApiError)) {
        setErrorKind("error");
        setDetail(String(err));
        return true;
      }
      if (err.status === 404) {
        setErrorKind("4404");
        setDetail(err.detail);
        return true;
      }
      if (err.status === 401) {
        setErrorKind("auth");
        setDetail(err.detail);
        return true;
      }
      return false;
    };

    switchedRef.current = false;

    const run = async (stateOnly = false): Promise<void> => {
      tries += 1;
      // 1) 终局对局：/meta 开放 → 一次性装入回放。
      //    未开局轮询（4409）期间跳过：对局不可能在未开局时就结束，省掉每轮一次 403（issue #81）。
      if (!stateOnly) {
        try {
          const meta = await getMeta(gameId, auth);
          const replayEvents = await getReplay(gameId, auth);
          if (cancelled) return;
          const store = useGameStore.getState();
          const v: Viewer =
            viewerFrom(meta as unknown as Record<string, unknown>) ?? viewer ?? "SPECTATOR";
          setResolvedViewer(v);
          store.load(meta, { gameId, token: token ?? "", viewer: v, mode: "replay" });
          store.appendEvents(replayEvents);
          setErrorKind(null);
          setReady(true);
          getGameAvatars(gameId, auth)
            .then((m) => {
              if (!cancelled)
                setAvatars(Object.fromEntries(Object.entries(m).map(([k, v]) => [Number(k), v])));
            })
            .catch(() => {
              /* 头像拿不到只是没图：不阻断对局页 */
            });
          getAudioManifest(gameId, auth)
            .then((m) => {
              if (cancelled) return;
              setManifest(m);
              if (Object.keys(m).length > 0) useVoice.getState().markAvailable();
            })
            .catch(() => {
              /* 清单拿不到就是没有配音：不阻断对局页 */
            });
          return;
        } catch (err) {
          if (cancelled) return;
          if (fail(err)) return;
          // 403：对局进行中或尚未开局 —— 继续走 /state
        }
      }

      // 2) 直播 / 未开局
      try {
        const snapshot = await getState(gameId, auth);
        if (cancelled) return;
        const meta = metaFromState(gameId, snapshot);
        const v: Viewer = viewerFrom(snapshot) ?? viewer ?? "SPECTATOR";
        setResolvedViewer(v);
        if (typeof v === "number" && typeof snapshot.my_role === "string") {
          setMyRole(snapshot.my_role as RoleType);
          setLastObs(snapshot as unknown as PlayerObservation);
        }
        useGameStore.getState().load(meta, { gameId, token: token ?? "", viewer: v, mode: "live" });
        setErrorKind(null);
        setDetail(null);
        setReady(true);
        getGameAvatars(gameId, auth)
          .then((m) => {
            if (!cancelled)
              setAvatars(Object.fromEntries(Object.entries(m).map(([k, v]) => [Number(k), v])));
          })
          .catch(() => {
            /* 头像拿不到只是没图：不阻断对局页 */
          });
        getAudioManifest(gameId, auth)
          .then((m) => {
            if (cancelled) return;
            setManifest(m);
            if (Object.keys(m).length > 0) useVoice.getState().markAvailable();
          })
          .catch(() => {
            /* 清单拿不到就是没有配音：不阻断对局页 */
          });
      } catch (err) {
        if (cancelled) return;
        if (fail(err)) return;
        const status = err instanceof ApiError ? err.status : 0;
        if (status === 403) {
          // 建局者已入座：GM 链接被服务端封锁（issue #115）
          setErrorKind("locked");
          setDetail(err instanceof ApiError ? err.detail : null);
          return;
        }
        if (status === 409) {
          setErrorKind("4409");
          setAttempt(tries);
          setDetail(null);
          pollRef.current = setTimeout(() => {
            void run(true);
          }, POLL_MS);
          return;
        }
        // 既不是 401/404/409（如后端 5xx、网络失败）：通用错误态原文展示，不要误报成 token 问题。
        setErrorKind("error");
        setDetail(err instanceof ApiError ? `${err.status} · ${err.detail}` : String(err));
      }
    };

    void run();
    return () => {
      cancelled = true;
      if (pollRef.current !== null) {
        clearTimeout(pollRef.current);
        pollRef.current = null;
      }
      useGameStore.getState().reset();
      setReady(false);
      setResolvedViewer(null);
      setMyRole(null);
      setLastObs(null);
      setManifest({});
      // 同上：直播卸载也要停播 + 清 available（fix round 3）。
      useVoice.getState().clear(true);
    };
  }, [gameId, token, auth, viewer]);

  useEffect(() => {
    manifestRef.current = manifest;
  }, [manifest]);

  // ---- 直播收尾（issue #81）：直播 head 到 GAME_OVER 后 /meta 开放，GM / 观众自动切到回放模式，
  // 装入终局后才开放的完整流（含角色翻牌），游标停在最后一条而不是回到开头。
  // 真人玩家不自动切：玩家栏有「查看全局回放」按钮，且切换会丢掉身份栏的上下文。
  const liveFinished =
    ready &&
    mode === "live" &&
    head !== null &&
    (head.phase === "GAME_OVER" || head.winner !== null) &&
    typeof resolvedViewer !== "number";
  useEffect(() => {
    if (!gameId || !liveFinished || switchedRef.current) return;
    switchedRef.current = true;
    let cancelled = false;
    const handoff = async (): Promise<void> => {
      try {
        const meta = await getMeta(gameId, auth);
        const replayEvents = await getReplay(gameId, auth);
        if (cancelled) return;
        const store = useGameStore.getState();
        const v: Viewer =
          viewerFrom(meta as unknown as Record<string, unknown>) ?? resolvedViewer ?? "SPECTATOR";
        setResolvedViewer(v);
        store.load(meta, { gameId, token: token ?? "", viewer: v, mode: "replay" });
        store.appendEvents(replayEvents);
        const last =
          replayEvents.length > 0 ? (replayEvents[replayEvents.length - 1] as Event).seq : 0;
        store.setCursor(last);
      } catch {
        /* /meta 仍未开放或网络失败：保持直播画面（已有终局横幅），不打扰用户 */
      }
    };
    void handoff();
    return () => {
      cancelled = true;
    };
  }, [gameId, auth, token, liveFinished, resolvedViewer]);

  // ---- 回放门控（issue #103）：mode==="replay" 时，游标推进到某个 seq 若清单里有这句的配音，
  // 就顺序播完它的全部分段再放行时钟继续（store/game.ts 的 makeTick 消费 replayGate）。
  // 直播模式不装（声音已经跟着 WS 帧实时播，不需要卡时钟）。依赖数组特意不含 manifest——
  // 见上面 manifestRef 声明处的注释。
  // 规格 §7（issue #189）：有配音且语音开着 → 播配音；否则发言 / 遗言按字数等阅读时长（readingDwellMs），
  // 其它事件不卡。阅读等待可被 stopPlayback() 取消（暂停 / 拖动 / 单步 / 回到直播）。
  useEffect(() => {
    if (mode !== "replay" || !gameId) return;
    useGameStore.getState().setReplayGate((seq) => {
      const parts = manifestRef.current[String(seq)];
      if (parts && useVoice.getState().enabled) {
        return useVoice.getState().playSeq(gameId, seq, parts, auth);
      }
      const { events: all, speed: spd } = useGameStore.getState();
      const ms = readingDwellMs(
        all.find((e) => e.seq === seq),
        spd,
      );
      return ms > 0 ? dwell.sleep(ms) : null;
    });
    return () => {
      useGameStore.getState().setReplayGate(null);
      useVoice.getState().clear();
      dwell.cancel();
    };
  }, [mode, gameId, auth]);

  // ---- 直播订阅（回放模式不连） ----
  // 同时要求 head 非空：引导重跑时 store 会被 reset（head=null、mode 回到 "live"），
  // 而 ready 可能还停留在上一次的 true（开发期 Fast Refresh 会保留组件 state），
  // 这一条避免在「已重置但尚未装入」的空窗里连出一个立刻被关掉的 WS。
  const live = useLiveEvents({
    gameId: gameId ?? null,
    auth,
    enabled: ready && mode === "live" && head !== null,
  });

  const turnPrompt = useTurn((s) => s.prompt);
  const turnPending = useTurn((s) => s.pending);
  const turnAccepted = useTurn((s) => s.accepted);
  const turnResult = useTurn((s) => s.lastResult);
  const turnError = useTurn((s) => s.lastError);
  const isPlayer = typeof resolvedViewer === "number";
  // 身份以最新 your_turn 为准（/state 只在引导时读一次）
  useEffect(() => {
    if (turnPrompt !== null) {
      setMyRole(turnPrompt.observation.my_role);
      setLastObs(turnPrompt.observation);
    }
  }, [turnPrompt]);
  /** 给 stageContent 用的观察（药瓶）：有 prompt 用 prompt，否则用最近一次观察。 */
  const obsPrompt = useMemo<YourTurn | null>(
    () =>
      turnPrompt ??
      (lastObs === null ? null : { observation: lastObs, available_tools: [], deadline_ts: 0 }),
    [turnPrompt, lastObs],
  );

  // ---- 派生视图 ----
  // viewState() 内部按 (cursor, events.length) 记忆化，同一状态下多次调用返回同一对象，
  // 可安全用作 zustand 选择器（useSyncExternalStore 要求快照稳定）。
  const view = useGameStore((s) => s.viewState());
  const visibleEvents = useMemo<Event[]>(
    () => (cursor === null ? events : events.filter((e) => e.seq <= cursor)),
    [events, cursor],
  );
  // 发言台只看游标之前的发言：回放时「最后一句」必须是游标处的，不是全局最后一条（终审 Important 5）。
  const standItems = useMemo(() => speechItems(visibleEvents), [visibleEvents]);
  // 对局记录（规格 2026-10-28-speech-stage §6）：已按游标截断的事件流 → 倒序条目；自称取最新一天的发言。
  const entries = useMemo(() => logEntries(visibleEvents), [visibleEvents]);
  const claims = useMemo(() => currentClaims(entries), [entries]);
  const segments = useMemo(() => roundSegments(events), [events]);
  const totalSeq = events.length > 0 ? (events[events.length - 1] as Event).seq : 0;
  const authStatus = useAuth((s) => s.status);

  const turnSpeaker =
    view !== null && SPEAKING_PHASES.has(view.phase) ? currentSpeaker(view) : null;
  // 正在出声的发言优先于"轮到谁"：引擎提交发言后立刻把发言权交给下一位，而音频还在播上一位，
  // 高亮若只看 state 会跑到下一位身上（issue #103 用户反馈）。零过滤：seq 来自服务端帧。
  const voicingSeq = useVoice((s) => s.voicingSeq);
  const voicePlaying = useVoice((s) => s.playing !== null);
  // 座位（发言/遗言事件）/ "GM"（其它任何事件，含带 actor_seat 的 HUNTER_SHOT 等进程事件，
  // issue #110）/ null（找不到事件 → 退回轮到谁）。只看事件类型与 actor_seat，不看 kind。
  const voicingActor = useMemo<number | "GM" | null>(() => {
    if (voicingSeq === null) return null;
    const e = events.find((x) => x.seq === voicingSeq);
    if (e === undefined) return null;
    if (e.type === "PLAYER_SPOKE" || e.type === "LAST_WORDS") return e.actor_seat ?? "GM";
    return "GM";
  }, [events, voicingSeq]);
  let speaking: number | null = null;
  if (typeof voicingActor === "number") speaking = voicingActor;
  else if (voicingActor === null) speaking = turnSpeaker;

  // 票数小标与座位状态行的「已投 N号」只在投票类阶段——否则会把上一轮遗留的票箱画在座位上。
  const ballot = useMemo<{
    votes: Record<number, number>;
    voteTargets: Record<number, number | null>;
  }>(() => {
    if (view === null) return { votes: {}, voteTargets: {} };
    const election = view.phase === "SHERIFF_ELECTION" || view.phase === "SHERIFF_PK";
    const voting = view.phase === "VOTE" || view.phase === "VOTE_PK" || view.phase === "EXILE";
    if (!election && !voting) return { votes: {}, voteTargets: {} };
    const { tally, votes: cast } = election
      ? sheriffVoteTally(view, visibleEvents)
      : voteTally(view, visibleEvents);
    return { votes: Object.fromEntries(tally), voteTargets: cast };
  }, [view, visibleEvents]);

  const nightRows = useMemo(
    () => (view !== null ? nightSummary(visibleEvents, view.round) : []),
    [view, visibleEvents],
  );

  // ---- 目标座位（受控）：桌上点座位与 HUD 胶囊等价 ----
  // 桌面皮肤偏好（规格 §7）：只决定桌子区画圆桌还是牌阵。
  const tableStyle = usePrefs((s) => s.tableStyle);
  const [selectedTarget, setSelectedTarget] = useState<number | null>(null);
  const [selectable, setSelectable] = useState<number[] | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const turnVersion = turnPrompt?.observation.state_version ?? -1;
  useEffect(() => {
    setSelectedTarget(null);
  }, [turnVersion]);

  // 角色覆盖层：reducer 要求 ROLES_ASSIGNED 全量，座位视角的 state 里没有角色；本人与狼队友
  // 来自服务端观察（my_role / private.teammates）——是服务端给的数据，不是前端推断。
  const knownRoles = useMemo<Record<number, RoleType>>(() => {
    const out: Record<number, RoleType> = {};
    if (isPlayer && myRole !== null) out[resolvedViewer as number] = myRole;
    const mates = lastObs?.private.teammates;
    if (Array.isArray(mates)) {
      for (const m of mates) if (typeof m === "number") out[m] = "WEREWOLF";
    }
    return out;
  }, [isPlayer, myRole, resolvedViewer, lastObs]);

  // 预言家已验签：state.seer_log 有什么就标什么（观众 / 非预言家的 state 里没有）。
  const marks = useMemo<Record<number, "好人" | "狼人">>(() => {
    if (view === null) return {};
    const out: Record<number, "好人" | "狼人"> = {};
    for (const entry of Object.values(view.seer_log).flat()) {
      out[entry.seat] = entry.result === "WOLF" ? "狼人" : "好人";
    }
    return out;
  }, [view]);

  // 夜间红签：女巫夜的「被刀」、狼人夜的「目标 · N 票」。
  const tags = useMemo<Record<number, string>>(() => {
    if (view === null) return {};
    const out: Record<number, string> = {};
    if (view.phase === "NIGHT_WITCH" && view.pending_night.wolf_target !== null) {
      out[view.pending_night.wolf_target] = "被刀";
    }
    if (view.phase === "NIGHT_WEREWOLF") {
      const count = new Map<number, number>();
      for (const t of Object.values(view.wolf_proposals)) {
        if (t !== null) count.set(t, (count.get(t) ?? 0) + 1);
      }
      let best: [number, number] | null = null;
      for (const [t, n] of count) if (best === null || n > best[1]) best = [t, n];
      if (best !== null) out[best[0]] = `目标 · ${best[1]} 票`;
    }
    return out;
  }, [view]);

  const seats = useMemo(
    () =>
      view === null
        ? []
        : seatModel({
            state: view,
            me: isPlayer ? (resolvedViewer as number) : null,
            knownRoles,
            speaking,
            votes: ballot.votes,
            voteTargets: ballot.voteTargets,
            marks,
            tags,
            selectable: isPlayer && turnPrompt !== null ? (selectable ?? []) : [],
            selected: selectedTarget,
          }),
    [
      view,
      isPlayer,
      resolvedViewer,
      knownRoles,
      speaking,
      ballot,
      marks,
      tags,
      selectable,
      turnPrompt,
      selectedTarget,
    ],
  );

  const center = useMemo(
    () =>
      view === null
        ? ({ kind: "none" } as const)
        : stageContent({
            state: view,
            events: visibleEvents,
            prompt: obsPrompt,
            selectedTarget,
            mode,
            myRole,
          }),
    [view, visibleEvents, obsPrompt, selectedTarget, mode, myRole],
  );

  const potions = useMemo<{ antidote: boolean; poison: boolean } | null>(() => {
    const priv = lastObs?.private;
    if (
      priv !== undefined &&
      typeof priv.antidote_available === "boolean" &&
      typeof priv.poison_available === "boolean"
    ) {
      return { antidote: priv.antidote_available, poison: priv.poison_available };
    }
    return null;
  }, [lastObs]);

  const hasDeaths = useMemo(
    () => (view === null ? false : graveyard(visibleEvents, view).length > 0),
    [view, visibleEvents],
  );
  const cards = useMemo(
    () =>
      view === null
        ? []
        : railCards({
            state: view,
            events: visibleEvents,
            mode,
            hasPotions: potions !== null,
            hasDeaths,
          }),
    [view, visibleEvents, mode, potions, hasDeaths],
  );

  if (errorKind !== null) {
    return (
      <ErrorState
        kind={errorKind}
        attempt={attempt}
        detail={detail}
        playerHref={gameId ? `#/g/${gameId}` : undefined}
        authed={authStatus === "authed"}
      />
    );
  }
  if (!ready || view === null || resolvedViewer === null) {
    return (
      <div className={styles.loading} role="status">
        正在载入对局…
      </div>
    );
  }

  // 「这局是否已经结束」看 head / 回放模式，而不是回放游标当前停在哪一刻。
  const finished = head !== null && (head.phase === "GAME_OVER" || head.winner !== null);
  const over = finished || mode === "replay";
  const winner = head?.winner ?? view.winner;
  const night = isNight(view.phase);
  const atEnd = cursor === null || cursor === totalSeq;
  // 结算页：直播尾声，或回放游标停在末尾（规格 §4.8）；回放拖到中途不覆盖。
  // 直播时 cursor 为 null → atEnd 为真；拖了游标就看游标处的 state 是否已到终局。
  const showOver = over && atEnd && (view.phase === "GAME_OVER" || view.winner !== null);
  const blood =
    view.phase === "LAST_WORDS" || view.phase === "VOTE_PK" || (showOver && winner === "WOLF");
  const amber = view.phase === "HUNTER_SHOOT";

  const store = useGameStore.getState();
  // 游标拖动/翻页/暂停时打断仍在播的配音（fix round 2，见 lib/replayControls.ts 头注释）与阅读等待。
  const controls = replayControls(store, stopPlayback);

  const goGlobalReplay = (): void => {
    const target = `#/g/${gameId ?? ""}`;
    if (window.location.hash === target) window.location.reload();
    else window.location.hash = target;
  };

  // 发言台（规格 2026-10-28-speech-stage §5）：跟着「正在出声 / 轮到谁」的座位走；旁白在播（voicingActor
  // 为 "GM"）时 speaking 为 null，发言台退回轮到谁，免得每句旁白都把发言台收起来。
  const standKind: StandKind =
    view.phase === "LAST_WORDS"
      ? "last_words"
      : view.phase === "SHERIFF_ELECTION" || view.phase === "SHERIFF_PK"
        ? "campaign"
        : "speech";
  const speechLimit =
    typeof view.config.speech_time_limit === "number" ? view.config.speech_time_limit : null;
  const standSeat = center.kind === "speechProgress" ? (speaking ?? turnSpeaker) : null;
  const standModel = standSeat === null ? null : (seats.find((s) => s.seat === standSeat) ?? null);
  const standOrderIdx = standSeat === null ? -1 : view.speech_order.indexOf(standSeat);
  const stand =
    standSeat === null || standModel === null ? null : (
      <SpeakerStand
        seat={standSeat}
        name={standModel.name}
        role={standModel.role}
        avatar={avatars[standSeat] ?? null}
        kind={standKind}
        item={currentSpeechItem(standItems, standSeat)}
        mine={isPlayer && standSeat === resolvedViewer}
        deadline={
          isPlayer && turnPrompt !== null && standSeat === resolvedViewer
            ? turnPrompt.deadline_ts
            : null
        }
        limit={speechLimit}
        voicing={voicePlaying && typeof voicingActor === "number" && voicingActor === standSeat}
        agent={agentLine(meta?.agents, standSeat)}
        queue={standOrderIdx === -1 ? [] : view.speech_order.slice(standOrderIdx + 1)}
        claims={claims}
      />
    );

  const me = isPlayer ? view.players.find((p) => p.seat === resolvedViewer) : undefined;
  const onStage =
    isPlayer &&
    ((view.phase === "VOTE_PK" && view.vote_candidates.includes(resolvedViewer as number)) ||
      (view.phase === "SHERIFF_PK" && view.sheriff_candidates.includes(resolvedViewer as number)));
  const idleText = night ? "天黑请闭眼" : onStage ? "等待裁决" : "旁听中";

  // 右栏（规格 2026-10-28-speech-stage §3 / R2）：上半发言台（发言阶段）或信息卡，下半对局记录。
  const railContent = (
    <>
      <div className={styles.railTop}>
        {stand ?? (
          <InfoRail
            cards={cards}
            state={view}
            events={visibleEvents}
            nightRows={nightRows}
            potions={potions}
            knownRoles={knownRoles}
          />
        )}
      </div>
      <div className={styles.railLog}>
        <GameLog
          entries={entries}
          state={view}
          cursor={cursor}
          avatars={avatars}
          knownRoles={knownRoles}
        />
      </div>
    </>
  );

  const headerExtra = (
    <>
      <TableStyleToggle />
      {isPlayer && <VoiceToggle />}
      {isPlayer && over && (
        <button type="button" className="btn btn-ghost" onClick={goGlobalReplay}>
          查看全局回放
        </button>
      )}
      {share && authStatus === "anon" && (
        <a className="btn btn-ghost" href="#/login">
          登录
        </a>
      )}
    </>
  );

  const bottom =
    isPlayer && !over ? (
      <div
        className={styles.hud}
        data-blood={blood ? "true" : undefined}
        data-amber={amber ? "true" : undefined}
      >
        <IdentityCard
          seat={resolvedViewer as number}
          name={me?.display_name ?? ""}
          role={myRole}
          alive={(me?.alive ?? true) && lastObs?.my_status !== "DEAD"}
          avatar={avatars[resolvedViewer as number] ?? null}
          lines={identityLines(myRole, lastObs, view)}
        />
        <ActionBar
          layout="hud"
          prompt={turnPrompt}
          pending={turnPending}
          accepted={turnAccepted}
          lastResult={turnResult}
          lastError={turnError}
          selectedTarget={selectedTarget}
          onSelectTarget={setSelectedTarget}
          onSelectableChange={setSelectable}
          idleText={idleText}
          onSubmit={(call) => {
            if (!live.send(call)) useTurn.getState().fail("连接未就绪，请稍后重试");
          }}
        />
      </div>
    ) : (
      <ReplayBar
        cursor={cursor}
        total={totalSeq}
        playing={playing}
        speed={speed}
        segments={segments}
        live={mode === "live"}
        onCursor={controls.onCursor}
        onPlay={controls.onPlay}
        onPause={controls.onPause}
        onSpeed={controls.onSpeed}
        onStep={controls.onStep}
        onLive={controls.onLive}
        leading={!isPlayer ? <VoiceToggle /> : undefined}
        trailing={
          share ? (
            <button
              type="button"
              className="btn btn-ghost"
              onClick={() => {
                void navigator.clipboard?.writeText(window.location.href).catch(() => undefined);
              }}
            >
              复制分享链接
            </button>
          ) : undefined
        }
      />
    );

  return (
    <div
      className={styles.root}
      data-night={night ? "true" : undefined}
      data-blood={blood ? "true" : undefined}
      data-amber={amber ? "true" : undefined}
    >
      <PhaseBar
        state={view}
        mode={mode}
        viewer={resolvedViewer}
        connection={connection}
        totalSeq={totalSeq}
        over={over}
        winner={winner}
        extra={headerExtra}
      />

      <div className={styles.stage}>
        <div className={styles.tableArea} data-table={tableStyle}>
          <div className={styles.plaque}>
            <PhasePlaque state={view} events={visibleEvents} cursor={cursor} total={totalSeq} />
          </div>
          {tableStyle === "cards" ? (
            <CardBoard
              seats={seats}
              night={night}
              center={center}
              avatars={avatars}
              onSelectSeat={setSelectedTarget}
            />
          ) : (
            <GameTable
              seats={seats}
              night={night}
              center={center}
              avatars={avatars}
              onSelectSeat={setSelectedTarget}
            />
          )}
        </div>
        <div className={styles.rail}>{railContent}</div>
        <EventDrawer
          open={drawerOpen}
          onToggle={() => setDrawerOpen((v) => !v)}
          tabLabel="发言台 · 对局记录"
        >
          <div className={styles.drawerRail}>{railContent}</div>
        </EventDrawer>
        {showOver && (
          <GameOverScreen
            state={view}
            events={visibleEvents}
            total={totalSeq}
            knownRoles={knownRoles}
            {...(isPlayer ? { onReplay: goGlobalReplay } : {})}
          />
        )}
      </div>

      {storeError !== null && <div className={styles.error}>{storeError}</div>}

      {bottom}
    </div>
  );
}
