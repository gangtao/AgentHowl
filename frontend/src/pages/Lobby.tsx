// Lobby 三步建局（设计稿 2a / 2d / 1b）：选 preset → 分配座位 → 创建并开始 → ShareDialog。
//
// 建局请求形状（规格 §7.2）：
//   POST /games {preset, config_override: {seed?}, agents: {"0": AgentProfile, "*": AgentProfile}}
// 随机 bot 座位不写入 agents；memory_id 同局唯一由 UI 禁用保证，后端 400 仍原文展示。

import { useEffect, useMemo, useState } from "react";
import type { AgentProfile } from "../api/agents";
import { ApiError, createGame, startGame, type CreateGameRequest } from "../api/rest";
import AgentEditor from "../components/AgentEditor/AgentEditor";
import PresetCard from "../components/PresetCard/PresetCard";
import SeatAssignment from "../components/SeatAssignment/SeatAssignment";
import ShareDialog from "../components/ShareDialog/ShareDialog";
import { assignmentSummary, buildAgentsPayload, emptyAssignment, type SeatSlot } from "../lib/seats";
import { useAgentLibrary } from "../store/agents";
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
  spectatorToken: string | null;
}

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

  useEffect(() => {
    void refresh();
    void refreshProviders();
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

  const agentsPayload = useMemo(
    () => buildAgentsPayload(assignment, fill, items),
    [assignment, fill, items],
  );
  const summary = assignmentSummary(assignment, fill);
  const fillAgent = fill === null ? null : (items.find((a) => a.agent_id === fill) ?? null);
  const fillBlocked = fillAgent?.profile.memory_id != null;

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
    try {
      const body: CreateGameRequest = { preset: preset.name, agents: agentsPayload };
      const seedTrimmed = seed.trim();
      if (seedTrimmed !== "") {
        const n = Number(seedTrimmed);
        if (!Number.isInteger(n)) throw new ApiError(400, "seed 必须是整数");
        body.config_override = { seed: n };
      }
      const res = await createGame(body);
      await startGame(res.game_id, res.host_token);
      setCreated({
        gameId: res.game_id,
        gmToken: res.gm_token,
        spectatorToken: res.spectator_token,
      });
    } catch (err) {
      setCreateError(err instanceof ApiError ? `${err.status} · ${err.detail}` : String(err));
    } finally {
      setCreating(false);
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
            {preset ? `${preset.num_players} 座位` : "未选板子"} · {summary.agentSeats} 个 Agent ·{" "}
            {summary.filled ? `其余 ${summary.restSeats} 座填满（*）` : `${summary.restSeats} 个随机 bot`}
          </span>
          <span className={styles.summarySub}>
            {summary.filled && fillAgent ? `其余由「${fillAgent.profile.name}」填满（*）· ` : ""}
            seed {seed.trim() === "" ? "随机" : seed.trim()}
          </span>
          <button
            type="button"
            className="btn btn-primary"
            style={{ marginTop: 6 }}
            disabled={step !== 3 || preset === null || creating || fillBlocked}
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
                从档案库把 Agent 选到座位上；未分配的座位为随机 bot（零 LLM）。同一档案可放多个座位。
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
                创建后自动开始，你以上帝视角实时观看。
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
            {createError && <div className={styles.error}>{createError}</div>}
            <div className={styles.nav}>
              <button type="button" className="btn btn-ghost" onClick={() => setStep(2)}>
                上一步
              </button>
              <button
                type="button"
                className="btn btn-primary"
                disabled={preset === null || creating || fillBlocked}
                onClick={() => void createAndStart()}
              >
                {creating ? "创建中…" : "创建并开始"}
              </button>
              <span className={styles.navHint}>POST /games → /start → #/g/{"{id}"}?gm=…</span>
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
          spectatorToken={created.spectatorToken}
          onLater={() => setCreated(null)}
          onEnter={() => {
            window.location.hash = `#/g/${created.gameId}?gm=${created.gmToken}`;
          }}
        />
      )}
    </div>
  );
}
