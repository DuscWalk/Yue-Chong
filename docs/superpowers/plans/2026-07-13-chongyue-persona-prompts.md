# 重岳双人格提示词 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 基于 PRTS 重岳档案和语音记录，重写普通话与武汉话两份内容丰富、可直接运行的人格提示词，并完整保留各自的官方中文原版语音。

**Architecture:** 保持现有 roleplay YAML schema 和 `load_persona`/`build_chat_messages` 不变，只替换两个 persona 数据文件。两份文件共享事实覆盖范围，但分别编写语言规则、日常互动示例和对应的官方原版语音集合；测试从加载后的 `Persona` 内容检查覆盖和语音保真。

**Tech Stack:** YAML、Python `pytest`、现有 `qq_rolebot.persona.load_persona`、Ruff。

---

### Task 1: 先锁定内容覆盖和原版语音契约

**Files:**
- Modify: `tests/test_persona_prompt_guardrails.py`

- [ ] **Step 1: 添加共享的官方语音标签和读取辅助函数**

在测试文件导入区之后加入以下内容。标签顺序与 PRTS 语音记录的中文基础语音顺序一致，缺失的编号是网页原始记录的编号间隔，不应人为补齐。

```python
OFFICIAL_VOICE_TITLES = [
    "任命助理", "交谈1", "交谈2", "交谈3", "晋升后交谈1", "晋升后交谈2",
    "信赖提升后交谈1", "信赖提升后交谈2", "信赖提升后交谈3", "闲置", "干员报到",
    "观看作战记录", "精英化晋升1", "精英化晋升2", "编入队伍", "任命队长", "行动出发",
    "行动开始", "选中干员1", "选中干员2", "部署1", "部署2", "作战中1", "作战中2",
    "作战中3", "作战中4", "完成高难行动", "3星结束行动", "非3星结束行动", "行动失败",
    "进驻设施", "戳一下", "信赖触摸", "标题", "新年祝福", "问候", "生日", "周年庆典",
]


def _official_voice_examples(persona) -> list[str]:
    return [
        example for example in persona.examples if example.startswith("官方原版语音台词-")
    ]


def _example_named(examples: list[str], title: str) -> str:
    prefix = f"官方原版语音台词-{title}"
    return next(example for example in examples if example.startswith(prefix))
```

- [ ] **Step 2: 添加普通话人格的内容和语音契约测试**

```python
def test_default_standard_persona_is_content_rich_and_preserves_mandarin_voice() -> None:
    persona = load_persona(Path("personas/default.yaml"))
    combined = "\n".join([persona.profile, persona.style, persona.background, persona.rules])
    voice = _official_voice_examples(persona)

    assert persona.language == "简体中文，普通话"
    assert len(voice) == len(OFFICIAL_VOICE_TITLES)
    assert [item.split("\n", 1)[0].removeprefix("官方原版语音台词-").removesuffix("（中文）") for item in voice] == OFFICIAL_VOICE_TITLES
    assert "炎国" in combined
    assert "玉门" in combined
    assert "罗德岛" in combined
    assert "槐天裴" in combined
    assert "夕的画" in combined
    assert "乡愁与乡愁蓝调音乐" in combined
    assert "只输出重岳会说的话" in persona.rules
    assert "让你来担任我的“录武官”？" in _example_named(persona.examples, "任命助理")
    assert "胜败乃兵家常事，振作些。" in _example_named(persona.examples, "行动失败")
```

- [ ] **Step 3: 添加武汉话人格的内容、语言差异和方言语音契约测试**

```python
def test_default_dialect_persona_is_content_rich_and_preserves_dialect_voice() -> None:
    persona = load_persona(Path("personas/default_dialect.yaml"))
    combined = "\n".join([persona.profile, persona.style, persona.background, persona.rules])
    voice = _official_voice_examples(persona)

    assert persona.language == "简体中文，武汉话口吻"
    assert len(voice) == len(OFFICIAL_VOICE_TITLES)
    assert [item.split("\n", 1)[0].removeprefix("官方原版语音台词-").removesuffix("（中文-方言）") for item in voice] == OFFICIAL_VOICE_TITLES
    assert "么样" in combined
    assert "晓得" in combined
    assert "冒得" in combined
    assert "玉门" in combined
    assert "罗德岛" in combined
    assert "十二位" in combined
    assert "让你来担任我的“录武官”？" in _example_named(persona.examples, "任命助理")
    assert "冒得关系。" in _example_named(persona.examples, "行动失败")
```

- [ ] **Step 4: 更新方言短回复测试，让官方长语音不参与日常回复长度统计**

把现有筛选条件改为：

```python
        if not example.startswith("官方原版语音台词-")
```

并保留对新增日常示例平均长度的现有断言，确保武汉话只影响口吻，不把 bot 变成长篇方言台词机。

- [ ] **Step 5: 运行新增测试，确认在提示词尚未重写前按预期失败**

Run:

```bash
~/miniconda3/envs/qq-rolebot-wsl/bin/python -m pytest -q tests/test_persona_prompt_guardrails.py
```

Expected: FAIL because现有文件没有新的官方语音标签和新的内容覆盖契约；不修改实现文件来绕过失败。

### Task 2: 重写普通话人格提示词

**Files:**
- Modify: `personas/default.yaml`

- [ ] **Step 1: 保留现有 roleplay YAML 顶层字段并重写角色底稿**

按以下顺序重写 `Profile`、`Background`、`Skills` 和 `Rules`，每一部分都写成模型可执行的角色指令：`Profile` 必须依次覆盖基础身份、自我认知、性格核心、十二位岁家成员及关系、人生经历、武学与处世、兴趣与日常；`Background` 必须覆盖泰拉、炎国、玉门、罗德岛、感染者处境和各国信息边界。每个主题都要有可用于对话的具体事实、态度和回话方向，不能用省略号或空泛形容词代替。

- [ ] **Step 2: 写明普通话输出和安全边界**

`Skills` 和 `Rules` 必须明确：现代自然普通话、默认短答、复杂问题才展开、先回应问题、少用大道理、当前信息查工具、媒体内容按实际输入、拒绝内部信息泄露，以及遇到危险内容转为认真劝阻。普通话版本不得出现武汉话词汇作为固定口头禅。

- [ ] **Step 3: 写入日常新增示例**

在官方语音集合前放置覆盖日常、训练、安慰、争执、兄妹、玉门、兴趣、天气工具、模糊图片、语音请求和安全拒绝的短示例。新增示例使用 `场景：\n回复` 两行形式，保持可直接复用。

- [ ] **Step 4: 按 PRTS 中文语音记录逐条写入 38 个官方示例**

每条格式固定为：

```yaml
  - |
    官方原版语音台词-任命助理（中文）
    让你来担任我的“录武官”？罗德岛的待客之道，真是令人动容，难怪我那几个妹妹会喜欢这里......唔，误会？那，换我做你的副将也无妨。
```

将 PRTS 中文版的 38 条台词逐字保留，包括原标点、省略号和语气，不把“全能演员”联动台词混进基础原版集合。文件顺序固定为：先放普通话日常新增示例，再连续放 38 条带 `官方原版语音台词-...（中文）` 标签的官方台词，便于测试和模型区分两者。

- [ ] **Step 5: 保留两个 PRTS 来源项**

`Sources` 保留角色档案和语音记录 URL，purpose 明确说明分别用于角色事实与原版语音/语气参考，不加入任何需要密钥的远程配置。

### Task 3: 重写武汉话人格提示词

**Files:**
- Modify: `personas/default_dialect.yaml`

- [ ] **Step 1: 复制事实覆盖但独立重写武汉话表达**

完整覆盖普通话文件的角色事实、十二位岁家成员、玉门/罗德岛/泰拉背景、武学观、兴趣和故事，但将新增说明和示例写成自然武汉熟人聊天口吻。使用“么样、搞么事、晓得、蛮、冒得、莫、咧、哈、过早”等词时控制密度，不强行每句方言化，不混入四川话或泛西南腔。

- [ ] **Step 2: 写清武汉话的场景切换规则**

方言版本要规定：日常轻松时短、顺、有气口；安慰和危险话题时收敛；训练时清楚严格；玉门、旧事和兄妹沉重话题少卖俏；官方原版方言台词按来源原样保留，不为统一新口吻改写。

- [ ] **Step 3: 写入武汉话日常新增示例**

新增示例覆盖与普通话版本相同的场景，但回复内容重新写成可读武汉话，包含“先接情绪再给小步子”“争执先降温”“查工具不乱猜”“看不清就直说”等行为约束。日常示例继续保持短回复长度测试通过。

- [ ] **Step 4: 按 PRTS 中文-方言记录逐条写入 38 个官方示例**

每条使用对应的方言原文，例如：

```yaml
  - |
    官方原版语音台词-任命助理（中文-方言）
    让你来担任我的“录武官”？罗德岛的待客之道，真是让人动容，难怪我那几个妹妹会喜欢这里......么煞，搞错了？那，换我做你的副将也冒得问题。
```

严格保留 PRTS 中文-方言版本的 38 条基础语音，不自行把普通话台词改成方言，也不加入全能演员联动语音。

- [ ] **Step 5: 保留两个 PRTS 来源项**

来源 URL 与普通话文件一致，purpose 说明方言版本还用于官方中文方言台词和表达参考。

### Task 4: 运行聚焦测试并修正内容回归

**Files:**
- Modify: `tests/test_persona_prompt_guardrails.py` only if a test assertion needs to reflect the approved prompt contract.

- [ ] **Step 1: 运行 persona 聚焦测试**

Run:

```bash
~/miniconda3/envs/qq-rolebot-wsl/bin/python -m pytest -q tests/test_persona_prompt_guardrails.py
```

Expected: all tests pass,包括 YAML 加载、内容覆盖、两套 38 条官方语音、武汉话日常示例长度和 prompt builder 集成。

- [ ] **Step 2: 直接检查两份加载后的统计信息**

Run:

```bash
~/miniconda3/envs/qq-rolebot-wsl/bin/python - <<'PY'
from pathlib import Path
from qq_rolebot.persona import load_persona

for path in (Path("personas/default.yaml"), Path("personas/default_dialect.yaml")):
    persona = load_persona(path)
    voice = [item for item in persona.examples if item.startswith("官方原版语音台词-")]
    print(path, persona.language, len(persona.profile), len(persona.background), len(persona.examples), len(voice))
PY
```

Expected: 两份都打印 `38` 个官方语音条目，且 profile/background/examples 均为非空的长文本。

### Task 5: 完整验证并提交人格改动

**Files:**
- Modify: `personas/default.yaml`
- Modify: `personas/default_dialect.yaml`
- Modify: `tests/test_persona_prompt_guardrails.py`

- [ ] **Step 1: 运行仓库级检查**

Run:

```bash
~/miniconda3/envs/qq-rolebot-wsl/bin/python -m ruff check .
~/miniconda3/envs/qq-rolebot-wsl/bin/python -m pytest -q
git diff --check
```

Expected: Ruff exit 0、pytest 无失败、`git diff --check` 无输出。若失败只修复本任务引入的问题，不改动工作区中原有的 `message_segments` 相关改动。

- [ ] **Step 2: 检查最终 diff 只包含本任务目标文件和已批准规格/计划**

Run:

```bash
git status --short --untracked-files=all
git diff --stat -- personas/default.yaml personas/default_dialect.yaml tests/test_persona_prompt_guardrails.py
```

确认没有 `.env`、数据库、二维码、模型、缓存、日志或其他服务器产物。

- [ ] **Step 3: 提交本任务改动**

```bash
git add personas/default.yaml personas/default_dialect.yaml tests/test_persona_prompt_guardrails.py
git commit -m "feat: rewrite Chongyue persona prompts"
```

不要将用户原有的 `qq_rolebot/message_segments.py`、`tests/test_message_segments.py`、`tests/test_plugin_smoke.py` 或其相关文档加入本次提交。
