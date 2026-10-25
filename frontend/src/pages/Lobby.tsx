// Lobby 三步建局（设计稿 2a / 2d / 1b）：选 preset → 分配座位 → 创建并开始 → ShareDialog。
//
// 建局请求形状（规格 §7.2）：
//   POST /games {preset, config_override: {seed?}, agents: {"0": AgentProfile, "*": AgentProfile}}
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
import PresetCard from "../components/PresetCard/PresetCard";
import SeatAssignment from "../components/SeatAssignment/SeatAssignment";
import ShareDialog from "../components/ShareDialog/ShareDialog";
import { assignmentSummary, buildAgentsPayload, emptyAssignment, meSeat, type SeatSlot } from "../lib/seats";
import { useAgentLibrary } from "../store/agents";
import { useAuth } from "../store/auth";
import { useProviders } from "../store/providers";
import styles from "./Lobby.module.css";

const STEPS = [
  { n: 1, title: "选择对局", sub: "板子 preset 与 seed" },
  { n: 2, title: "分配座位", sub: "从档案库挑 Agent" },
  { n: 3, title: "创建并开始", sub: "汇总并开局" },
] as const;

interface Created {
  gameId: string;
  gmToken: string;
  shareToken: string | null;
}

const TTS_DISABLED: TtsStatus = { enabled: false, ok: false, url: null, detail: null, supports_style: false };

export default function Lobby(): JSX.Element {
  const { items, skills, presets, error, refresh, create } = useAgentLibrary();
  const providers = useProviders((s) => s.items);
  const refreshProviders = useProviders((s) => s.refresh);

  const [step, setStep] = useState(1);
  const [presetName, setPresetName] = useState<string | null>(null);
  const [seed, setSeed] = useState("");
  const [assignment, setAssignment] = useState<SeatSlot[]>([]);
  const [fill, setFill] = useState<string | null>(null);
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

  // 默认选中第一个 preset；换 preset 时按新人数重建座位表（保留仍存在的座位）
  useEffect(() => {
    if (presetName === null && presets.length > 0) setPresetName(presets[0]?.name ?? null);
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
      const body: CreateGameRequest = { preset: preset.name, agents: agentsPayload, voice, narration: voice && narration };
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

  const payloadKeys = Object.keys(agentsPayload).sort();

  return (
    <div className={styles.page}>
      <aside className={styles.steps}>
        {STEPS.map((s) => (
          <button
            key={s.n}
            type="button"
            className={styles.stepRow}
            aria-current={step === s.n ? "step" : undefined}
            onClick={() => setStep(s.n)}
          >
            <span
              className={`${styles.stepDot} ${step === s.n ? styles.stepDotOn : ""} ${
                step > s.n ? styles.stepDotDone : ""
              }`}
            >
              {s.n}
            </span>
            <span className={styles.stepText}>
              <span className={step === s.n ? styles.stepTitleOn : styles.stepTitle}>{s.title}</span>
              <span className={styles.stepSub}>{s.sub}</span>
            </span>
          </button>
        ))}

        <div className={styles.summary}>
          <span className="card-kicker">汇总</span>
          <span className={styles.summaryMain}>
            {preset ? `${preset.num_players} 座位` : "未选板子"} · {summary.agentSeats} 个 Agent
            {summary.humanSeat !== null ? ` · 我在 ${summary.humanSeat}号` : ""} ·{" "}
            {summary.filled ? `其余 ${summary.restSeats} 座填满（*）` : `${summary.restSeats} 个随机 bot`}
          </span>
          <span className={styles.summarySub}>
            {summary.filled && fillAgent ? `其余由「${fillAgent.profile.name}」填满（*）· ` : ""}
            seed {seed.trim() === "" ? "随机" : seed.trim()}
          </span>
          {tts.enabled && (
            <label style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12.5 }}>
              <input
                type="checkbox"
                checked={voice}
                disabled={!tts.ok}
                onChange={(e) => {
                  setVoice(e.target.checked);
                  if (!e.target.checked) setNarration(false);
                }}
              />
              语音播报{tts.ok ? "" : `（TTS 不可用：${tts.detail ?? ""}）`}
            </label>
          )}
          {tts.enabled && (
            <label style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12.5, marginLeft: 20 }}>
              <input
                type="checkbox"
                checked={voice && narration}
                disabled={!tts.ok || !voice}
                onChange={(e) => setNarration(e.target.checked)}
              />
              旁白（GM 播报阶段 / 结算 / 投票结果）
            </label>
          )}
          <button
            type="button"
            className="btn btn-primary"
            style={{ marginTop: 6 }}
            disabled={step !== 3 || preset === null || creating || fillBlocked || failedGame !== null}
            onClick={() => void createAndStart()}
          >
            {creating ? "创建中…" : "创建并开始"}
          </button>
          <span className={styles.payload}>
            agents: {payloadKeys.length === 0 ? "{}" : `{${payloadKeys.map((k) => `"${k}"`).join(", ")}}`}
          </span>
        </div>
      </aside>

      <main className={styles.main}>
        {error && <div className={styles.error}>{error}</div>}

        {step === 1 && (
          <>
            <div>
              <h3 className={styles.title}>选择对局</h3>
              <p className="text-muted" style={{ fontSize: 13, margin: 0 }}>
                全 AI 对局；未分配档案的座位是随机 bot（零 LLM）。
              </p>
            </div>
            <div className={styles.presets}>
              {presets.length === 0 ? (
                <p className="text-muted" style={{ fontSize: 13 }}>
                  载入 preset 中…
                </p>
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
              <div className="field" style={{ marginTop: 4, maxWidth: 240 }}>
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
            </div>
            <div className={styles.nav}>
              <button
                type="button"
                className="btn btn-primary"
                disabled={preset === null}
                onClick={() => setStep(2)}
              >
                下一步 · 分配座位
              </button>
            </div>
          </>
        )}

        {step === 2 && (
          <>
            <div>
              <h3 className={styles.title}>分配座位</h3>
              <p className="text-muted" style={{ fontSize: 13, margin: 0 }}>
                从档案库把 Agent 选到座位上；未分配的座位为随机 bot（零 LLM）。同一档案可放多个座位。选「我自己」即亲自入座一个座位。
              </p>
            </div>
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
            <div className={styles.nav}>
              <button type="button" className="btn btn-ghost" onClick={() => setStep(1)}>
                上一步
              </button>
              <button type="button" className="btn btn-primary" onClick={() => setStep(3)}>
                下一步 · 汇总
              </button>
            </div>
          </>
        )}

        {step === 3 && (
          <>
            <div>
              <h3 className={styles.title}>创建并开始</h3>
              <p className="text-muted" style={{ fontSize: 13, margin: 0 }}>
                {me === null
                  ? "创建后自动开始，你以上帝视角实时观看。"
                  : `你将以 ${me}号 入座，创建后直接进入玩家页；对局结束前看不到上帝视角。`}
              </p>
            </div>
            <div className={styles.review}>
              <div className={styles.reviewRow}>
                <span className={styles.reviewKey}>板子</span>
                <span>
                  {preset ? `${preset.description_zh}（${preset.name}）` : "—"}
                </span>
              </div>
              <div className={styles.reviewRow}>
                <span className={styles.reviewKey}>座位</span>
                <span>
                  {preset?.num_players ?? 0} 座 · {summary.agentSeats} 个 Agent ·{" "}
                  {summary.filled ? `其余 ${summary.restSeats} 座由「*」填满` : `${summary.restSeats} 个随机 bot`}
                </span>
              </div>
              <div className={styles.reviewRow}>
                <span className={styles.reviewKey}>seed</span>
                <span>{seed.trim() === "" ? "随机" : seed.trim()}</span>
              </div>
              {me !== null && (
                <>
                  <div className={styles.reviewRow}>
                    <span className={styles.reviewKey}>我的显示名</span>
                    <input
                      className="input"
                      aria-label="我的显示名"
                      value={displayName}
                      placeholder={user?.username ?? "我"}
                      onChange={(e) => setDisplayName(e.target.value)}
                    />
                  </div>
                  <div className={styles.reviewRow}>
                    <span className={styles.reviewKey}>发言时限（秒）</span>
                    <input className="input" aria-label="发言时限" inputMode="numeric" value={speechTimeout} onChange={(e) => setSpeechTimeout(e.target.value)} />
                  </div>
                  <div className={styles.reviewRow}>
                    <span className={styles.reviewKey}>行动时限（秒）</span>
                    <input className="input" aria-label="行动时限" inputMode="numeric" value={actionTimeout} onChange={(e) => setActionTimeout(e.target.value)} />
                  </div>
                </>
              )}
              <div className={styles.reviewRow}>
                <span className={styles.reviewKey}>agents</span>
                <pre className={styles.json}>{JSON.stringify(agentsPayload, null, 2)}</pre>
              </div>
            </div>
            {fillBlocked && (
              <div className={styles.error}>
                「{fillAgent?.profile.name}」配置了 memory_id，不能作为 <code>&quot;*&quot;</code>{" "}
                档案（后端会 400）。请回到步骤 2 改用逐座位分配。
              </div>
            )}
            {createError && (
              <div className={styles.error}>
                {createError}
                {failedGame !== null && (
                  <>
                    {" "}
                    <button type="button" className="btn btn-ghost" onClick={() => void discardFailedGame()}>
                      删除这局
                    </button>
                  </>
                )}
              </div>
            )}
            <div className={styles.nav}>
              <button type="button" className="btn btn-ghost" onClick={() => setStep(2)}>
                上一步
              </button>
              <button
                type="button"
                className="btn btn-primary"
                disabled={preset === null || creating || fillBlocked || failedGame !== null}
                onClick={() => void createAndStart()}
              >
                {creating ? "创建中…" : "创建并开始"}
              </button>
              <span className={styles.navHint}>
                {me === null ? "POST /games → /start → #/g/{id}?gm=…" : "POST /games → /join → /start → #/g/{id}?player=…"}
              </span>
            </div>
          </>
        )}
      </main>

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
