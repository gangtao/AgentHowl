// 由档案名生成一个安全的 memory_id（规格 §7.2b 第 4 组「按名字生成」）。
//
// 后端约束（app/agent/experience.py::MEMORY_ID_PATTERN）：`^[A-Za-z0-9_\-]{1,64}$`。
// 拉丁字母 / 数字原样保留（转小写），其余字符（中文等）用短横替代；被替换掉非 ASCII 时
// 追加名字哈希的 6 位十六进制以避免不同中文名撞成同一个 id。

const MAX_LEN = 64;

/** FNV-1a 32 位；纯函数、跨平台一致，只用于生成后缀，不做安全用途。 */
function hash6(text: string): string {
  let h = 0x811c9dc5;
  for (let i = 0; i < text.length; i += 1) {
    h ^= text.charCodeAt(i);
    h = Math.imul(h, 0x01000193) >>> 0;
  }
  return h.toString(16).padStart(8, "0").slice(-6);
}

function trimDashes(s: string): string {
  return s.replace(/^[-_]+/, "").replace(/[-_]+$/, "");
}

/**
 * `suggestMemoryId("Night Owl")` → `night-owl`；`suggestMemoryId("夜枭")` → `agent-xxxxxx`；
 * 混合名（`夜枭 Owl`）保留拉丁部分并追加哈希后缀，保证不同名字不会撞 id。
 */
export function suggestMemoryId(name: string): string {
  const source = name.trim();
  const slug = trimDashes(source.toLowerCase().replace(/[^a-z0-9_-]+/g, "-"));
  const droppedNonAscii = /[^\x20-\x7E]/.test(source);
  let out: string;
  if (!slug) {
    out = `agent-${hash6(source)}`;
  } else if (droppedNonAscii) {
    out = `${slug}-${hash6(source)}`;
  } else {
    out = slug;
  }
  return trimDashes(out.slice(0, MAX_LEN)) || `agent-${hash6(source)}`;
}

/** 前端即时校验：与后端 MEMORY_ID_PATTERN 同口径。 */
export function isValidMemoryId(value: string): boolean {
  return /^[A-Za-z0-9_-]{1,64}$/.test(value);
}
