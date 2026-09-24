// 对局页（设计稿 1c/1d/1g/1h/1i/1j）：直播 + 回放同一页面，GM 与观众只差数据。
//
// 引导流程（规格 §6 + 后端实况）：
//   1. GET /meta —— 后端只在终局后开放（rest.py::meta_endpoint 与 /replay 同门槛）。
//      200 ⇒ 对局已结束 ⇒ 直接 GET /replay 一次性装入，mode="replay"、cursor=0。
//      404 ⇒ 对局不存在（4404）；401 ⇒ token 无效；403 ⇒ 对局进行中或未开局，转第 2 步。
//   2. GET /state —— 直播期唯一能拿到名单/配置的端点。
//      200 ⇒ 由快照补出 GameMeta（GM 拿完整 state，观众拿 SpectatorView）并订阅 WS 直播。
//      409 ⇒ 尚未开局：显示「等待开局」，每 2 秒重试整个引导流程。

import { useEffect, useMemo, useRef, useState } from "react";
import { ApiError, getMeta, getReplay, getState } from "../api/rest";
import { useLiveEvents } from "../api/ws";
import { WINNER_ZH, isNight } from "../engine/phases";
import {
  currentSpeaker,
  nightLinks,
  nightSummary,
  roundSegments,
  sheriffVoteTally,
  speechItems,
  voteTally,
} from "../engine/select";
import type { Event, GameMeta, Phase } from "../engine/types";
import { useGameStore } from "../store/game";
import type { Viewer } from "../store/game";
import ElectionPanel from "../components/ElectionPanel/ElectionPanel";
import ErrorState from "../components/ErrorState/ErrorState";
import type { ErrorKind } from "../components/ErrorState/ErrorState";
import NightOverlay from "../components/NightOverlay/NightOverlay";
import NightSummary from "../components/NightSummary/NightSummary";
import PhaseBar from "../components/PhaseBar/PhaseBar";
import PlayerStatusPanel from "../components/PlayerStatusPanel/PlayerStatusPanel";
import ReplayBar from "../components/ReplayBar/ReplayBar";
import SeatCircle from "../components/SeatCircle/SeatCircle";
import SpeechFeed from "../components/SpeechFeed/SpeechFeed";
import VotePanel from "../components/VotePanel/VotePanel";
import styles from "./GamePage.module.css";

export interface GamePageProps {
  gameId?: string;
  token?: string;
  viewer?: Viewer;
}

/** 未开局轮询间隔（毫秒，规格 §7.3：4409 每 2s 重试）。 */
const POLL_MS = 2000;

/** 会出现「当前发言者」的阶段。 */
const SPEAKING_PHASES: ReadonlySet<Phase> = new Set([
  "DAY_SPEECH",
  "LAST_WORDS",
  "SHERIFF_ELECTION",
  "SHERIFF_PK",
]);

interface SeatRow {
  seat: number;
  display_name: string;
}

/** 由 /state 快照补出 GameMeta（见文件头注释）。 */
function metaFromState(gameId: string, raw: Record<string, unknown>): GameMeta {
  const players = raw.players as SeatRow[] | undefined;
  const seats = raw.seats as SeatRow[] | undefined;
  const roster = (players ?? seats ?? []).map((p) => ({
    seat: p.seat,
    display_name: p.display_name,
  }));
  const config = (raw.config as GameMeta["config"] | undefined) ?? {
    // 观众视角拿不到 config（服务端没发）：用名单人数兜底，只用于渲染，不参与裁决。
    num_players: roster.length,
    sheriff: { enabled: true, vote_weight: 1.5 },
    roles: [],
    win_condition: "",
  };
  return { game_id: gameId, config, roster, agents: {} };
}

export default function GamePage({ gameId, token, viewer }: GamePageProps): JSX.Element {
  const [ready, setReady] = useState(false);
  const [errorKind, setErrorKind] = useState<ErrorKind | null>(null);
  const [attempt, setAttempt] = useState(0);
  const [detail, setDetail] = useState<string | null>(null);
  const pollRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const events = useGameStore((s) => s.events);
  const head = useGameStore((s) => s.head);
  const cursor = useGameStore((s) => s.cursor);
  const mode = useGameStore((s) => s.mode);
  const connection = useGameStore((s) => s.connection);
  const storeError = useGameStore((s) => s.error);
  const playing = useGameStore((s) => s.playing);
  const speed = useGameStore((s) => s.speed);

  // ---- 引导：/meta →（403）/state ----
  useEffect(() => {
    if (!gameId || !token || !viewer) {
      setErrorKind("auth");
      return;
    }
    let cancelled = false;
    let tries = 0;

    const fail = (err: unknown): boolean => {
      // 返回 true 表示已处理（终态），false 表示可继续退回 /state
      if (!(err instanceof ApiError)) {
        setErrorKind("4404");
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

    const run = async (): Promise<void> => {
      tries += 1;
      // 1) 终局对局：/meta 开放 → 一次性装入回放
      try {
        const meta = await getMeta(gameId, token);
        const replay = await getReplay(gameId, token);
        if (cancelled) return;
        const store = useGameStore.getState();
        store.load(meta, { gameId, token, viewer, mode: "replay" });
        store.appendEvents(replay);
        setErrorKind(null);
        setReady(true);
        return;
      } catch (err) {
        if (cancelled) return;
        if (fail(err)) return;
        // 403：对局进行中或尚未开局 —— 继续走 /state
      }

      // 2) 直播 / 未开局
      try {
        const snapshot = await getState(gameId, token);
        if (cancelled) return;
        const meta = metaFromState(gameId, snapshot);
        useGameStore.getState().load(meta, { gameId, token, viewer, mode: "live" });
        setErrorKind(null);
        setDetail(null);
        setReady(true);
      } catch (err) {
        if (cancelled) return;
        if (fail(err)) return;
        const status = err instanceof ApiError ? err.status : 0;
        if (status === 409) {
          setErrorKind("4409");
          setAttempt(tries);
          setDetail(null);
          pollRef.current = setTimeout(() => {
            void run();
          }, POLL_MS);
          return;
        }
        setErrorKind("auth");
        setDetail(err instanceof ApiError ? err.detail : String(err));
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
    };
  }, [gameId, token, viewer]);

  // ---- 直播订阅（回放模式不连） ----
  // 同时要求 head 非空：引导重跑时 store 会被 reset（head=null、mode 回到 "live"），
  // 而 ready 可能还停留在上一次的 true（开发期 Fast Refresh 会保留组件 state），
  // 这一条避免在「已重置但尚未装入」的空窗里连出一个立刻被关掉的 WS。
  useLiveEvents({
    gameId: gameId ?? null,
    token: token ?? null,
    enabled: ready && mode === "live" && head !== null,
  });

  // ---- 派生视图 ----
  // viewState() 内部按 (cursor, events.length) 记忆化，同一状态下多次调用返回同一对象，
  // 可安全用作 zustand 选择器（useSyncExternalStore 要求快照稳定）。
  const view = useGameStore((s) => s.viewState());
  const visibleEvents = useMemo<Event[]>(
    () => (cursor === null ? events : events.filter((e) => e.seq <= cursor)),
    [events, cursor],
  );
  const items = useMemo(() => speechItems(events), [events]);
  const segments = useMemo(() => roundSegments(events), [events]);
  const totalSeq = events.length > 0 ? (events[events.length - 1] as Event).seq : 0;
  const atSeq = cursor ?? totalSeq;

  const speaking = view !== null && SPEAKING_PHASES.has(view.phase) ? currentSpeaker(view) : null;

  // 票数小标只在投票类阶段显示——否则会把上一轮遗留的票箱画在座位上。
  const votes = useMemo<Record<number, number>>(() => {
    if (view === null) return {};
    const election = view.phase === "SHERIFF_ELECTION" || view.phase === "SHERIFF_PK";
    const voting = view.phase === "VOTE" || view.phase === "VOTE_PK" || view.phase === "EXILE";
    if (!election && !voting) return {};
    const { tally } = election
      ? sheriffVoteTally(view, visibleEvents)
      : voteTally(view, visibleEvents);
    return Object.fromEntries(tally);
  }, [view, visibleEvents]);

  const lines = useMemo(
    () =>
      view !== null && viewer === "GM" && isNight(view.phase)
        ? nightLinks(visibleEvents, view.round)
        : [],
    [view, visibleEvents, viewer],
  );

  const nightRows = useMemo(
    () => (view !== null ? nightSummary(visibleEvents, view.round) : []),
    [view, visibleEvents],
  );

  if (errorKind !== null) {
    return <ErrorState kind={errorKind} attempt={attempt} detail={detail} />;
  }
  if (!ready || view === null || viewer === undefined) {
    return (
      <div className={styles.loading} role="status">
        正在载入对局…
      </div>
    );
  }

  // 终局横幅看的是「这局是否已经结束」（head / 回放），而不是回放游标当前停在哪一刻——
  // 设计稿 1g 里游标停在 seq 143 时横幅照样显示最终结果 + 「回放显示到 seq N」。
  const finished = head !== null && (head.phase === "GAME_OVER" || head.winner !== null);
  const over = finished || mode === "replay";
  const winner = head?.winner ?? view.winner;
  const reconnectHint =
    mode === "live" && (connection === "closed" || connection === "connecting") && !over
      ? "重连中 · 正在补发事件"
      : null;

  const rightPanel = isNight(view.phase) ? (
    <NightSummary rows={nightRows} round={view.round} viewer={viewer} />
  ) : view.phase === "SHERIFF_ELECTION" || view.phase === "SHERIFF_PK" ? (
    <ElectionPanel state={view} events={visibleEvents} viewer={viewer} />
  ) : view.phase === "VOTE" || view.phase === "VOTE_PK" || view.phase === "EXILE" ? (
    <VotePanel state={view} events={visibleEvents} viewer={viewer} />
  ) : (
    <PlayerStatusPanel state={view} viewer={viewer} speakingSeat={speaking} />
  );

  const store = useGameStore.getState();

  return (
    <div className={`${styles.root} ${over ? styles.rootOver : ""}`}>
      <PhaseBar
        state={view}
        mode={mode}
        viewer={viewer}
        connection={connection}
        lastSeq={atSeq}
        totalSeq={totalSeq}
        reconnectHint={reconnectHint}
      />

      {over && (
        <div className={styles.banner}>
          <span className={styles.bannerRule}>═══</span>
          <span>
            游戏结束：
            <span className={styles.bannerWinner}>
              {winner !== null ? `${WINNER_ZH[winner] ?? winner}胜` : "平局"}
            </span>
            <span className={styles.bannerCode}>（{winner ?? "平局"}）</span>
          </span>
          <span className={styles.bannerRule}>═══</span>
          <span className={styles.bannerSub}>回放显示到 seq {atSeq}</span>
        </div>
      )}

      <div className={styles.body}>
        <div className={styles.left}>
          <SeatCircle
            state={view}
            viewer={viewer}
            speaking={speaking}
            votes={votes}
            nightLines={lines}
          />
        </div>

        <div className={styles.center}>
          <SpeechFeed
            items={items}
            cursor={cursor}
            players={view.players}
            viewer={viewer}
            speakingSeat={speaking}
          />
          <NightOverlay phase={view.phase} viewer={viewer} />
        </div>

        <div className={styles.right}>{rightPanel}</div>
      </div>

      {storeError !== null && <div className={styles.error}>{storeError}</div>}

      <ReplayBar
        cursor={cursor}
        total={totalSeq}
        playing={playing}
        speed={speed}
        segments={segments}
        live={mode === "live"}
        onCursor={(seq) => store.setCursor(seq)}
        onPlay={() => store.play()}
        onPause={() => store.pause()}
        onSpeed={(s) => store.setSpeed(s)}
        onStep={(d) => (d === 1 ? store.stepForward() : store.stepBack())}
        onLive={() => store.setCursor(null)}
      />
    </div>
  );
}
