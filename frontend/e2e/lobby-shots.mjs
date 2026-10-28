// 大厅截图（UI 改版 PR ③）：登录后走完建局三步（不点「点燃篝火」），分别在 1440×900 截第 1 / 2 / 3 步，
// 第 2 步额外截一张打开木牌菜单的，再截 390 宽的列表回退。
//
// 用法：AH_BASE_URL=http://localhost:5173 AH_USER=… AH_PASS=… SHOT_DIR=../../docs/design/ui-gamified-2026-10-28 node lobby-shots.mjs
import { chromium } from "playwright-core";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

const BASE = process.env.AH_BASE_URL ?? "http://localhost:5173";
const USER = process.env.AH_USER ?? "";
const PASS = process.env.AH_PASS ?? "";
const OUT = process.env.SHOT_DIR ?? "shots";
const PRESET = process.env.AH_PRESET ?? "12 人预女猎白";
const EXE =
  process.env.CHROMIUM ??
  path.join(
    os.homedir(),
    "Library/Caches/ms-playwright/chromium-1148/chrome-mac/Chromium.app/Contents/MacOS/Chromium",
  );
fs.mkdirSync(OUT, { recursive: true });
const log = (...a) => console.log(new Date().toISOString().slice(11, 19), ...a);

const browser = await chromium.launch({ executablePath: EXE, headless: true });
const ctx = await browser.newContext({
  viewport: { width: 1440, height: 900 },
  deviceScaleFactor: 1,
});
const page = await ctx.newPage();
await page.goto(`${BASE}/#/login`);
await page.waitForSelector("#login-id");
await page.fill("#login-id", USER);
await page.fill("#auth-pw", PASS);
await page.click('button[type="submit"]');
await page.waitForSelector('nav a:has-text("新的一局")');
await page.goto(`${BASE}/#/`);

const next1 = page.locator('button:has-text("下一步 · 分配座位")');
await next1.waitFor({ timeout: 15000 });
await page.waitForTimeout(600);
await page.click(`text=${PRESET}`);
await page.fill("#lobby-seed", "42");
await page.waitForTimeout(200);
await page.screenshot({ path: `${OUT}/02-lobby-1-preset.png` });
log("step 1");

await next1.click();
const seat0 = page.locator('button[aria-label="入座 0号"]');
await seat0.waitFor({ timeout: 10000 });
await seat0.click();
await page.locator('[role="menuitem"]:has-text("我自己")').click();
// 若档案库有档案：先点中第一张卡，再把它放到 2 号；然后打开 5 号菜单截图
const firstCard = page.locator("[data-agent-id]").first();
if ((await firstCard.count()) > 0) {
  await firstCard.click();
  await page.locator('button[aria-label="入座 2号"]').click();
  await firstCard.click();
  await page.locator('button[aria-label="入座 7号"]').click();
}
await page.locator('button[aria-label="入座 5号"]').click();
await page.waitForSelector('[role="menu"]');
await page.waitForTimeout(200);
await page.screenshot({ path: `${OUT}/02-lobby-2-seats-menu.png` });
await page.keyboard.press("Escape");
await page.waitForTimeout(150);
await page.screenshot({ path: `${OUT}/02-lobby-2-seats.png` });
log("step 2");

await page.locator('button:has-text("下一步 · 开局卷轴")').click();
await page.waitForSelector("section.ah-parch");
await page.waitForTimeout(200);
await page.screenshot({ path: `${OUT}/02-lobby-3-scroll.png` });
log("step 3");

// 1100 宽：第 2 步档案列上移、圆桌保持 480px；第 1 步剧本牌单列
await page.locator('button:has-text("← 上一步 · 分配座位")').click();
await page.setViewportSize({ width: 1100, height: 900 });
await page.waitForTimeout(300);
await page.screenshot({ path: `${OUT}/02-lobby-2-seats-1100.png` });
await page.locator('button:has-text("① 选择剧本")').click();
await page.waitForTimeout(200);
await page.screenshot({ path: `${OUT}/02-lobby-1-preset-1100.png` });
await page.locator('button:has-text("下一步 · 分配座位")').click();
log("1100");

// 390 宽：第 2 步列表回退
await page.setViewportSize({ width: 390, height: 844 });
await page.waitForTimeout(300);
await page.screenshot({ path: `${OUT}/02-lobby-2-seats-390.png`, fullPage: true });
log("390 fallback");

await browser.close();
log("done →", OUT);
