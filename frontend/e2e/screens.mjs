// 对局页截图（UI 改版 PR ②）：用一局已结束的对局，分别以上帝（登录建局者）与观众（share 链接）视角打开回放，
// 把游标拖到各阶段截图；再截 1100 / 390 宽的降级布局。
//
// 用法：AH_BASE_URL=http://localhost:5173 AH_USER=… AH_PASS=… AH_GAME=g_xxx SHOT_DIR=../../docs/design/ui-gamified-2026-10-28 node screens.mjs
//   AH_TABLE=cards：切到卡牌皮肤，只截上帝回放 + 390 宽，前缀 11-cards-*（UI 改版 PR ⑤）
import { chromium } from "playwright-core";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

const BASE = process.env.AH_BASE_URL ?? "http://localhost:5173";
const USER = process.env.AH_USER ?? "";
const PASS = process.env.AH_PASS ?? "";
const GAME = process.env.AH_GAME ?? "";
const OUT = process.env.SHOT_DIR ?? "shots";
const TABLE = process.env.AH_TABLE ?? "round";
const CARDS = TABLE === "cards";
const EXE =
  process.env.CHROMIUM ??
  path.join(
    os.homedir(),
    "Library/Caches/ms-playwright/chromium-1148/chrome-mac/Chromium.app/Contents/MacOS/Chromium",
  );
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

/** 切桌面皮肤（偏好记在 localStorage，同一 context 内后续页面沿用）。 */
async function pickSkin(page) {
  if (!CARDS) return;
  const skin = page.locator('select[aria-label="桌面皮肤"]');
  await skin.waitFor({ timeout: 15000 });
  await skin.selectOption("cards");
  await page.waitForSelector('[data-testid="card-board"]', { timeout: 10000 });
}

async function captureReplay(page, prefix) {
  await page.goto(`${BASE}/#/g/${GAME}`);
  await page.waitForSelector(".ah-plaque", { timeout: 20000 });
  await pickSkin(page);
  await page.waitForTimeout(800);
  for (const [name, pred] of STOPS) {
    const seq = await seek(page, pred);
    await page.waitForTimeout(500);
    await page.screenshot({ path: `${OUT}/${prefix}-${name}.png` });
    log(prefix, name, "seq", seq);
  }
  // 宽屏没有抽屉页签（右栏常驻：发言台 + 对局记录）；抽屉截图见下方窄屏段
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
await captureReplay(gm, CARDS ? "11-cards-gm-replay" : "05-gm-replay");

// ---- 观众（share 链接，匿名；卡牌皮肤只看上帝视角 + 窄屏）----
const rows = await gm.evaluate(async () => (await fetch("/api/v1/games?limit=50")).json());
const row = (Array.isArray(rows) ? rows : (rows.items ?? [])).find((r) => r.game_id === GAME);
if (CARDS) log("cards: skip spectator");
else if (row?.share_token) {
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

// ---- 窄屏降级：1024（<1100，右栏收进抽屉）与 390 ----
for (const [name, vp] of [
  ["1024", { width: 1024, height: 800 }],
  ["390", { width: 390, height: 844 }],
]) {
  const ctx = await browser.newContext({ viewport: vp });
  const p = await login(ctx);
  await p.goto(`${BASE}/#/g/${GAME}`);
  await p.waitForSelector(".ah-plaque", { timeout: 20000 });
  await pickSkin(p);
  await seek(p, (t) => /白天 · 发言/.test(t));
  await p.waitForTimeout(600);
  const sw = await p.evaluate(() => document.documentElement.scrollWidth);
  const stem = `${OUT}/${CARDS ? "11-cards-game" : "10-game"}-${name}`;
  await p.screenshot({ path: `${stem}.png` });
  log(name, "scrollWidth", sw, sw <= vp.width ? "OK" : "OVERFLOW");
  // 抽屉：发言台 + 对局记录（只在 <1100px 存在页签）
  await p.click('button[aria-controls="event-drawer"]');
  await p.waitForTimeout(500);
  await p.screenshot({ path: `${stem}-drawer.png` });
  await p.keyboard.press("Escape");
  await ctx.close();
}

await browser.close();
log("done");
