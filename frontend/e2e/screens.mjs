// 对局页截图（UI 改版 PR ②）：用一局已结束的对局，分别以上帝（登录建局者）与观众（share 链接）视角打开回放，
// 把游标拖到各阶段截图；再截 1100 / 390 宽的降级布局。
//
// 用法：AH_BASE_URL=http://localhost:5173 AH_USER=… AH_PASS=… AH_GAME=g_xxx SHOT_DIR=../../docs/design/ui-gamified-2026-10-28 node screens.mjs
import { chromium } from "playwright-core";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

const BASE = process.env.AH_BASE_URL ?? "http://localhost:5173";
const USER = process.env.AH_USER ?? "";
const PASS = process.env.AH_PASS ?? "";
const GAME = process.env.AH_GAME ?? "";
const OUT = process.env.SHOT_DIR ?? "shots";
const EXE =
  process.env.CHROMIUM ??
  path.join(os.homedir(), "Library/Caches/ms-playwright/chromium-1148/chrome-mac/Chromium.app/Contents/MacOS/Chromium");
if (!GAME) throw new Error("需要 AH_GAME（已结束的对局 id）");
fs.mkdirSync(OUT, { recursive: true });
const log = (...a) => console.log(new Date().toISOString().slice(11, 19), ...a);

const browser = await chromium.launch({ executablePath: EXE, headless: true });

async function login(ctx) {
  const p = await ctx.newPage();
  await p.goto(`${BASE}/#/login`);
  await p.waitForSelector("#login-id");
  await p.fill("#login-id", USER);
  await p.fill("#auth-pw", PASS);
  await p.click('button[type="submit"]');
  await p.waitForSelector('nav a:has-text("新的一局")');
  return p;
}

/** 把回放游标拖到满足条件的第一个位置（按 ← → 单步太慢，直接设 range）。 */
async function seek(page, pred) {
  const max = Number(await page.locator('[aria-label="回放进度"]').getAttribute("max"));
  for (let seq = 1; seq <= max; seq += 1) {
    await page.evaluate((v) => {
      const el = document.querySelector('[aria-label="回放进度"]');
      const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set;
      setter.call(el, String(v));
      el.dispatchEvent(new Event("input", { bubbles: true }));
      el.dispatchEvent(new Event("change", { bubbles: true }));
    }, seq);
    await page.waitForTimeout(30);
    const plaque = await page.locator(".ah-plaque").first().textContent();
    if (pred(plaque ?? "")) return seq;
  }
  return max;
}

const STOPS = [
  ["night", (t) => /狼人行动/.test(t)],
  ["sheriff", (t) => /警长竞选/.test(t)],
  ["speech", (t) => /白天 · 发言/.test(t)],
  ["vote", (t) => /白天 · 投票/.test(t)],
];

async function captureReplay(page, prefix) {
  await page.goto(`${BASE}/#/g/${GAME}`);
  await page.waitForSelector(".ah-plaque", { timeout: 20000 });
  await page.waitForTimeout(800);
  for (const [name, pred] of STOPS) {
    const seq = await seek(page, pred);
    await page.waitForTimeout(500);
    await page.screenshot({ path: `${OUT}/${prefix}-${name}.png` });
    log(prefix, name, "seq", seq);
  }
  // 事件流抽屉（在拖到末尾之前：结算页覆盖舞台后页签点不到）
  await page.click('button[aria-controls="event-drawer"]');
  await page.waitForTimeout(500);
  await page.screenshot({ path: `${OUT}/${prefix}-drawer.png` });
  await page.keyboard.press("Escape");
  await page.waitForTimeout(200);
  // 末尾：结算页
  const max = Number(await page.locator('[aria-label="回放进度"]').getAttribute("max"));
  await page.evaluate((v) => {
    const el = document.querySelector('[aria-label="回放进度"]');
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set.call(el, String(v));
    el.dispatchEvent(new Event("input", { bubbles: true }));
  }, max);
  await page.waitForTimeout(800);
  await page.screenshot({ path: `${OUT}/${prefix}-over.png` });
}

// ---- 上帝（建局者登录态）----
const gmCtx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
const gm = await login(gmCtx);
await captureReplay(gm, "05-gm-replay");

// ---- 观众（share 链接，匿名）----
const rows = await gm.evaluate(async () => (await fetch("/api/v1/games?limit=50")).json());
const row = (Array.isArray(rows) ? rows : rows.items ?? []).find((r) => r.game_id === GAME);
if (row?.share_token) {
  const specCtx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const spec = await specCtx.newPage();
  await spec.goto(`${BASE}/#/g/${GAME}?share=${row.share_token}`);
  await spec.waitForSelector(".ah-plaque", { timeout: 20000 });
  await spec.waitForTimeout(800);
  await spec.screenshot({ path: `${OUT}/05-spectator-replay-end.png` });
  const seq = await seek(spec, (t) => /白天 · 发言/.test(t));
  await spec.waitForTimeout(500);
  await spec.screenshot({ path: `${OUT}/05-spectator-replay-speech.png` });
  log("spectator speech seq", seq);
  await specCtx.close();
} else log("no share_token for", GAME);

// ---- 窄屏降级：1100 与 390 ----
for (const [name, vp] of [["1100", { width: 1100, height: 800 }], ["390", { width: 390, height: 844 }]]) {
  const ctx = await browser.newContext({ viewport: vp });
  const p = await login(ctx);
  await p.goto(`${BASE}/#/g/${GAME}`);
  await p.waitForSelector(".ah-plaque", { timeout: 20000 });
  await seek(p, (t) => /白天 · 发言/.test(t));
  await p.waitForTimeout(600);
  const sw = await p.evaluate(() => document.documentElement.scrollWidth);
  await p.screenshot({ path: `${OUT}/10-game-${name}.png` });
  log(name, "scrollWidth", sw, sw <= vp.width ? "OK" : "OVERFLOW");
  await ctx.close();
}

await browser.close();
log("done");
