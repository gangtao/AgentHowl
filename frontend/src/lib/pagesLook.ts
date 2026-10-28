// 其余页面的外观纯函数（规格 §6，设计稿 1k / 1l / 1j）：名字 → 稳定暖色渐变（角色牌首字圆）、
// provider kind → 药剂圆配色、胜方 → 阵营色变量。零 IO、零 React；颜色只影响装饰，不承载信息判断。

/** 六对暖色，按名字哈希取；与设计稿 1k 的 hi / lo 口径一致。 */
const NAME_PALETTE: readonly { hi: string; lo: string }[] = [
  { hi: "#c9842c", lo: "#6e3a10" },
  { hi: "#b8563d", lo: "#5a1f14" },
  { hi: "#8a6a1e", lo: "#3f2e0a" },
  { hi: "#6b8a4e", lo: "#2c3f1c" },
  { hi: "#4f7a8a", lo: "#1d3540" },
  { hi: "#8a4f7a", lo: "#3d1a36" },
];
const NAME_DEFAULT = { hi: "#5a4330", lo: "#3a2a1e" } as const;

const POTION: Record<string, { hi: string; lo: string }> = {
  ollama: { hi: "#f0b85a", lo: "#8a5a1e" },
  openai: { hi: "#8fd3b6", lo: "#1f5a46" },
  anthropic: { hi: "#e8b48c", lo: "#7a3e1c" },
  openai_compatible: { hi: "#c9bca0", lo: "#5a4a33" },
  gemini: { hi: "#9db7ff", lo: "#2a3f8a" },
  deepseek: { hi: "#7fb3ff", lo: "#1c3a7a" },
};
const POTION_DEFAULT = { hi: "#a79f8c", lo: "#4a4238" } as const;

/** 按 code point 累加的稳定哈希（同名同色）。 */
function hashName(name: string): number {
  let h = 0;
  for (const ch of Array.from(name)) h = (h * 31 + (ch.codePointAt(0) ?? 0)) >>> 0;
  return h;
}

/** 名字 → 暖色渐变两端色；空名 / 全空白 → 缺省木色对。 */
export function nameGradient(name: string | null | undefined): { hi: string; lo: string } {
  const t = (name ?? "").trim();
  if (t === "") return { ...NAME_DEFAULT };
  return { ...(NAME_PALETTE[hashName(t) % NAME_PALETTE.length] ?? NAME_DEFAULT) };
}

/** 直接喂 `Avatar` 的 `color`（它写进 background）。 */
export function nameGradientCss(name: string | null | undefined): string {
  const { hi, lo } = nameGradient(name);
  return `radial-gradient(circle at 35% 30%, ${hi}, ${lo})`;
}

/** provider kind → 药剂圆两端色；后端新增的未知 kind 用缺省灰金。 */
export function potionColors(kind: string): { hi: string; lo: string } {
  return { ...(POTION[kind] ?? POTION_DEFAULT) };
}

/** 胜方 → CSS 变量名（用在羊皮纸上：好人用深金 --ah-god-hi，浅金 --ah-god 对比度不够）；平局 / 未知 → null。 */
export function winnerColorVar(winner: string | null): string | null {
  if (winner === "GOOD") return "--ah-god-hi";
  if (winner === "WOLF") return "--ah-wolf";
  return null;
}
