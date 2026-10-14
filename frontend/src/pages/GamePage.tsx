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
import {
  ApiError,
  getAudioManifest,
  getGameAvatars,
  getMeta,
  getReplay,
  getState,
} from "../api/rest";
import type { AudioPartInfo } from "../api/rest";
import { useLiveEvents } from "../api/ws";
import { replayControls } from "../lib/replayControls";
import { useVoice } from "../store/voice";
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
import SpeakerSpotlight from "../components/SpeakerSpotlight/SpeakerSpotlight";
import SpeechFeed from "../components/SpeechFeed/SpeechFeed";
import VoiceToggle from "../components/VoiceToggle/VoiceToggle";
import VotePanel from "../components/VotePanel/VotePanel";
import styles from "./GamePage.module.css";

export interface GamePageProps {
  gameId?: string;
  token?: string;
  viewer?: Viewer;
  /** 无 token 回放（`#/g/{id}?replay=1`，issue #98）：跳过 /state 探测，直接 /meta + /replay。 */
  replay?: boolean;
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

export default function GamePage({ gameId, token, viewer, replay }: GamePageProps): JSX.Element {
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
  const pollRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const events = useGameStore((s) => s.events);
  const head = useGameStore((s) => s.head);
  const cursor = useGameStore((s) => s.cursor);
  const mode = useGameStore((s) => s.mode);
  const connection = useGameStore((s) => s.connection);
  const storeError = useGameStore((s) => s.error);
  const playing = useGameStore((s) => s.playing);
  const speed = useGameStore((s) => s.speed);

  // 回放模式没有 token，视角固定为上帝——服务端对已结束对局本就返回全量事件流
  // （issue #98 设计 §1 访问策略 A），前端不做任何裁剪。
  const effectiveViewer: Viewer | undefined = replay === true ? "GM" : viewer;

  // ---- 引导：replay ⇒ /meta + /replay（无 token）；否则 /meta →（403）/state ----
  useEffect(() => {
    if (!gameId || (!replay && (!token || !viewer))) {
      setErrorKind("auth");
      return;
    }

    if (replay) {
      // 历史回放：无 token，直接装入（后端只对已结束对局开放）
      let cancelled = false;
      void (async () => {
        try {
          const meta = await getMeta(gameId);
          const events = await getReplay(gameId);
          if (cancelled) return;
          const store = useGameStore.getState();
          store.load(meta, { gameId, token: "", viewer: "GM", mode: "replay" });
          store.appendEvents(events);
          setErrorKind(null);
          setDetail(null);
          setReady(true);
          getGameAvatars(gameId)
            .then((m) => {
              if (!cancelled) setAvatars(Object.fromEntries(Object.entries(m).map(([k, v]) => [Number(k), v])));
            })
            .catch(() => {
              /* 头像拿不到只是没图：不阻断对局页 */
            });
          getAudioManifest(gameId)
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
          if (err instanceof ApiError && err.status === 404) {
            setErrorKind("4404");
            setDetail(err.detail);
            return;
          }
          // 403（对局未结束）与 401 合成同一条文案：回放模式本就无 token，用户也无从提供
          // token——开关 AGENTHOWL_PUBLIC_HISTORY=0 时 401 的含义同样是「这局现在不给你看」，
          // 对无 token 的访客与「对局进行中」没有区别，不该暴露成 token 问题（复核 M1 / 裁决 R6）。
          if (err instanceof ApiError && (err.status === 403 || err.status === 401)) {
            setErrorKind("error");
            setDetail("对局进行中，暂不可回放（已结束的对局可从历史页回放）");
            return;
          }
          setErrorKind("error");
          setDetail(err instanceof ApiError ? `${err.status} · ${err.detail}` : String(err));
        }
      })();
      return () => {
        cancelled = true;
        useGameStore.getState().reset();
        setReady(false);
        setManifest({});
        // 直播中途离页不会自己停播（只有回放门控的卸载才调 clear()）；这里顺带把
        // available 也清掉，避免 🔊 开关残留到下一局还没判定出清单的空窗（fix round 3）。
        useVoice.getState().clear(true);
      };
    }

    // 非回放路径：上面的守卫已保证 token/viewer 存在，这里再显式收窄一次让 TS 看见。
    if (!token || !viewer) {
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

    const run = async (): Promise<void> => {
      tries += 1;
      // 1) 终局对局：/meta 开放 → 一次性装入回放
      try {
        const meta = await getMeta(gameId, token);
        const replayEvents = await getReplay(gameId, token);
        if (cancelled) return;
        const store = useGameStore.getState();
        store.load(meta, { gameId, token, viewer, mode: "replay" });
        store.appendEvents(replayEvents);
        setErrorKind(null);
        setReady(true);
        getGameAvatars(gameId, token || undefined)
          .then((m) => {
            if (!cancelled) setAvatars(Object.fromEntries(Object.entries(m).map(([k, v]) => [Number(k), v])));
          })
          .catch(() => {
            /* 头像拿不到只是没图：不阻断对局页 */
          });
        getAudioManifest(gameId, token || undefined)
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

      // 2) 直播 / 未开局
      try {
        const snapshot = await getState(gameId, token);
        if (cancelled) return;
        const meta = metaFromState(gameId, snapshot);
        useGameStore.getState().load(meta, { gameId, token, viewer, mode: "live" });
        setErrorKind(null);
        setDetail(null);
        setReady(true);
        getGameAvatars(gameId, token || undefined)
          .then((m) => {
            if (!cancelled) setAvatars(Object.fromEntries(Object.entries(m).map(([k, v]) => [Number(k), v])));
          })
          .catch(() => {
            /* 头像拿不到只是没图：不阻断对局页 */
          });
        getAudioManifest(gameId, token || undefined)
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
        if (status === 409) {
          setErrorKind("4409");
          setAttempt(tries);
          setDetail(null);
          pollRef.current = setTimeout(() => {
            void run();
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
      setManifest({});
      // 同上：直播卸载也要停播 + 清 available（fix round 3）。
      useVoice.getState().clear(true);
    };
  }, [gameId, token, viewer, replay]);

  useEffect(() => {
    manifestRef.current = manifest;
  }, [manifest]);

  // ---- 回放门控（issue #103）：mode==="replay" 时，游标推进到某个 seq 若清单里有这句的配音，
  // 就顺序播完它的全部分段再放行时钟继续（store/game.ts 的 makeTick 消费 replayGate）。
  // 直播模式不装（声音已经跟着 WS 帧实时播，不需要卡时钟）。依赖数组特意不含 manifest——
  // 见上面 manifestRef 声明处的注释。
  useEffect(() => {
    if (mode !== "replay" || !gameId) return;
    useGameStore.getState().setReplayGate((seq) => {
      const parts = manifestRef.current[String(seq)];
      return parts ? useVoice.getState().playSeq(gameId, seq, parts, token || undefined) : null;
    });
    return () => {
      useGameStore.getState().setReplayGate(null);
      useVoice.getState().clear();
    };
  }, [mode, gameId, token]);

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

  const turnSpeaker =
    view !== null && SPEAKING_PHASES.has(view.phase) ? currentSpeaker(view) : null;
  // 正在出声的发言优先于"轮到谁"：引擎提交发言后立刻把发言权交给下一位，而音频还在播上一位，
  // 高亮/聚光牌若只看 state 会跑到下一位身上（issue #103 用户反馈）。零过滤：seq 来自服务端帧。
  const voicingSeq = useVoice((s) => s.voicingSeq);
  const voicingSeat = useMemo<number | null>(() => {
    if (voicingSeq === null) return null;
    const e = events.find((x) => x.seq === voicingSeq);
    return e?.actor_seat ?? null;
  }, [events, voicingSeq]);
  const speaking = voicingSeat ?? turnSpeaker;

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

  // 零过滤：连线完全由事件派生——观众流没有 WOLF_KILL_* / SEER_CHECKED 等事件，nightLinks 自然返回 []。
  const lines = useMemo(
    () => (view !== null && isNight(view.phase) ? nightLinks(visibleEvents, view.round) : []),
    [view, visibleEvents],
  );

  const nightRows = useMemo(
    () => (view !== null ? nightSummary(visibleEvents, view.round) : []),
    [view, visibleEvents],
  );

  if (errorKind !== null) {
    return <ErrorState kind={errorKind} attempt={attempt} detail={detail} />;
  }
  if (!ready || view === null || effectiveViewer === undefined) {
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
    <NightSummary rows={nightRows} round={view.round} viewer={effectiveViewer} />
  ) : view.phase === "SHERIFF_ELECTION" || view.phase === "SHERIFF_PK" ? (
    <ElectionPanel state={view} events={visibleEvents} />
  ) : view.phase === "VOTE" || view.phase === "VOTE_PK" || view.phase === "EXILE" ? (
    <VotePanel state={view} events={visibleEvents} />
  ) : (
    <PlayerStatusPanel state={view} speakingSeat={speaking} />
  );

  const store = useGameStore.getState();
  // 游标拖动/翻页/暂停时打断仍在播的配音（fix round 2，见 lib/replayControls.ts 头注释）。
  const controls = replayControls(store, useVoice.getState());

  return (
    <div className={`${styles.root} ${over ? styles.rootOver : ""}`}>
      <PhaseBar
        state={view}
        mode={mode}
        viewer={effectiveViewer}
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
          <VoiceToggle />
          <SeatCircle
            state={view}
            speaking={speaking}
            votes={votes}
            nightLines={lines}
            avatars={avatars}
          />
          {/* 发言者聚光牌占座位环下方的空白区（issue #102 追加） */}
          <SpeakerSpotlight state={view} seat={speaking} avatars={avatars} />
        </div>

        <div className={styles.center}>
          <SpeechFeed
            items={items}
            cursor={cursor}
            state={view}
            speakingSeat={speaking}
            avatars={avatars}
          />
          <NightOverlay phase={view.phase} viewer={effectiveViewer} />
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
        onCursor={controls.onCursor}
        onPlay={controls.onPlay}
        onPause={controls.onPause}
        onSpeed={controls.onSpeed}
        onStep={controls.onStep}
        onLive={controls.onLive}
      />
    </div>
  );
}
