// 发言台的「{model} · 声线：{voice}」行（规格 R7）：只在 meta.agents 里有这个座位的档案时才有内容。
// 上帝的 /meta 带档案，玩家 / 观众拿到的是空对象——数据驱动，不加视角分支。纯函数。

export interface AgentLine {
  /** 去掉 provider 前缀的模型名：`openai/gpt-4o` → `gpt-4o`。 */
  model: string;
  /** preset → speaker；design → 「定制」；无 voice → 「不配音」。 */
  voice: string;
}

interface VoiceLike {
  mode?: unknown;
  speaker?: unknown;
}

export function agentLine(
  agents: Record<string, unknown> | undefined,
  seat: number | null,
): AgentLine | null {
  if (agents === undefined || seat === null) return null;
  const profile = agents[String(seat)];
  if (typeof profile !== "object" || profile === null) return null;
  const model = (profile as { model?: unknown }).model;
  if (typeof model !== "string" || model.length === 0) return null;
  const short = model.includes("/") ? (model.split("/").pop() as string) : model;
  const voice = (profile as { voice?: VoiceLike | null }).voice ?? null;
  let voiceZh = "不配音";
  if (voice !== null && typeof voice === "object") {
    if (voice.mode === "design") voiceZh = "定制";
    else if (typeof voice.speaker === "string" && voice.speaker.length > 0) voiceZh = voice.speaker;
    else voiceZh = "预置";
  }
  return { model: short, voice: voiceZh };
}
