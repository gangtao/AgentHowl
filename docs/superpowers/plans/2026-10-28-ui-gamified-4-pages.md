# UI 游戏化 PR ④ 其余页面 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把历史对局（村志）、Agent 档案库（村民名册 + 招募告示抽屉）、模型服务（炼金工坊）、用户管理（长老名册）四页及其表单组件换成暗夜村庄视觉，数据流、请求形状与现有测试断言的业务语义不变。

**Architecture:** 新增零 IO 的 `lib/pagesLook.ts`（名字→暖色渐变、provider kind→药剂色、胜方→阵营色变量）；`HistoryTable` / `AgentCard`（完整卡）/ `ProviderCard` / `AdminUsers` 表格换皮；`AgentEditor` 重排为「一 · 身份 / 二 · 技艺 / 三 · 人格 / 四 · 声线」四节并把 memory_id 并入身份节；`SkillPicker` / `PersonalityEditor` / `ModelSelect` / `ProviderEditor` 只改样式与 kicker 文案。所有页面标题改为规格 §6 文案；`AgentCard compact`（大厅 <900px 回退用）不动。

**Tech Stack:** React 18 + TypeScript strict、CSS Modules、Vitest + Testing Library、PR ① 的 `--ah-*` 令牌与全局类（`.ah-wood/.ah-parch/.table-parch/.dialog/.seg/.tag-*/.btn-*`）、`Drawer tone="parch"`、`Avatar`（`color` 可传渐变字符串）。

**Spec:** `docs/superpowers/specs/2026-10-28-ui-gamification-design.md` §6（其余页面）、§8（PR ④：分支 `feat/ui-gamified-4-pages`，验证 `npm run check` + 各页截图）、§9；设计稿 `docs/design/gamified-2026-10-27/options/{1j,1k,4e,1l}.html`。

## Global Constraints

- 分支 `feat/ui-gamified-4-pages`，从 `main`（02bbea1）切出；`cd frontend && npm run check` 必须绿，用 `$?` 判定。
- 零过滤：四页只渲染服务端给的字段；不新增前端判断谁能看什么（admin 列仍由页面现有 `showOwner` / 路由守卫决定）。
- 请求形状不变：`AgentProfile`（extra=forbid）、`ProviderInput`、`patchUser` body；`lib/seats.ts`、`lib/personality.ts`、`lib/providerKinds.ts`、`lib/rating.ts` 不改。
- 文案（规格 §6 原文）：「村志 · 历史对局」「村民名册 · Agent 档案库」「炼金工坊 · 模型服务」「长老名册 · 用户管理」；档案库右上分段「声望 / 最近更新」、「导入 JSON」「导出全部」、篝火「+ 招募」；编辑器 kicker「招 募 告 示」、分节「一 · 身份」「二 · 技艺 · 已选 N」「三 · 人格」、按钮「盖章保存」、底部「名字与 memory_id 库内唯一；技能名与 provider 由后端校验。」；ProviderCard 状态「● 未测试 / 已连通 / 失败」、列表末尾「+ 新建药剂（provider）」；`ProviderEditor` kicker「配 方」。
- 「称号」字段不存在，不新增；角色牌金色一行用 `personalitySummary`（无则省略）。
- 现有测试的 aria-label / title（AdminUsers 的「禁用 X / 设为管理员 X / 标记已验证 X」、HistoryTable 的「回放 / 观看 / 分享 / 删除」与 title 文案、AgentEditor 的字段 label）保持；仅文案按规格改的按钮（「保存」→「盖章保存」、「+ 新建」→「+ 招募」、「积分」→「声望」）同步改测试查询。
- CSS Module 内组合器后的全局类必须 `:global()`（守卫 `cssModules.test.ts`）；页面级 CSS 不再引用 `--color-*` 旧名，改 `--ah-*`。
- 中文注释 / 英文标识符；纯函数放 `src/lib/`。

## Review Focus

1. 档案没有 `personality`、`skills` 为空、`rating.games === 0`：角色牌应省略金色行、技能区显示「无技能」、战绩行「尚无战绩」，不出现「undefined」或空括号 —— Task 3 测试。
2. 名字为空或只含空白的档案（导入的坏数据）：首字圆回退「?」、渐变仍稳定（同名同色）—— Task 1 / Task 3 测试。
3. provider `kind` 不在六种之内（后端新增）：药剂圆用缺省色、kind 行显示原字符串，不崩 —— Task 1 / Task 6 测试。
4. 历史对局 `winner` 为 null 或未知字符串、`started_at` 为 null：胜方「—」、时间「—」、不着色 —— Task 2 测试（沿用现有用例加断言）。
5. 用户表里自己那一行：不渲染操作但仍有身份 / 状态着色；`email_verified=false` 时「标记已验证」仍存在 —— Task 7 测试（沿用现有用例）。

---

### Task 1: `lib/pagesLook.ts` 外观纯函数

**Files:**
- Create: `frontend/src/lib/pagesLook.ts`
- Test: `frontend/src/lib/pagesLook.test.ts`

**Interfaces:**
- Produces:
  ```ts
  /** 名字 → 稳定的暖色渐变两端色（设计稿 1k：按名字哈希）；空名 → 缺省木色对。 */
  export function nameGradient(name: string | null | undefined): { hi: string; lo: string };
  /** `radial-gradient(circle at 35% 30%, hi, lo)`，直接喂 Avatar 的 color。 */
  export function nameGradientCss(name: string | null | undefined): string;
  /** provider kind → 药剂圆两端色；未知 kind → 缺省灰金。 */
  export function potionColors(kind: string): { hi: string; lo: string };
  /** 胜方 → CSS 变量名：GOOD → "--ah-god"，WOLF → "--ah-wolf"，其它 → null。 */
  export function winnerColorVar(winner: string | null): string | null;
  ```
  调色板（固定 6 对，按 `hash % 6` 取）：`[["#c9842c","#6e3a10"],["#b8563d","#5a1f14"],["#8a6a1e","#3f2e0a"],["#6b8a4e","#2c3f1c"],["#4f7a8a","#1d3540"],["#8a4f7a","#3d1a36"]]`；缺省 `["#5a4330","#3a2a1e"]`。药剂色：ollama `["#f0b85a","#8a5a1e"]`、openai `["#8fd3b6","#1f5a46"]`、anthropic `["#e8b48c","#7a3e1c"]`、openai_compatible `["#c9bca0","#5a4a33"]`、gemini `["#9db7ff","#2a3f8a"]`、deepseek `["#7fb3ff","#1c3a7a"]`、缺省 `["#a79f8c","#4a4238"]`。哈希：`Array.from(name.trim())` 的 code point 累加 `(h * 31 + cp) >>> 0`。

- [ ] **Step 1: Write the failing tests**

```ts
// frontend/src/lib/pagesLook.test.ts
import { describe, expect, it } from "vitest";
import { nameGradient, nameGradientCss, potionColors, winnerColorVar } from "./pagesLook";

describe("nameGradient", () => {
  it("同名同色、不同名大概率不同色、空名缺省", () => {
    expect(nameGradient("狐语")).toEqual(nameGradient("狐语"));
    expect(nameGradient("狐语")).not.toEqual(nameGradient("算盘"));
    expect(nameGradient("")).toEqual({ hi: "#5a4330", lo: "#3a2a1e" });
    expect(nameGradient("   ")).toEqual(nameGradient(null));
  });
  it("css 形状", () => {
    expect(nameGradientCss("狐语")).toMatch(/^radial-gradient\(circle at 35% 30%, #[0-9a-f]{6}, #[0-9a-f]{6}\)$/);
  });
});

describe("potionColors / winnerColorVar", () => {
  it("六种 kind 各有颜色，未知 kind 缺省", () => {
    expect(potionColors("ollama")).toEqual({ hi: "#f0b85a", lo: "#8a5a1e" });
    expect(potionColors("mystery")).toEqual({ hi: "#a79f8c", lo: "#4a4238" });
  });
  it.each([
    ["GOOD", "--ah-god"],
    ["WOLF", "--ah-wolf"],
    ["DRAW", null],
    [null, null],
  ])("%s → %s", (w, v) => expect(winnerColorVar(w)).toBe(v));
});
```

- [ ] **Step 2: Run → FAIL（模块不存在）**

Run: `cd frontend && npx vitest run src/lib/pagesLook.test.ts`

- [ ] **Step 3: Implement `pagesLook.ts` per Produces**

- [ ] **Step 4: Run → PASS；Step 5: Commit**

```bash
git add frontend/src/lib/pagesLook.ts frontend/src/lib/pagesLook.test.ts
git commit -m "feat(frontend): pagesLook 外观纯函数（名字渐变 / 药剂色 / 胜方色）"
```

---

### Task 2: 村志 · 历史对局（`History` + `HistoryTable`）

**Files:**
- Modify: `frontend/src/pages/History.tsx`（标题 / 副标 / 刷新按钮类）、`frontend/src/pages/History.module.css`（`--ah-*`）
- Modify: `frontend/src/components/HistoryTable/HistoryTable.tsx`、`HistoryTable.module.css`
- Test: `frontend/src/components/HistoryTable/HistoryTable.test.tsx`（追加断言）、`frontend/src/pages/History.test.tsx`（标题查询）

**Interfaces:**
- Consumes: `winnerColorVar` (Task 1)。
- Produces: `HistoryTable` props 不变；DOM：外层 `<div class="ah-parch {styles.ledger}">` 包 `<table class="table-parch">`；时间格 `<b>` + `<code>` id；状态签 `tag tag-wood`（finished）/ `tag tag-accent-2`（live）/ `tag tag-parch`（aborted，带描边）；胜方 `<span class={styles.winner} style={{color: var(--ah-god|--ah-wolf)}}>`（heading 15px）；操作：回放 / 观看 `<a class="btn btn-secondary {styles.act}">`，分享 `btn btn-ghost`，删除 `btn btn-ghost {styles.del}`（红字）；空态羊皮纸卡「还没有对局，去建一局」不变文案。

- [ ] **Step 1: Add failing assertions**

在 `HistoryTable.test.tsx` 追加：
```tsx
it("羊皮纸账本：胜方按阵营着色，null 胜方不着色；表格用 table-parch", () => {
  render(<HistoryTable items={[finishedGood, finishedWolf, liveRow]} />);   // 用文件里已有的夹具，按需补 winner
  expect(document.querySelector("table")).toHaveClass("table-parch");
  expect(screen.getByText("好人胜")).toHaveStyle({ color: "var(--ah-god)" });
  expect(screen.getByText("狼人胜")).toHaveStyle({ color: "var(--ah-wolf)" });
  expect(screen.getAllByText("—").length).toBeGreaterThan(0);
});
```
`History.test.tsx`：标题查询改为 `getByRole("heading", { name: "村志 · 历史对局" })`（若现有用例没查标题则新增一行断言）。

- [ ] **Step 2: Run → FAIL**

Run: `cd frontend && npx vitest run src/components/HistoryTable src/pages/History.test.tsx`

- [ ] **Step 3: Implement**

`History.tsx`：`<h2 className={styles.title}>村志 · 历史对局</h2>`（heading 30px），副标 `.lead`，刷新 `btn btn-ghost`。`HistoryTable.tsx`：按 Produces 改类名与着色；`formatStartedAt` / `PRESET_LABEL` / `WINNER_LABEL` / 排序逻辑不动。CSS：`.ledger { padding: 22px 28px }`，`.winner { font-family: var(--font-heading); font-size: 15px }`，`.seats { color: var(--ah-parch-ink-2) }`，`.del { color: var(--ah-wolf) }`，空态改羊皮纸底。

- [ ] **Step 4: Run → PASS + `cssModules.test.ts` 绿；Step 5: Commit**

```bash
git add frontend/src/pages/History.tsx frontend/src/pages/History.module.css frontend/src/pages/History.test.tsx frontend/src/components/HistoryTable
git commit -m "feat(frontend): 历史对局改「村志」羊皮纸账本"
```

---

### Task 3: 村民名册 · `AgentCard` 角色牌 + `AgentLibrary` 页头

**Files:**
- Modify: `frontend/src/components/AgentCard/AgentCard.tsx:89-145`（完整卡分支；compact 分支不动）、`AgentCard.module.css`
- Modify: `frontend/src/pages/AgentLibrary.tsx`（页头 / 排序分段 / 按钮文案 / 网格 / 空态）、`AgentLibrary.module.css`
- Test: `frontend/src/components/AgentCard/AgentCard.test.tsx`（新增）、`frontend/src/pages/AgentLibrary.test.tsx`（「积分」→「声望」）

**Interfaces:**
- Consumes: `nameGradientCss` (Task 1)；`personalitySummary`、`ratingLine`（现有）。
- Produces: 完整卡 DOM：`<article class={styles.card} data-agent-id>` → `.crown`（篝火光晕；`Avatar size=72 color={nameGradientCss(name)}`；`<h3 class={styles.name}>`；`summary !== "" && <span class={styles.title}>「{summary}」</span>`）→ `.strip`（`ah-parch`；三行 `声望 {Math.round(rating)}` / `战绩 {games === 0 ? "尚无战绩" : `${games} 局 · 胜率 ${winRate}%`}` / `性情 {summary || "—"}`）→ `.skills`（mono 小签，空 → 「无技能」）→ `.meta`「{model} · T={temperature ?? 0.3}」→ `.actions` 编辑 / 复制 / 删除（删除 muted）。`AgentLibrary`：`<h2>村民名册 · Agent 档案库</h2>`；排序 `<span class="seg" role="group" aria-label="排序">` 两个 `<label class="seg-opt">` 含 radio，文案「声望」「最近更新」（声望 = `sort === "rating"`）；「导入 JSON」「导出全部」`btn btn-ghost`；「+ 招募」`btn btn-primary`；网格 `repeat(auto-fill, minmax(200px, 1fr))`；末尾虚线木牌「+ 招募」；空态文案不变但按钮「+ 招募」。

- [ ] **Step 1: Write failing tests**

```tsx
// AgentCard.test.tsx 追加
it("角色牌：首字渐变圆 / 金色人格行 / 羊皮纸三行 / 技能签 / 模型行", () => {
  render(<AgentCard stored={withPersonality} onEdit={vi.fn()} />);   // profile: name 狐语, model openai/gpt-5, temperature 0.7, skills ["bluff","vote"], personality {preset:{system:"MBTI",value:"ENTP"}}, rating {rating:1024, games:12, wins:7,...}
  expect(screen.getByRole("heading", { name: "狐语" })).toBeInTheDocument();
  expect(screen.getByText("「ENTP」")).toBeInTheDocument();
  expect(screen.getByText("1024")).toBeInTheDocument();
  expect(screen.getByText("12 局 · 胜率 58%")).toBeInTheDocument();
  expect(screen.getByText("bluff")).toBeInTheDocument();
  expect(screen.getByText("openai/gpt-5 · T=0.7")).toBeInTheDocument();
});
it("无人格 / 无技能 / 无战绩：省略金色行，显示「无技能」「尚无战绩」", () => {
  render(<AgentCard stored={bare} />);   // profile {name:"算盘", model:"m"}, rating EMPTY_RATING
  expect(screen.queryByText(/^「.*」$/)).toBeNull();
  expect(screen.getByText("无技能")).toBeInTheDocument();
  expect(screen.getByText("尚无战绩")).toBeInTheDocument();
  expect(screen.getByText("m · T=0.3")).toBeInTheDocument();
});
```
`AgentLibrary.test.tsx`：`getByRole("button", { name: "积分" })` → `getByLabelText("声望")`（seg-opt 里的 radio）；「最近更新」同理 `getByLabelText`。

- [ ] **Step 2: Run → FAIL；Step 3: Implement；Step 4: Run → PASS（含 `SeatAssignment.test` 仍绿，compact 未动）**

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/AgentCard frontend/src/pages/AgentLibrary.tsx frontend/src/pages/AgentLibrary.module.css frontend/src/pages/AgentLibrary.test.tsx
git commit -m "feat(frontend): Agent 档案库改「村民名册」角色牌"
```

---

### Task 4: 招募告示 · `AgentEditor` 分节重排

**Files:**
- Modify: `frontend/src/components/AgentEditor/AgentEditor.tsx:238-496`（JSX 重排；`FormState` / `submit` / 校验不动）、`AgentEditor.module.css`
- Test: `frontend/src/components/AgentEditor/AgentEditor.test.tsx`（「保存」→「盖章保存」；新增分节断言）

**Interfaces:**
- Consumes: `nameGradientCss` (Task 1) 给 84px `Avatar`。
- Produces: 分节 kicker 文案（`<span class={styles.kicker}>`，11px 字距 2px `--ah-parch-link` 色）：「一 · 身份」= 头像 84px + 「上传立绘」（`btn btn-secondary`，label for 同 id）+ 「移除」(红字 ghost) + 提示；名字；`ModelSelect`；两列：温度滑杆（label「性情 · 温度 {v}」，下方「沉稳 / 跳脱」两端字）| thinking 开关 + memory_id（label「记忆 memory_id（可选）」，输入 mono，「按名字生成」，唯一性提示不变，说明「同一 memory_id 的 Agent 跨局累积经验；改 id 不迁移已有经验文件。」）。「二 · 技艺 · 已选 N」由 `SkillPicker` 的 head 渲染（Task 5 改其文案）。「三 · 人格」= `PersonalityEditor`。「四 · 声线」= 现有声线节原样。footer：外层 `.foot` 深羊皮纸由 Drawer 提供；文案不变；按钮「取消」`btn btn-ghost`、「盖章保存」`btn btn-primary`（saving → 「保存中…」）。

- [ ] **Step 1: Update tests（RED）**

`AgentEditor.test.tsx` 全文 `{ name: "保存" }` → `{ name: "盖章保存" }`；新增：
```tsx
it("招募告示分节：一 · 身份 / 三 · 人格 / 四 · 声线 kicker，memory_id 在身份节", () => {
  render(<AgentEditor stored={null} skills={[]} providers={[]} others={[]} onSave={vi.fn()} onCancel={vi.fn()} />);
  expect(screen.getByText("一 · 身份")).toBeInTheDocument();
  expect(screen.getByText("三 · 人格")).toBeInTheDocument();
  expect(screen.getByText("四 · 声线")).toBeInTheDocument();
  expect(screen.getByLabelText(/记忆 memory_id/)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "盖章保存" })).toBeDisabled();
  expect(screen.getByText("上传立绘")).toBeInTheDocument();
});
```

- [ ] **Step 2: Run → FAIL；Step 3: Implement；Step 4: Run → PASS（全文件）**

Run: `cd frontend && npx vitest run src/components/AgentEditor src/pages/AgentLibrary.test.tsx src/pages/Lobby.test.tsx`

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/AgentEditor
git commit -m "feat(frontend): AgentEditor 改「招募告示」四节（身份 / 技艺 / 人格 / 声线）"
```

---

### Task 5: `SkillPicker` / `PersonalityEditor` / `ModelSelect` / `ConfirmDialog` 羊皮纸化

**Files:**
- Modify: `frontend/src/components/SkillPicker/SkillPicker.tsx:42-48`（kicker 文案 + 选中 ■）、`SkillPicker.module.css`
- Modify: `frontend/src/components/PersonalityEditor/PersonalityEditor.module.css`（chips / sliders / preview 改羊皮纸色）
- Modify: `frontend/src/components/ModelSelect/ModelSelect.tsx:76,93`（label「模型服务（药剂）」、「↻ 拉取列表」）、`ModelSelect.module.css`
- Modify: `frontend/src/components/ConfirmDialog/ConfirmDialog.tsx`（无逻辑改动；`danger` 时标题血色）
- Test: `frontend/src/components/SkillPicker/SkillPicker.test.tsx`（新建）

**Interfaces:**
- Produces: `SkillPicker` head 文案 `二 · 技艺 · 已选 {n}`；每张技能卡 `<label class={styles.item} data-on>`，选中时前缀 `■`（`aria-hidden`），未选 `□`；名字 mono 600。`ModelSelect` provider 下拉 label「模型服务（药剂）」，拉取按钮「↻ 拉取列表」。

- [ ] **Step 1: Write failing test**

```tsx
// SkillPicker.test.tsx
it("kicker 文案与选中标记", () => {
  const onChange = vi.fn();
  render(<SkillPicker skills={[{ name: "bluff", description: "虚张声势", roles: [], phases: [] }]} value={["bluff"]} onChange={onChange} />);
  expect(screen.getByText("二 · 技艺 · 已选 1")).toBeInTheDocument();
  expect(screen.getByText("■")).toBeInTheDocument();
  fireEvent.click(screen.getByLabelText(/bluff/));
  expect(onChange).toHaveBeenCalledWith([]);
});
```

- [ ] **Step 2: Run → FAIL；Step 3: Implement（CSS：选中 `background: rgba(227,166,72,.12); border-color: var(--ah-fire)`；其余控件颜色全部换 `--ah-parch-*`）；Step 4: Run → PASS + `AgentEditor.test` + `cssModules.test` 绿**

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/SkillPicker frontend/src/components/PersonalityEditor frontend/src/components/ModelSelect frontend/src/components/ConfirmDialog
git commit -m "feat(frontend): 技能卡 / 人格编辑 / 模型选择 / 确认框羊皮纸化"
```

---

### Task 6: 炼金工坊 · `Providers` + `ProviderCard` + `ProviderEditor` 样式

**Files:**
- Modify: `frontend/src/pages/Providers.tsx`（标题 / 按钮 / 虚线新建卡）、`Providers.module.css`
- Modify: `frontend/src/components/ProviderCard/ProviderCard.tsx`、`ProviderCard.module.css`
- Modify: `frontend/src/components/ProviderEditor/ProviderEditor.module.css`（kinds chips → 羊皮纸 seg 风格；颜色换 `--ah-parch-*`）
- Test: `frontend/src/components/ProviderCard/ProviderCard.test.tsx`（新建）

**Interfaces:**
- Consumes: `potionColors` (Task 1)。
- Produces: `ProviderCard` DOM：`<article class="ah-wood {styles.card}">` → `.head`：44px `.potion`（`style={{background: radial-gradient(circle at 40% 35%, hi, lo)}}`）+ `<h3>` 名字 + 金色 `{PROVIDER_KIND_ZH[kind] ?? kind} 药剂` + 右上 `.status`「● 未测试」/「● 已连通 · {ms} ms」/「● 失败 · {ms} ms」/「● 测试中…」（颜色 muted / `--ah-ok` / `--ah-err`）→ `.strip`（`ah-parch`，三行 mono：地址 / 密钥 `已配置 ····{tail}` 或 `未配置` / 默认模型）→ 失败时 `<pre class={styles.error}>` → `.foot`「未被引用」或「被 N 个 Agent 引用：…」+ 测试连接 / 编辑 / 删除。`Providers`：`<h2>炼金工坊 · 模型服务</h2>`；页头「+ 新建」保留为 `btn btn-primary`；网格末尾 `<button class={styles.addCard}>+ 新建药剂（provider）</button>`。

- [ ] **Step 1: Write failing test**

```tsx
// ProviderCard.test.tsx
const base = { provider_id: "p1", name: "本地 Ollama", kind: "ollama", api_base: "http://localhost:11434", has_key: false, key_hint: null, default_model: "qwen2.5:14b" } as ProviderPublic;
it("药剂圆 / kind 行 / 状态 / 羊皮纸信息条", () => {
  render(<ProviderCard provider={base} refNames={["狐语", "算盘"]} onTest={vi.fn()} onEdit={vi.fn()} onDelete={vi.fn()} />);
  expect(screen.getByRole("heading", { name: "本地 Ollama" })).toBeInTheDocument();
  expect(screen.getByText("Ollama 药剂")).toBeInTheDocument();
  expect(screen.getByText("● 未测试")).toBeInTheDocument();
  expect(screen.getByText("未配置")).toBeInTheDocument();
  expect(screen.getByText(/被 2 个 Agent 引用/)).toBeInTheDocument();
});
it("未知 kind 不崩、测试结果着色文案", () => {
  render(<ProviderCard provider={{ ...base, kind: "mystery" as never, has_key: true, key_hint: "Zz0=" }} refNames={[]} test={{ ok: true, latency_ms: 42, error: null }} onTest={vi.fn()} onEdit={vi.fn()} onDelete={vi.fn()} />);
  expect(screen.getByText("mystery 药剂")).toBeInTheDocument();
  expect(screen.getByText("● 已连通 · 42 ms")).toBeInTheDocument();
  expect(screen.getByText("已配置 ····Zz0=")).toBeInTheDocument();
});
```

- [ ] **Step 2: Run → FAIL；Step 3: Implement；Step 4: Run → PASS + `ProviderEditor.test` 绿**

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/Providers.tsx frontend/src/pages/Providers.module.css frontend/src/components/ProviderCard frontend/src/components/ProviderEditor
git commit -m "feat(frontend): 模型服务改「炼金工坊」药剂木牌"
```

---

### Task 7: 长老名册 · `AdminUsers`

**Files:**
- Modify: `frontend/src/pages/AdminUsers.tsx:83-150`（标题 / 表格类 / 着色）、`AdminUsers.module.css`
- Test: `frontend/src/pages/AdminUsers.test.tsx`（追加断言）

**Interfaces:**
- Produces: `<h2>长老名册 · 用户管理</h2>`；`<div class="ah-parch {styles.ledger}"><table class="table-parch">`；列：用户名 `<b>` / 邮箱 `<code class={styles.mono}>` / 身份 `<span data-role="admin|user">`（admin `--ah-gold-ink`=`#8a6a1e`，user 墨）/ 状态 / 邮箱验证 / 注册时间 / 操作（禁用 / 启用 `btn btn-ghost {styles.danger}` 红字；设为管理员 / 降为普通用户 墨色 ghost；标记已验证 ghost）；行错误 `role="alert"` 不变。

- [ ] **Step 1: Add failing assertions**

在现有「列出用户…」用例末尾追加：
```tsx
expect(screen.getByRole("heading", { name: "长老名册 · 用户管理" })).toBeInTheDocument();
expect(document.querySelector("table")).toHaveClass("table-parch");
expect(screen.getByText("管理员")).toHaveAttribute("data-role", "admin");
```

- [ ] **Step 2: Run → FAIL；Step 3: Implement；Step 4: Run → PASS**

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/AdminUsers.tsx frontend/src/pages/AdminUsers.module.css frontend/src/pages/AdminUsers.test.tsx
git commit -m "feat(frontend): 用户管理改「长老名册」羊皮纸表"
```

---

### Task 8: 截图、文档、PR

**Files:**
- Create: `frontend/e2e/pages-shots.mjs`（登录 → 历史 / 档案库 / 打开编辑器 / 模型服务 各截 1440×900；`AH_ADMIN_SESSION` 存在时再截用户管理；390 宽档案库一张）
- Modify: `frontend/e2e/README.md`、`docs/design/ui-gamified-2026-10-28/README.md`（PR ④ 段）
- Create: `docs/design/ui-gamified-2026-10-28/06-history.png`、`07-agents.png`、`07-agents-editor.png`、`08-providers.png`、`08-admin-users.png`（有管理员会话时）、`07-agents-390.png`

- [ ] **Step 1: Write `pages-shots.mjs`（复用 `lobby-shots.mjs` 的登录段）**
- [ ] **Step 2: 起后端 + Vite，运行脚本，肉眼对照 1j / 1k / 4e / 1l**
- [ ] **Step 3: Final gate** — Run: `cd frontend && npm run check; echo EXIT=$?` → `EXIT=0`
- [ ] **Step 4: Commit、push、`gh pr create`（用户在 GitHub 合并）**

```bash
git add frontend/e2e docs/design/ui-gamified-2026-10-28
git commit -m "test(e2e): 其余页面截图脚本 + PR ④ 截图基线"
```
