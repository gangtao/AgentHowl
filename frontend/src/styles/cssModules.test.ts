// @vitest-environment node
// CSS Module 守卫：模块文件里形如 `.local .btn-primary` 的后代选择器会被 Vite 连同全局类一起哈希成死规则，
// 引用全局类必须写成 `.local :global(.btn-primary)`。本测试扫描全部 *.module.css。
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

// global.css 里定义的全局类：精确名 + 带连字符的族前缀（本地类名是驼峰，不会撞上）。
const GLOBAL_EXACT = new Set([
  "btn",
  "input",
  "field",
  "tag",
  "seg",
  "seg-opt",
  "card",
  "nav",
  "dialog",
  "table",
  "text-muted",
  "text-mono",
  "radio",
  "hr",
]);
const GLOBAL_PREFIX = /^(ah-|btn-|tag-|card-|nav-|dialog-|table-|elev-)/;

function walk(dir: string, out: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) walk(p, out);
    else if (name.endsWith(".module.css")) out.push(p);
  }
  return out;
}

/** 返回文件里「出现在后代 / 兄弟位置且未用 :global 包住的全局类名」列表。
 *  模块自己定义 `.card { … }` 是合法本地类（它会被哈希并经 styles.card 使用），只有 `.row .input`
 *  这种把全局类放在组合器之后的写法才是死规则。 */
function leakedGlobals(css: string): string[] {
  const found: string[] = [];
  const stripped = css.replace(/\/\*[\s\S]*?\*\//g, "").replace(/:global\([^)]*\)/g, "");
  for (const m of stripped.matchAll(/([^{}]+)\{/g)) {
    const selectorList = (m[1] as string).trim();
    if (selectorList.startsWith("@")) continue;
    for (const selector of selectorList.split(",")) {
      const compounds = selector
        .trim()
        .split(/\s*[>+~]\s*|\s+/)
        .filter(Boolean);
      for (const compound of compounds.slice(1)) {
        for (const c of compound.matchAll(/\.([a-zA-Z_][\w-]*)/g)) {
          const cls = c[1] as string;
          if (GLOBAL_EXACT.has(cls) || GLOBAL_PREFIX.test(cls)) found.push(cls);
        }
      }
    }
  }
  return found;
}

const files = walk(new URL("../", import.meta.url).pathname);

describe("*.module.css 不得裸引用全局类", () => {
  it.each(files.map((f) => [f.replace(/.*\/src\//, "src/"), f]))("%s", (_label, file) => {
    expect(leakedGlobals(readFileSync(file, "utf8"))).toEqual([]);
  });
});
