# Agent 人格：可配置任意性格特点（自由描述 / 自定义特质 / MBTI、Big Five 预设）— 设计文档

> 日期：2026-09-19 · 状态：已批准 · 关联：GitHub issue #57（依赖 #56 AgentProfile；与 #58 技能包并列进系统 prompt）· 上游：`docs/specs/requirements.md` §4.4.2 三段式 prompt（静态段）；调研依据见 issue #57（MBTI-in-Thoughts：prompt 注入人格在博弈场景产生稳定偏差、隐式写法有效、S/N 轴信号弱；PMC 批判：用连续强度、防漂移；PersonaLLM：Big Five 可稳定表达）

## 1. 目标与交付判据

每个 Agent 可配置**任意性格特点**：自然语言描述、自定义特质词表、MBTI / Big Five 预设三者任意组合；统一翻译成狼人杀语境的行为倾向注入系统 prompt 静态段。**MBTI 只是预设之一**。

**交付判据**：
- `AgentProfile.personality: PersonalitySpec | None`；三层输入任意组合都能生成人设段；缺省无人格时系统 prompt **逐字不变**。
- 人设段只进 `static_system_prompt`（每端口生成一次），不进动态段、不进狼夜私有段、不进反思 prompt。
- 预设展开不出现体系名（MBTI / INTJ / Big Five 等）；用户显式的 `description` / `traits` 优先于预设。
- `description` / `style_notes` 护栏：越权或改规则的短语建局即拒（API 422 / CLI 参数错误）。
- 建局响应回显 `personality`；开局档案表显示人格摘要。
- 硬约束（规则合规、公私分离、`_SELF_CHECK`）不受人格影响。

## 2. schema（新文件 `backend/app/agent/personality.py`）

```python
MBTI_AXES = ("EI", "SN", "TF", "JP")        # 每轴两字母；value 字符串须是 4 字母、每轴取其一（大小写不敏感，存大写）
BIG_FIVE_KEYS = ("O", "C", "E", "A", "N")
FORBIDDEN_PHRASES = ("你知道", "上帝视角", "无视规则", "绕过", "作弊", "真实身份是", "其实是狼")

class PersonalityPreset(BaseModel):          # frozen, extra="forbid"
    system: Literal["MBTI", "BIG_FIVE"]
    value: str | dict[str, float]
    # MBTI：str 如 "INTJ"（四轴各一字母；默认强度 E/I、T/F、J/P=0.5（「比较」档），S/N=0.3（「略微」档；信号弱）），或 dict {"E":0.8,"N":0.3,"T":0.9,"J":0.6}
    #   —— dict 键为该轴取的字母，值 0–1 为该字母倾向强度；缺省轴不出句
    # BIG_FIVE：dict {"O":0.7,"C":0.4,"E":0.9,"A":0.2,"N":0.5}，值 0–1；str 不接受

class PersonalitySpec(BaseModel):            # frozen, extra="forbid"
    description: str | None = None           # ≤ 300 字（strip 后；空 → None）
    traits: dict[str, float] = {}            # 特质词 → 强度 0–1；键 strip 非空 ≤ 12 字
    preset: PersonalityPreset | None = None
    style_notes: str | None = None           # ≤ 100 字
    # 校验：四者不能全空（"personality: {}" 拒绝）；description / style_notes 含 FORBIDDEN_PHRASES 拒绝；
    # traits 值越界拒绝；MBTI 字母/Big Five 键非法拒绝
```

- 校验失败抛 pydantic `ValidationError`：API 请求体 422；CLI `load_agent_profiles` 已把 `ValidationError` 转成参数错误（含文件名与座位键）。
- `AgentProfile`（frozen）持 `PersonalitySpec`（含 dict 字段）后，配置了人格的档案不可哈希——可接受：#59 应以 `memory_id` 字符串为键，不以档案对象为键（规格明记）。

## 3. 翻译层（同模块，纯函数）

```python
def render_personality(spec: PersonalitySpec) -> str
def personality_summary(spec: PersonalitySpec) -> str      # 档案表用：preset 代码（如 ENFP / 五维简写）否则 description 前 12 字否则首个特质词
```

`render_personality` 输出多行文本，**顺序即优先级**：

1. `description` 原文一行（`你的性格：{description}`）。
2. `traits`：按强度降序，每个一句。内置狼人杀语境词表 `_TRAIT_LEXICON`（≈15 条，特质词 → 行为句），例：多疑→「倾向质疑金水与示好，不轻信任何人」；冲动→「早表态、易改票、先说后想」；谨慎→「后置位再表态，少声称身份」；从众→「倾向跟大票、不当出头鸟」；好胜→「敢于争警长、敢于悍跳或对跳」；冷静→「情绪稳定、被怀疑时不过度辩解」；健谈→「发言长、主动带节奏」；沉默→「发言简短、只说关键信息」；固执→「一旦定论很少改票」；圆滑→「不轻易得罪人、措辞留余地」；直率→「有怀疑直接点名」；乐观／悲观／逻辑／感性 各一句。强度分档前缀：<0.34「略微」、<0.67「比较」、≥0.67「非常」。词表外的词：`你比较{词}`（按档位换前缀）。
3. `preset` 展开（隐式写法，不出现体系名）：
   - MBTI 四轴各一句（按取的字母与强度分档）：E「主动发言、愿意上警争节奏」/ I「少说多听、后置位表态」；S「只认已发生的票型与事实」/ N「敢于推测身份链、提前站边」；T「用逻辑找狼、查杀直接归票、不怕得罪人」/ F「看重信任与关系、倾向相信示好者」；J「早定论、坚持判断、不轻易改票」/ P「保留判断、随新信息灵活改口」。
   - Big Five：O 高「乐于尝试非常规打法」低「按常规套路走」；C 高「记录票型、逻辑严谨」低「凭感觉」；E 高／低同 E/I；A 高「随和、易被说服」低「多疑、爱唱反调」；N 高「被怀疑时情绪化辩解」低「情绪稳定」；0.4–0.6 之间不出句。
4. `style_notes` 一行（`说话风格：{style_notes}`）。
5. 末句固定：「以上倾向只影响你的风格与判断偏好；若相互冲突，以先出现的描述为准；不得因此违反游戏规则或泄露私有信息。」

## 4. 接入

- `prompts.py`：`static_system_prompt(config, seat, role, personality_text: str = "")`——非空时在角色行之后插入 `\n== 你的性格 ==\n{personality_text}`，通用约束句（发言用中文…）仍在其后；为空时输出逐字不变。
- `agent_player.py`：`AgentPlayerPort(..., personality: PersonalitySpec | None = None)`；`_system_for` 里 `static_system_prompt(..., personality_text=render_personality(p) if p else "")`，与技能索引并列缓存。`build_agent_port` 传 `profile.personality`。
- `profile.py`：`AgentProfile.personality: PersonalitySpec | None = None`（模块 docstring 同步）。
- `render.py` `render_agent_roster`：有人格时追加 `性格 {personality_summary}`。
- API：随 `AgentProfile` 自动接受与回显；`validate_profiles` 不需改。
- 反思 prompt（`memory.reflect`）不带人格——反思是事实摘要，不该被风格污染。

## 5. 一致性 bench（env 门控）

`tests/test_agent_bench.py` 加 `test_personality_contrast_smoke`：同一预设 seed、同一 DAY_SPEECH observation，分别用「多疑 0.9」与「从众 0.9」人格各调一次发言，打印两段发言长度与是否含「金水」「怀疑」等词；不断言方向。

## 6. 测试（零 IO 零 mock）

`tests/test_agent_personality.py`：schema（全空拒、超长拒、强度越界拒、护栏短语拒、MBTI 非法字母拒、Big Five 非法键拒、大小写归一）；`render_personality` 三层任意组合、顺序、强度分档前缀、词表内外、MBTI str/dict、Big Five 中间值不出句、隐式写法（不含 "MBTI"/"INTJ"/"Big Five"）、末句存在；`personality_summary`。
`tests/test_agent_prompts.py`：`personality_text=""` 逐字不变；非空时位于角色行之后、约束句之前。
`tests/test_agent_player.py`：带人格端口的系统 prompt 含「== 你的性格 ==」、狼夜 user prompt 不含人设段；无人格端口系统 prompt 不含。
`tests/test_agent_profile.py` / `test_api_lobby.py`：`personality` 回显；护栏短语 → 422；旧回显精确相等断言补 `"personality": None`。
`tests/test_cli_play_watch.py` / `test_cli_render.py`：YAML 里的 personality 解析；档案表摘要；护栏短语 → 参数错误。

## 7. 明确不在范围

- 训练/微调；人格随对局动态演化；人格自动生成；人格进反思 prompt；人格影响引擎默认行动。
