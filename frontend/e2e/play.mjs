// 玩家视角全角色端到端（UI 改版 PR ② 的 3a 骨架）：登录 → Lobby 选板子 + seed → 0号「我自己」→ 建局 →
// 按角色策略把整局打完（其余座位随机 bot）→ 赛后检查。输出一行 SUMMARY JSON。
//
// 用法（后端 + `npm run dev` 都在跑）：
//   AH_BASE_URL=http://localhost:5173 AH_USER=e2e_player AH_PASS=… AH_SEED=2 RUN=wolf node play.mjs
// 环境变量：
//   AH_BASE_URL  站点（缺省 http://localhost:5173）        AH_USER / AH_PASS  走登录表单
//   AH_SESSION   直接注入会话 cookie（与 AH_USER 二选一）     AH_PRESET  板子（缺省 std_12_yn_hunter_idiot）
//   AH_SEED      发牌 seed（seat 0 角色→seed 见 README）     RUN  本局名字（日志 / 截图前缀）
//   SPEECH_SEC / ACTION_SEC  时限；MAX_MIN 最长等待分钟；RUN_SHERIFF=1 上警；SELF_DESTRUCT=1 第 2 轮自爆
//   SHOT_DIR  截图目录（缺省 shots/）
import { chromium } from "playwright-core";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

const BASE = process.env.AH_BASE_URL ?? "http://localhost:5173";
const RUN = process.env.RUN ?? "run";
const PRESET = process.env.AH_PRESET ?? "std_12_yn_hunter_idiot";
const SEED = process.env.AH_SEED ?? "";
const USER = process.env.AH_USER ?? "";
const PASS = process.env.AH_PASS ?? "";
const SESSION = process.env.AH_SESSION ?? "";
const SPEECH_SEC = process.env.SPEECH_SEC ?? "30";
const ACTION_SEC = process.env.ACTION_SEC ?? "20";
const MAX_MIN = Number(process.env.MAX_MIN ?? "12");
const RUN_SHERIFF = process.env.RUN_SHERIFF === "1";
const SELF_DESTRUCT = process.env.SELF_DESTRUCT === "1";
const SHOT_DIR = process.env.SHOT_DIR ?? "shots";
const EXE =
  process.env.CHROMIUM ??
  path.join(os.homedir(), "Library/Caches/ms-playwright/chromium-1148/chrome-mac/Chromium.app/Contents/MacOS/Chromium");

fs.mkdirSync(SHOT_DIR, { recursive: true });
const LOG = fs.createWriteStream(`${RUN}.log`);
const t0 = Date.now();
const log = (...a) => {
  const line = `[${((Date.now() - t0) / 1000).toFixed(1)}s] ${a.join(" ")}`;
  LOG.write(line + "\n");
  console.log(line);
};
let shotN = 0;
const shot = async (page, name) => {
  if (shotN++ > 120) return;
  await page.screenshot({ path: `${SHOT_DIR}/${RUN}-${String(shotN).padStart(2, "0")}-${name}.png` }).catch(() => {});
};

const S = {
  run: RUN, preset: PRESET, seed: SEED, role: null, acts: 0, yourTurns: 0, results: 0, rejected: [],
  consoleErrors: [], pageErrors: [], wsErrors: [], badResponses: [], mismatches: 0, stalls: 0,
  gameOver: false, finished: false, winner: null, phases: new Set(), rounds: 0, actionsByKind: {},
  selfDestructed: false, sheriffRan: false, historyHasGame: null, stateRole: null, replayView: null,
};
const bump = (k) => { S.acts++; S.actionsByKind[k] = (S.actionsByKind[k] ?? 0) + 1; };

const browser = await chromium.launch({ executablePath: EXE, headless: true });
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
if (SESSION) await ctx.addCookies([{ name: "agenthowl_session", value: SESSION, url: BASE, httpOnly: true, sameSite: "Lax" }]);
const page = await ctx.newPage();
page.on("console", (m) => { if (m.type() === "error") { S.consoleErrors.push(m.text().slice(0, 200)); log("CONSOLE", m.text().slice(0, 300)); } });
page.on("response", (r) => { if (r.status() >= 400) { const u = r.url().replace(BASE, "").replace(/token=[^&]+/, "token=…"); S.badResponses.push(`${r.status()} ${u}`); log("HTTP", r.status(), u); } });
page.on("pageerror", (e) => { S.pageErrors.push(e.message.slice(0, 200)); log("PAGEERROR", e.message); });

// ---- WS 观测：当前 prompt、回合、私有信息（只用于决定点哪个按钮；提交仍走 UI）----
let cur = null;
let lastSentAt = 0; let wsN = 0; const wsStats = {}; let lastActedSV = -1; const rejectedSV = new Set();
page.on("websocket", (ws) => {
  const id = ++wsN; log("WS#" + id, "open");
  ws.on("close", () => log("WS#" + id, "closed"));
  ws.on("framesent", (f) => { lastSentAt = Date.now(); log("WS#" + id, "SENT", f.payload.slice(0, 200)); });
  ws.on("framereceived", (f) => {
    let o; try { o = JSON.parse(f.payload); } catch { return; }
    wsStats[o.type] = (wsStats[o.type] ?? 0) + 1;
    if (o.type === "your_turn") {
      const obs = o.observation; S.yourTurns++; S.role ??= obs.my_role; S.phases.add(obs.phase);
      cur = { sv: obs.state_version, phase: obs.phase, role: obs.my_role, tools: o.available_tools, obs, at: Date.now() };
      log("your_turn", JSON.stringify({ phase: obs.phase, tools: o.available_tools, sv: obs.state_version, role: obs.my_role, stage: obs.election_stage ?? null, killed: obs.private?.tonight_killed_seat ?? null, dl: Math.round(o.deadline_ts - Date.now() / 1000) }));
    } else if (o.type === "action_result") {
      S.results++; if (!o.ok) { S.rejected.push(`${cur?.phase ?? "?"}:${o.rejected_reason}`); rejectedSV.add(o.state_version); }
      log("action_result", JSON.stringify(o));
    } else if (o.type === "error") { S.wsErrors.push(JSON.stringify(o).slice(0, 200)); log("WS ERROR", JSON.stringify(o)); }
    else if (o.type === "game_over") { S.gameOver = true; S.winner = o.winner ?? null; log("game_over", JSON.stringify(o)); }
    else if (o.type === "phase_change") { S.rounds = Math.max(S.rounds, o.round ?? 0); S.phases.add(o.to); log("phase_change", o.to, "round", o.round); }
  });
});

// ---- 登录 ----
await page.goto(`${BASE}/#/login`);
if (!SESSION) {
  if (!USER || !PASS) throw new Error("需要 AH_USER / AH_PASS 或 AH_SESSION");
  await page.waitForSelector("#login-id", { timeout: 15000 });
  await page.fill("#login-id", USER);
  await page.fill("#auth-pw", PASS);
  await page.click('button[type="submit"]');
}
await page.waitForSelector('nav a:has-text("新的一局")', { timeout: 15000 });
const who = await page.evaluate(async () => (await fetch("/api/v1/auth/me")).json());
log("logged in as", who.username);
await page.goto(`${BASE}/#/`);

// ---- Lobby（PR ③ 之前仍是旧大厅）----
const next1 = page.locator('button:has-text("下一步 · 分配座位")');
await next1.waitFor({ timeout: 15000 });
await page.waitForTimeout(500);
await page.click(`text=${PRESET}`);
if (SEED !== "") await page.fill("#lobby-seed", SEED);
await next1.click();
const sel = page.locator('select[aria-label="0号 座位"]');
await sel.waitFor({ timeout: 10000 });
await sel.selectOption("me");
await page.locator('aside button:has-text("汇总并开局")').click();
await page.fill('input[aria-label="我的显示名"]', "E2E");
await page.fill('input[aria-label="发言时限"]', SPEECH_SEC);
await page.fill('input[aria-label="行动时限"]', ACTION_SEC);
await page.locator('button.btn-primary:has-text("创建并开始")').last().click();
await page.waitForURL(/#\/g\/.*player=/, { timeout: 30000 });
const gameId = page.url().match(/#\/g\/([^?]+)/)?.[1];
const playerToken = page.url().match(/player=([^&]+)/)?.[1];
S.gameId = gameId;
log("game page", gameId);

// ---- 玩局循环（新 DOM：阶段木牌 .ah-plaque、HUD 行动区 [aria-label=行动区]、结算页 [aria-label=游戏结束]）----
const region = page.locator('[role="region"][aria-label="行动区"]');
let last = ""; let idleSince = Date.now(); let lastPhase = ""; let voteN = 0; let lastGuard = -1; const checked = new Set(); let candidacyN = 0; let spokeLastWordsSV = -1;
const stateText = async () => page.evaluate(() => {
  const plaque = document.querySelector(".ah-plaque");
  const phase = plaque?.firstElementChild?.textContent?.trim() ?? "";
  const over = !!document.querySelector('[role="region"][aria-label="游戏结束"]');
  const overText = document.querySelector('[role="region"][aria-label="游戏结束"] h1')?.textContent?.trim() ?? "";
  const region = document.querySelector('[role="region"][aria-label="行动区"]');
  const rtext = region ? region.textContent.trim().slice(0, 200) : "";
  const idle = [...document.querySelectorAll('[role="status"]')].map((e) => e.textContent.trim()).find((t) => /旁听中|等待裁决|天黑请闭眼|已提交/.test(t)) ?? "";
  const seats = document.querySelectorAll("button[data-seat]").length;
  const selectable = document.querySelectorAll("button[data-seat][data-selectable]").length;
  return { phase, over, overText, rtext, hasRegion: !!region, idle, seats, selectable };
});
const chips = () => region.locator('button[aria-pressed]').filter({ hasText: /^\d+号$/ });
const pickSeat = async (avoid = [], viaTable = false) => {
  const all = await chips().allInnerTexts();
  const seats = all.map((t) => Number(t.replace("号", ""))).filter((n) => !avoid.includes(n));
  if (seats.length === 0) return null;
  const s = seats[Math.floor(seats.length / 2)];
  if (viaTable) {
    // 规格 §4.2：桌上点座位与点胶囊等价
    await page.locator(`button[data-seat="${s}"][data-selectable]`).click();
  } else {
    await region.locator(`button:text-is("${s}号")`).click();
  }
  await page.waitForTimeout(80);
  return s;
};
const btn = (t) => region.locator(`button:text-is("${t}")`);
const btnRe = (re) => region.locator("button").filter({ hasText: re });
const clickFirst = async (loc, kind) => {
  if ((await loc.count()) === 0) return false;
  const b = loc.first();
  if (await b.isDisabled()) { log("disabled:", kind, "buttons=", (await region.locator("button").allInnerTexts()).join("/")); return false; }
  await b.click(); bump(kind); lastActedSV = cur?.sv ?? -1; log("ACT", kind, "sv", cur?.sv); return true;
};
const confirm = (label, kind) => clickFirst(btn(label), kind);
const confirmRe = (re, kind) => clickFirst(btnRe(re), kind);
let tableClicks = 0;
const deadline = Date.now() + MAX_MIN * 60000;
while (Date.now() < deadline) {
  const s = await stateText();
  const key = JSON.stringify(s);
  if (key !== last) {
    log("UI", JSON.stringify(s));
    if (s.phase !== lastPhase) { await shot(page, `phase-${s.phase.replace(/[^\w一-龥]+/g, "_") || "none"}`); lastPhase = s.phase; }
    last = key; idleSince = Date.now();
  }
  if (s.over || S.gameOver) {
    await page.waitForTimeout(1500);
    const f = await stateText(); S.finished = f.over; S.overText = f.overText;
    await shot(page, "over"); log("GAME OVER:", f.overText); break;
  }
  if (cur && !s.hasRegion && Date.now() - cur.at > 3000 && cur.at > lastSentAt && cur.sv !== lastActedSV) { S.mismatches++; log("MISMATCH: your_turn", Math.round((Date.now() - cur.at) / 1000), "s ago but no 行动区; idle=", s.idle); await shot(page, "mismatch"); cur = null; }
  if (Date.now() - idleSince > 90000) { S.stalls++; log("STALL: no UI change for 90s"); await shot(page, "stall"); idleSince = Date.now(); }
  const canAct = s.hasRegion && !s.rtext.includes("提交中") && cur && (cur.sv !== lastActedSV || rejectedSV.has(cur.sv));
  if (canAct) {
    const retry = rejectedSV.has(cur.sv) && cur.sv === lastActedSV; if (retry) rejectedSV.delete(cur.sv);
    const obs = cur.obs; const role = cur.role; const priv = obs.private ?? {};
    try {
      // 自爆：狼人白天 tools 含 self_destruct（页签），第 2 回合起自爆一次
      if (SELF_DESTRUCT && role === "WEREWOLF" && !S.selfDestructed && S.rounds >= 2 && cur.tools.includes("self_destruct")) {
        await region.locator('[role="tab"]:has-text("自爆")').click(); await page.waitForTimeout(100);
        await region.locator('button:not([role="tab"]):text-is("自爆")').click(); await page.waitForTimeout(100);
        if (await confirm("确认自爆", "self_destruct")) S.selfDestructed = true;
        await page.waitForTimeout(800); continue;
      }
      const ta = region.locator('textarea[aria-label="发言内容"]');
      const badgeWindow = cur.phase === "LAST_WORDS" && cur.tools.includes("sheriff_action") && (retry || spokeLastWordsSV === cur.sv || obs.badge_only);
      if (badgeWindow) {
        const tabS = region.locator('[role="tab"]:has-text("警长")'); if (await tabS.count()) { await tabS.click(); await page.waitForTimeout(100); }
        await shot(page, "badge-window");
        if (await btn("移交警徽").count()) { await pickSeat([0]); await confirm("移交警徽", "pass_badge"); }
        else if (await btn("撕警徽").count()) await confirm("撕警徽", "tear_badge");
        else log("badge window but no badge buttons; buttons=", (await region.locator("button").allInnerTexts()).join("/"));
      } else if (await ta.count()) {
        if (cur.phase === "LAST_WORDS") spokeLastWordsSV = cur.sv + 2;
        await ta.fill(`E2E（${role}）在 ${cur.phase} 第 ${S.rounds} 回合的发言 #${S.acts + 1}。`);
        const claimSel = region.locator('select[aria-label="声明身份"]');
        if (role === "SEER" && S.rounds >= 1 && (await claimSel.count())) await claimSel.selectOption("SEER");
        const flow = region.locator('input[aria-label="警徽流"]');
        if (await flow.count()) await flow.fill("3,5");
        await shot(page, "speak");
        if (!(await confirmRe(/^(发送发言|留下遗言)$/, "speak"))) log("no speak button; buttons=", (await region.locator("button").allInnerTexts()).join("/"));
      } else if (await btn("上警").count()) {
        if (RUN_SHERIFF && candidacyN++ === 0) { await confirm("上警", "run_for_sheriff"); S.sheriffRan = true; } else await confirm("不上", "withdraw");
      } else if (await btn("坚持竞选").count()) {
        if (RUN_SHERIFF && candidacyN++ <= 1) await confirm("坚持竞选", "stay_candidate"); else await confirm("退水", "withdraw");
      } else if (await btn("投给候选人").count()) { await pickSeat([0]); await confirm("投给候选人", "vote_sheriff"); }
      else if ((await btnRe(/^确认投票/).count()) || (await btn("确认 · 弃票").count())) {
        voteN++;
        if (retry || voteN % 3 === 0) { await btn("弃票").click(); await page.waitForTimeout(80); await confirm("确认 · 弃票", "vote_abstain"); }
        else { await pickSeat([0], tableClicks++ % 2 === 0); await shot(page, "vote"); await confirmRe(/^确认投票 · \d+号$/, "vote"); }
      } else if (await btn("不用药").count()) {
        // 女巫（HUD 三按钮）
        const killed = typeof priv.tonight_killed_seat === "number" ? priv.tonight_killed_seat : null;
        await shot(page, "witch");
        if (!retry && killed !== null && priv.antidote_available && killed !== 0 && (await btnRe(/^解药 · 救 \d+号$/).count())) await confirmRe(/^解药 · 救 \d+号$/, "witch_save");
        else if (!retry && priv.poison_available && S.rounds >= 2) { await btn("毒药 · 选目标").click(); await page.waitForTimeout(100); await pickSeat([0], true); await confirmRe(/^毒药 · \d+号$/, "witch_poison"); }
        else await confirm("不用药", "night_skip");
      } else if ((await btnRe(/^(刀|查验|守护|开枪)( · \d+号)?$/).count())) {
        // 夜间 / 开枪：先点座位（桌上或胶囊），再点主按钮；retry 则走跳过
        const mates = Array.isArray(priv.teammates) ? priv.teammates : [];
        const skip = region.locator("button").filter({ hasText: /^(空刀|跳过|空守|不开枪)$/ });
        if (retry) { await clickFirst(skip, "night_skip"); }
        else if (cur.phase === "HUNTER_SHOOT") { await pickSeat([0], true); await shot(page, "hunter-shoot"); if (!(await confirmRe(/^开枪 · \d+号$/, "hunter_shoot"))) await clickFirst(skip, "night_skip_fallback"); }
        else if (role === "WEREWOLF") {
          const props = priv.tonight_kill_proposals ?? {}; const follow = Object.entries(props).find(([f]) => Number(f) !== 0)?.[1];
          if (typeof follow === "number" && (await page.locator(`button[data-seat="${follow}"][data-selectable]`).count())) { await page.locator(`button[data-seat="${follow}"][data-selectable]`).click(); await page.waitForTimeout(80); }
          else await pickSeat([0, ...mates], true);
          await shot(page, "wolf-kill");
          if (!(await confirmRe(/^刀 · \d+号$/, "wolf_kill"))) await clickFirst(skip, "night_skip_fallback");
        } else if (role === "SEER") {
          const t = await pickSeat([0, ...checked], true); if (t !== null) checked.add(t);
          await shot(page, "seer-check");
          if (!(await confirmRe(/^查验 · \d+号$/, "seer_check"))) await clickFirst(skip, "night_skip_fallback");
        } else if (role === "GUARD") {
          const t = await pickSeat([lastGuard], true); lastGuard = t ?? -1;
          if (!(await confirmRe(/^守护 · \d+号$/, "guard"))) await clickFirst(skip, "night_skip_fallback");
        } else await clickFirst(skip, "night_skip");
      }
      else if (await btn("移交警徽").count()) { await pickSeat([0]); await confirm("移交警徽", "pass_badge"); }
      else if (await btn("撕警徽").count()) { await confirm("撕警徽", "tear_badge"); }
      else if (await btn("从左发言").count()) { await confirm(S.rounds % 2 ? "从右发言" : "从左发言", "direction"); }
      else if (await btn("退水").count()) { await confirm("退水", "withdraw"); }
      else log("region but no known action; buttons=", (await region.locator("button").allInnerTexts()).join("/"));
      await page.waitForTimeout(600);
    } catch (e) { log("ACT error", e.message.split("\n")[0]); }
  }
  await page.waitForTimeout(350);
}

// ---- 赛后：顶栏「查看全局回放」→ 结算 / 回放 ----
try {
  const rb = page.locator('button:has-text("查看全局回放")');
  if (await rb.count()) {
    await rb.first().click(); await page.waitForTimeout(2000);
    const t = await page.evaluate(() => document.body.innerText);
    S.replayView = { url: page.url().replace(/token=[^&]+/, "token=…").replace(/player=[^&]+/, "player=…"), hasRoles: /狼人|预言家|女巫|村民/.test(t), overScreen: !!document.querySelector('[aria-label="游戏结束"]') };
    await shot(page, "replay");
  } else S.replayView = "no button";
} catch (e) { log("replay click error", e.message.split("\n")[0]); }
try {
  const st = await page.evaluate(async (tok) => (await fetch(`/api/v1/games/${location.hash.match(/#\/g\/([^?]+)/)[1]}/state`, { headers: { Authorization: `Bearer ${tok}` } })).json(), playerToken);
  S.stateRole = st.my_role ?? null; S.statePhase = st.phase ?? null;
} catch (e) { log("post api error", e.message); }
await page.goto(`${BASE}/#/history`);
await page.waitForSelector("text=历史对局", { timeout: 10000 });
await page.waitForFunction(() => !document.body.innerText.includes("载入中"), null, { timeout: 15000 }).catch(() => log("history still loading after 15s"));
await page.waitForTimeout(300);
S.historyHasGame = (await page.evaluate(() => document.body.innerText)).includes(gameId.slice(0, 8));
S.phases = [...S.phases]; S.wsFrames = wsStats; S.wsConnections = wsN;
log("SUMMARY", JSON.stringify(S));
await browser.close();
LOG.end();
