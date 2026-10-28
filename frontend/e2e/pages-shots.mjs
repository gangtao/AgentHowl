// 其余页面截图（UI 改版 PR ④）：登录后依次截 历史对局（村志）/ Agent 档案库（村民名册）/ 打开「招募告示」编辑器 /
// 模型服务（炼金工坊）；账号是管理员时再截 用户管理（长老名册）；最后截 390 宽的档案库。
// 档案库 / 模型服务为空时先用 API 造 3 个档案 + 1 个 provider（结束后删掉；KEEP=1 保留）。
//
// 用法：AH_BASE_URL=http://localhost:5173 AH_USER=… AH_PASS=… SHOT_DIR=../../docs/design/ui-gamified-2026-10-28 node pages-shots.mjs
//   AH_SESSION=<raw cookie> 代替账号密码（用户管理页需要管理员会话）；PAGES=admin 只截用户管理页。
import { chromium } from "playwright-core";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

const BASE = process.env.AH_BASE_URL ?? "http://localhost:5173";
const USER = process.env.AH_USER ?? "";
const PASS = process.env.AH_PASS ?? "";
const OUT = process.env.SHOT_DIR ?? "shots";
const KEEP = process.env.KEEP === "1";
const SESSION = process.env.AH_SESSION ?? "";
const PAGES = (process.env.PAGES ?? "all").split(",");
const want = (k) => PAGES.includes("all") || PAGES.includes(k);
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
if (SESSION) {
  const u = new URL(BASE);
  await ctx.addCookies([
    { name: "agenthowl_session", value: SESSION, domain: u.hostname, path: "/" },
  ]);
  await page.goto(`${BASE}/#/`);
} else {
  await page.goto(`${BASE}/#/login`);
  await page.waitForSelector("#login-id");
  await page.fill("#login-id", USER);
  await page.fill("#auth-pw", PASS);
  await page.click('button[type="submit"]');
}
await page.waitForSelector('nav a:has-text("新的一局")');

/** 浏览器内带 cookie 调 API。 */
const api = (method, url, body) =>
  page.evaluate(
    async ({ method, url, body }) => {
      const r = await fetch(`/api/v1${url}`, {
        method,
        headers: { "Content-Type": "application/json" },
        body: body === undefined ? undefined : JSON.stringify(body),
      });
      const text = await r.text();
      return { status: r.status, body: text ? JSON.parse(text) : null };
    },
    { method, url, body },
  );

const me = (await api("GET", "/auth/me")).body;
log("logged in as", me.username, me.role);

// ---- 造数据（仅当为空）----
const created = { agents: [], providers: [] };
let providers = (await api("GET", "/providers")).body;
if (want("agents") || want("providers")) {
  if (providers.length === 0) {
    const r = await api("POST", "/providers", {
      name: "本地 Ollama",
      kind: "ollama",
      api_base: "http://localhost:11434",
      default_model: "qwen2.5:14b",
    });
    if (r.status < 300) created.providers.push(r.body.provider_id);
    log("provider", r.status);
    providers = (await api("GET", "/providers")).body;
  }
}
if (want("agents") && (await api("GET", "/agents")).body.length === 0) {
  // 普通用户的档案必须 BYOK：挂到第一个 provider 上
  const provider = providers[0]?.provider_id ?? null;
  const seeds = [
    {
      name: "狐语",
      model: "qwen2.5:14b",
      provider,
      temperature: 0.7,
      skills: ["*"],
      personality: { preset: { system: "MBTI", value: "ENTP" } },
      memory_id: "fox-whisper",
    },
    {
      name: "算盘",
      model: "qwen2.5:14b",
      provider,
      temperature: 0.2,
      skills: [],
      personality: { traits: { 逻辑: 0.9, 谨慎: 0.6 } },
    },
    {
      name: "老好人",
      model: "qwen2.5:7b",
      provider,
      temperature: 0.5,
      personality: { description: "与人为善，不爱出头" },
    },
  ];
  for (const p of seeds) {
    const r = await api("POST", "/agents", p);
    if (r.status < 300) created.agents.push(r.body.agent_id);
    log("agent", p.name, r.status);
  }
}

async function shot(hash, name, ready) {
  await page.goto(`${BASE}/${hash}`);
  await page.waitForSelector(ready, { timeout: 15000 });
  await page.waitForTimeout(500);
  await page.screenshot({ path: `${OUT}/${name}.png` });
  log(name);
}

if (want("history")) await shot("#/history", "06-history", 'h2:has-text("村志")');
if (want("agents")) {
  await shot("#/agents", "07-agents", 'h2:has-text("村民名册")');
  // 打开第一张角色牌的编辑器
  await page.locator('[data-agent-id] button:has-text("编辑")').first().click();
  await page.waitForSelector("text=招 募 告 示");
  await page.waitForTimeout(400);
  await page.screenshot({ path: `${OUT}/07-agents-editor.png` });
  log("07-agents-editor");
  await page.keyboard.press("Escape");
}
if (want("providers")) await shot("#/providers", "08-providers", 'h2:has-text("炼金工坊")');
if (want("admin")) {
  if (me.role === "admin") await shot("#/admin", "08-admin-users", 'h2:has-text("长老名册")');
  else log("skip admin page (not admin)");
}

if (want("agents")) {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(`${BASE}/#/agents`);
  await page.waitForSelector('h2:has-text("村民名册")');
  await page.waitForTimeout(400);
  await page.screenshot({ path: `${OUT}/07-agents-390.png`, fullPage: true });
  log("07-agents-390");
}

if (!KEEP) {
  for (const id of created.agents)
    log("del agent", id, (await api("DELETE", `/agents/${id}`)).status);
  for (const id of created.providers)
    log("del provider", id, (await api("DELETE", `/providers/${id}`)).status);
}
await browser.close();
log("done →", OUT);
