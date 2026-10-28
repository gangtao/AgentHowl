// Lobby 三步建局（规格 §5，设计稿 1c / 1d / 4a）：选剧本 → 圆桌分配座位 → 开局卷轴 → ShareDialog。
// 本文件只做状态与编排；视觉在 PresetCard / SeatRing / AgentMiniList / LobbyScrollCard / LaunchScroll。
// SeatAssignment 保留为 <900px 的列表回退（CSS 切换，两套同时渲染、aria 名不同）。
//
// 建局请求形状（规格 §7.2）：
//   POST /games {preset, config_override: {seed?}, agents: {"0": AgentProfile, "*": AgentProfile}, agent_ids: {"0": agent_id, "*": agent_id}}
// 随机 bot 座位不写入 agents；memory_id 同局唯一由 UI 禁用保证，后端 400 仍原文展示。

import { useEffect, useMemo, useState } from "react";
import type { AgentProfile } from "../api/agents";
import {
  ApiError,
  createGame,
  joinGame,
  getTtsStatus,
  startGame,
  type CreateGameRequest,
  type TtsStatus,
} from "../api/rest";
import { deleteGame } from "../api/history";
import AgentEditor from "../components/AgentEditor/AgentEditor";
import LaunchScroll from "../components/LaunchScroll/LaunchScroll";
import LobbyScrollCard from "../components/LobbyScrollCard/LobbyScrollCard";
import PresetCard from "../components/PresetCard/PresetCard";
import SeatAssignment from "../components/SeatAssignment/SeatAssignment";
import AgentMiniList from "../components/SeatRing/AgentMiniList";
import SeatRing from "../components/SeatRing/SeatRing";
import ShareDialog from "../components/ShareDialog/ShareDialog";
import { seatTags } from "../lib/lobbyText";
import {
  assignmentSummary,
  buildAgentIdsPayload,
  buildAgentsPayload,
  emptyAssignment,
  meSeat,
  type SeatSlot,
} from "../lib/seats";
import { useAgentLibrary } from "../store/agents";
import { useAuth } from "../store/auth";
import { useProviders } from "../store/providers";
import styles from "./Lobby.module.css";

const STEPS = [
  { n: 1, title: "选择剧本", sub: "板子 preset 与 seed" },
  { n: 2, title: "分配座位", sub: "从档案库挑 Agent" },
  { n: 3, title: "点燃篝火", sub: "开局卷轴与时限" },
] as const;

/** 第 3 步顶部横向进度（设计稿 4a）。 */
const PROGRESS = ["① 选择剧本", "② 分配座位", "③ 点燃篝火"] as const;

interface Created {
  gameId: string;
  gmToken: string;
  shareToken: string | null;
}

const TTS_DISABLED: TtsStatus = {
  enabled: false,
  ok: false,
  url: null,
  detail: null,
  supports_style: false,
};

export default function Lobby(): JSX.Element {
  const { items, skills, presets, error, refresh, create } = useAgentLibrary();
  const providers = useProviders((s) => s.items);
  const refreshProviders = useProviders((s) => s.refresh);

  const [step, setStep] = useState(1);
  const [presetName, setPresetName] = useState<string | null>(null);
  const [seed, setSeed] = useState("");
  const [assignment, setAssignment] = useState<SeatSlot[]>([]);
  const [fill, setFill] = useState<string | null>(null);
  /** 左栏点中、待放到座位上的档案（规格 §5：先点档案再点座位）。 */
  const [pendingAgent, setPendingAgent] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);
  const [created, setCreated] = useState<Created | null>(null);
  const [newAgentOpen, setNewAgentOpen] = useState(false);
  const [newAgentError, setNewAgentError] = useState<string | null>(null);
  const [tts, setTts] = useState<TtsStatus>(TTS_DISABLED);
  const [voice, setVoice] = useState(false);
  const [narration, setNarration] = useState(false);
  const user = useAuth((s) => s.user);
  const [displayName, setDisplayName] = useState("");
  const [speechTimeout, setSpeechTimeout] = useState("120");
  const [actionTimeout, setActionTimeout] = useState("60");
  /** 三步编排中途失败留下的未开局对局：给「删除这局」用。 */
  const [failedGame, setFailedGame] = useState<string | null>(null);
  const me = meSeat(assignment);
  const effectiveName = displayName.trim() || user?.username || "我";

  useEffect(() => {
    void refresh();
    void refreshProviders();
    // 探测失败（服务未起、网络错误等）按「未开启语音」处理：建局本身不受影响（issue #103）。
    getTtsStatus()
      .then(setTts)
      .catch(() => setTts(TTS_DISABLED));
  }, [refresh, refreshProviders]);

  const preset = presets.find((p) => p.name === presetName) ?? null;

  // 默认选中第一个 preset；列表刷新后所选名字不存在（store 里是别处留下的旧列表）也回退到第一个。
  // 换 preset 时按新人数重建座位表（保留仍存在的座位）
  useEffect(() => {
    if (presets.length === 0) return;
    if (presetName === null || !presets.some((p) => p.name === presetName)) {
      setPresetName(presets[0]?.name ?? null);
    }
  }, [presets, presetName]);

  useEffect(() => {
    if (preset === null) return;
    setAssignment((prev) =>
      emptyAssignment(preset.num_players).map((slot) => ({
        seat: slot.seat,
        agentId: prev.find((p) => p.seat === slot.seat)?.agentId ?? null,
      })),
    );
  }, [preset]);

  const fillAgent = fill === null ? null : (items.find((a) => a.agent_id === fill) ?? null);
  // 含 memory_id 的档案不能当 "*"（buildAgentsPayload 会抛错）：这里先摘掉 fill 算预览，
  // 下面的 fillBlocked 负责把提示与「创建并开始」挡住
  const fillBlocked = fillAgent?.profile.memory_id != null;
  const agentsPayload = useMemo(
    () => buildAgentsPayload(assignment, fillBlocked ? null : fill, items),
    [assignment, fill, fillBlocked, items],
  );
  const agentIdsPayload = useMemo(
    () => buildAgentIdsPayload(assignment, fillBlocked ? null : fill, items),
    [assignment, fill, fillBlocked, items],
  );
  const summary = assignmentSummary(assignment, fill);

  function assign(seat: number, agentId: string | null): void {
    setAssignment((prev) => prev.map((s) => (s.seat === seat ? { ...s, agentId } : s)));
  }

  function shuffle(): void {
    setAssignment((prev) => {
      const ids = prev.map((s) => s.agentId);
      for (let i = ids.length - 1; i > 0; i -= 1) {
        const j = Math.floor(Math.random() * (i + 1));
        const a = ids[i] ?? null;
        const b = ids[j] ?? null;
        ids[i] = b;
        ids[j] = a;
      }
      return prev.map((s, i) => ({ seat: s.seat, agentId: ids[i] ?? null }));
    });
  }

  async function createAndStart(): Promise<void> {
    if (preset === null || creating) return;
    setCreating(true);
    setCreateError(null);
    let gameId: string | null = null;
    try {
      const body: CreateGameRequest = {
        preset: preset.name,
        agents: agentsPayload,
        agent_ids: agentIdsPayload,
        voice,
        narration: voice && narration,
      };
      const override: Record<string, unknown> = {};
      const seedTrimmed = seed.trim();
      if (seedTrimmed !== "") {
        const n = Number(seedTrimmed);
        if (!Number.isInteger(n)) throw new ApiError(400, "seed 必须是整数");
        override.seed = n;
      }
      if (me !== null) {
        // 真人座位：发言 / 行动时限放宽（issue #115）
        const sp = Number(speechTimeout);
        const ac = Number(actionTimeout);
        if (!Number.isInteger(sp) || sp <= 0 || !Number.isInteger(ac) || ac <= 0) {
          throw new ApiError(400, "时限必须是正整数（秒）");
        }
        override.speech_timeout_sec = sp;
        override.action_timeout_sec = ac;
      }
      if (Object.keys(override).length > 0) body.config_override = override;
      const res = await createGame(body);
      gameId = res.game_id;
      if (me === null) {
        await startGame(res.game_id, res.host_token);
        setCreated({ gameId: res.game_id, gmToken: res.gm_token, shareToken: res.share_token });
        return;
      }
      // 我自己入座：建局 → 以指定座位入座（cookie）→ 开始 → 直接进玩家页；GM 链接不展示
      const joined = await joinGame(res.game_id, { display_name: effectiveName, seat: me });
      await startGame(res.game_id, res.host_token);
      window.location.hash = `#/g/${res.game_id}?player=${encodeURIComponent(joined.player_token)}`;
    } catch (err) {
      setCreateError(err instanceof ApiError ? `${err.status} · ${err.detail}` : String(err));
      if (gameId !== null) setFailedGame(gameId);
    } finally {
      setCreating(false);
    }
  }

  async function discardFailedGame(): Promise<void> {
    if (failedGame === null) return;
    try {
      await deleteGame(failedGame);
      setFailedGame(null);
      setCreateError(null);
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) {
        // 对局已不存在（别处删过）：视同删除成功，解锁「创建并开始」
        setFailedGame(null);
        setCreateError(null);
        return;
      }
      // 其它错误保留 failedGame，可再点「删除这局」重试
      setCreateError(err instanceof ApiError ? `${err.status} · ${err.detail}` : String(err));
    }
  }

  async function saveNewAgent(profile: AgentProfile): Promise<void> {
    setNewAgentError(null);
    try {
      await create(profile);
      setNewAgentOpen(false);
    } catch (err) {
      setNewAgentError(err instanceof ApiError ? `${err.status} · ${err.detail}` : String(err));
    }
  }

  const tags = seatTags(assignment, items, fillBlocked ? null : fill);
  const canLaunch = step === 3 && preset !== null && !fillBlocked && failedGame === null;
  const fillError = fillBlocked
    ? `「${fillAgent?.profile.name ?? ""}」配置了 memory_id，不能作为 "*" 档案（后端会 400）。请回到步骤 2 改用逐座位分配。`
    : null;

  function goStep(n: number): void {
    setPendingAgent(null);
    setStep(n);
  }

  return (
    <div className={styles.page} data-step={step}>
      {step === 1 ? (
        <aside className={styles.steps}>
          <span className={styles.stepsTitle}>建 局 三 步</span>
          {STEPS.map((s) => (
            <button
              key={s.n}
              type="button"
              className={styles.stepRow}
              data-state={step === s.n ? "current" : step > s.n ? "done" : "todo"}
              aria-current={step === s.n ? "step" : undefined}
              onClick={() => goStep(s.n)}
            >
              <span className={styles.stepDot}>{s.n}</span>
              <span className={styles.stepText}>
                <span className={styles.stepTitle}>{s.title}</span>
                <span className={styles.stepSub}>{s.sub}</span>
              </span>
            </button>
          ))}
        </aside>
      ) : (
        <nav className={styles.progress} aria-label="建局进度">
          {PROGRESS.map((t, i) => (
            <button
              key={t}
              type="button"
              className={styles.progressStep}
              aria-current={i + 1 === step ? "step" : undefined}
              onClick={() => goStep(i + 1)}
            >
              {t}
            </button>
          ))}
        </nav>
      )}

      {step === 2 && (
        <aside className={styles.agentCol}>
          <div>
            <h2 className={styles.title}>分配座位</h2>
            <p className={styles.lead}>
              从档案库把 Agent 放到座位上；留空即随机 bot。选「我自己」即亲自入座。
            </p>
          </div>
          <AgentMiniList
            library={items}
            selected={pendingAgent}
            onSelect={setPendingAgent}
            onNewAgent={() => {
              setNewAgentError(null);
              setNewAgentOpen(true);
            }}
          />
        </aside>
      )}

      <main className={styles.main}>
        {error && <div className={styles.error}>{error}</div>}

        {step === 1 && (
          <>
            <div>
              <h2 className={styles.title}>选择剧本</h2>
              <p className={styles.lead}>全 AI 对局；未分配档案的座位是随机 bot（零 LLM）。</p>
            </div>
            <div className={styles.presets}>
              {presets.length === 0 ? (
                <p className={styles.lead}>载入 preset 中…</p>
              ) : (
                presets.map((p) => (
                  <PresetCard
                    key={p.name}
                    preset={p}
                    selected={p.name === presetName}
                    onSelect={() => setPresetName(p.name)}
                  />
                ))
              )}
            </div>
            <div className={`field ${styles.seedField}`}>
              <label htmlFor="lobby-seed">seed</label>
              <input
                id="lobby-seed"
                className="input"
                value={seed}
                placeholder="随机"
                inputMode="numeric"
                onChange={(e) => setSeed(e.target.value)}
              />
            </div>
            <div className={styles.nav}>
              <button
                type="button"
                className="btn btn-secondary"
                disabled={preset === null}
                onClick={() => goStep(2)}
              >
                下一步 · 分配座位 →
              </button>
            </div>
          </>
        )}

        {step === 2 && (
          <>
            <div className={styles.ringCol}>
              {pendingAgent !== null && (
                <span className={styles.pendingHint}>
                  已选中「{items.find((a) => a.agent_id === pendingAgent)?.profile.name ?? ""}」·
                  点一个座位放入
                </span>
              )}
              <SeatRing
                assignment={assignment}
                library={items}
                fill={fillBlocked ? null : fill}
                pendingAgent={pendingAgent}
                onAssign={(seat, id) => {
                  assign(seat, id);
                  setPendingAgent(null);
                }}
              />
              <div className={styles.tools}>
                <span className={styles.toolLabel}>工具：</span>
                <button
                  type="button"
                  className="btn btn-ghost"
                  onClick={() => {
                    setFill(null);
                    setAssignment((prev) => prev.map((s) => ({ seat: s.seat, agentId: null })));
                  }}
                >
                  全部随机 bot
                </button>
                <button type="button" className="btn btn-ghost" onClick={shuffle}>
                  随机打乱
                </button>
                <label className={styles.fillLabel}>
                  填满其余座位：
                  <select
                    className={`input ${styles.fillSelect}`}
                    value={fill ?? ""}
                    aria-label="填满其余座位"
                    onChange={(e) => setFill(e.target.value || null)}
                  >
                    <option value="">不填</option>
                    {items.map((a) => (
                      <option
                        key={a.agent_id}
                        value={a.agent_id}
                        disabled={a.profile.memory_id != null}
                      >
                        {a.profile.name}
                        {a.profile.memory_id != null ? "（含 memory_id，不可填满）" : ""}
                      </option>
                    ))}
                  </select>
                </label>
              </div>
              {fillError !== null && <div className={styles.error}>{fillError}</div>}
            </div>
            <div className={styles.fallback}>
              <h2 className={styles.title}>分配座位</h2>
              <p className={styles.lead}>
                从档案库把 Agent 放到座位上；留空即随机 bot。选「我自己」即亲自入座。
              </p>
              <SeatAssignment
                library={items}
                assignment={assignment}
                fill={fill}
                onAssign={assign}
                onFill={setFill}
                onAllRandom={() => {
                  setFill(null);
                  setAssignment((prev) => prev.map((s) => ({ seat: s.seat, agentId: null })));
                }}
                onShuffle={shuffle}
                onNewAgent={() => {
                  setNewAgentError(null);
                  setNewAgentOpen(true);
                }}
              />
            </div>
            <div className={styles.nav}>
              <button type="button" className="btn btn-ghost" onClick={() => goStep(1)}>
                ← 上一步
              </button>
              <button type="button" className="btn btn-secondary" onClick={() => goStep(3)}>
                下一步 · 开局卷轴 →
              </button>
            </div>
          </>
        )}

        {step === 3 && preset !== null && (
          <LaunchScroll
            preset={preset}
            me={me}
            seatTags={tags.tags}
            rest={tags.rest}
            fillName={tags.fillName}
            seed={seed}
            displayName={displayName}
            displayNamePlaceholder={user?.username ?? "我"}
            onDisplayName={setDisplayName}
            speechTimeout={speechTimeout}
            onSpeechTimeout={setSpeechTimeout}
            actionTimeout={actionTimeout}
            onActionTimeout={setActionTimeout}
            voice={voice}
            narration={voice && narration}
            ttsEnabled={tts.enabled}
            error={fillError ?? createError}
            canDiscard={failedGame !== null}
            onDiscard={() => void discardFailedGame()}
            canLaunch={canLaunch}
            creating={creating}
            onBack={() => goStep(2)}
            onLaunch={() => void createAndStart()}
          />
        )}
        {step === 3 && preset === null && <p className={styles.lead}>先回到第 1 步选择剧本。</p>}
      </main>

      <LobbyScrollCard
        numPlayers={preset?.num_players ?? null}
        presetZh={preset?.description_zh ?? null}
        summary={summary}
        fillName={fillBlocked ? null : (fillAgent?.profile.name ?? null)}
        seed={seed}
        tts={tts}
        voice={voice}
        narration={narration}
        onVoice={(v) => {
          setVoice(v);
          if (!v) setNarration(false);
        }}
        onNarration={setNarration}
        showNotes={step === 2}
        canLaunch={canLaunch}
        creating={creating}
        onLaunch={() => void createAndStart()}
      />

      {newAgentOpen && (
        <AgentEditor
          stored={null}
          skills={skills}
          providers={providers}
          others={items}
          error={newAgentError}
          onSave={(profile) => void saveNewAgent(profile)}
          onCancel={() => setNewAgentOpen(false)}
        />
      )}

      {created !== null && (
        <ShareDialog
          gameId={created.gameId}
          gmToken={created.gmToken}
          shareToken={created.shareToken}
          onLater={() => setCreated(null)}
          onEnter={() => {
            window.location.hash = `#/g/${created.gameId}?gm=${created.gmToken}`;
          }}
        />
      )}
    </div>
  );
}
