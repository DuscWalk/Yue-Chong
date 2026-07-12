# Lens-First Vision Pipeline Design

## Status

本设计取代：

- `docs/superpowers/specs/2026-07-08-vision-media-search-design.md`
- `docs/superpowers/specs/2026-07-10-evidence-driven-vision-pipeline-design.md`

旧设计仍保留为历史记录，但不再代表下一版生产实现。

## Goal

重构 QQ 机器人的静态图片理解流程，以识别准确率为首要目标，同时控制常见图片的等待时间和 SerpApi 免费额度消耗。

新流程必须：

- 支持用户对图片提出任意问题，不要求预先选择 OCR、人物识别或梗图识别分类。
- 客观描述画面和可见文字。
- 图片中存在人物、虚构角色或二次元形象时，尽量给出人物、作品和来源信息。
- 证据不足时宁可说明不确定，不强行猜测。
- 使用可观测的 SerpApi Google Lens，而不是依赖 Qwen 内置但不可验证的图搜工具。
- 保留现有触发策略：只有机器人已经决定回复时才处理图片。
- 支持同一条消息中的多张图片，以及跨图片比较问题。
- 不要求 Cloudflare R2、域名或已配置的 HTTPS 临时发布服务。

## Non-Goals

- 不让视觉模型决定群聊中是否可以回复。
- 不建立严格的证据审计系统，也不要求代码逐条验证 Qwen 引用的搜索证据。
- 不保证识别所有人物、角色、表情包、地点或物品。
- 不主动识别普通或未知真人身份。
- 不在仓库或永久图片目录中保存用户发送的原图。
- 不保留旧视觉实现作为并行生产路径。
- 不把最终角色扮演模型的生成时间计入识图阶段预算。

## Production Benchmark

设计结论来自生产服务器上的真实 SerpApi、Qwen3.7 Plus 和 QQ 临时图片 URL测试。测试期间使用的图片、原始 URL和临时响应均已删除。

### Thinking

同一张 1248x2532 图片：

- `enable_thinking=true`：15.24 秒后超时。
- `enable_thinking=false`：5.75 秒完成，并正确识别为《明日方舟》的“夕”。

下一版视觉调用默认关闭 thinking。

### Original Dual Lens Flow

对三张已确认真实标签的图片，同时请求 `visual_matches` 和 `exact_matches`：

| 图片 | Visual Lens | Exact Lens | 主要结果 |
| --- | ---: | ---: | --- |
| Priestess 低清头像 | 30.87 秒 | 32.87 秒 | exact 明确识别 Priestess |
| 龙泡泡相关梗图 | 7.85 秒 | 19.70 秒，无结果 | visual 指向明日方舟梗图来源 |
| Lemuen 海报 | 25.62 秒 | 16.21 秒 | exact 找到官方海报，visual 指向 Lemuen |

该流程存在三个问题：

- 每张冷图固定消耗两次 SerpApi 查询。
- 任一路失败时，当前客户端可能丢弃另一路已经成功的结果。
- 后续候选抽取和 Web 验证会继续累加等待时间。

### Selected `type=all` Flow

使用单次 Lens `type=all`，再调用一次关闭 thinking 的 Qwen：

| 图片 | Cold Lens `all` | Qwen | 估算识图总耗时 | 结果 |
| --- | ---: | ---: | ---: | --- |
| Priestess | 12.71 秒 | 4.17 秒 | 16.88 秒 | 正确 |
| 龙泡泡相关梗图 | 7.05 秒 | 6.30 秒 | 13.35 秒 | 识别为明日方舟 Dusk Bean 梗图 |
| Lemuen | 16.92 秒 | 6.94 秒 | 23.86 秒 | 正确 |

在这个三图小样本中，主链达到 3/3，且未使用固定 exact 或普通 Web Search。

### `auto_crop`

`auto_crop=true` 对三张图的 Lens visual 耗时变化分别为：

- `-12.31` 秒；
- `+2.59` 秒；
- `-2.61` 秒。

它可能改善某些图片的关注区域，但不是稳定提速开关，因此不作为默认配置。

## Selected Architecture

静态图片使用 Lens-first 两步主链：

```text
Trigger policy allows reply
    -> download, normalize, hash, deduplicate images
    -> SerpApi Google Lens type=all for each unique image
    -> one Qwen call with all images, user question, chat context, and per-image Lens results
    -> optional exact or Google Search fallback requested by Qwen
    -> at most one short Qwen re-evaluation after fallback
    -> concise Vision Context for the existing roleplay model
```

识图内部常见路径只有 Lens 和 Qwen 两个外部阶段。最终角色扮演回复仍由现有主对话模型生成。

## Main Flow

### 1. Trigger First

群白名单、`/bot on`、私聊、直接 `@`、回复机器人和跟进策略保持不变。

图片下载、Lens 和 Qwen 只在现有策略已经决定机器人应当回复后执行。未触发回复的群图片不得提交给任何视觉或搜索服务。

### 2. Preprocess And Fingerprint

对每张允许处理的静态图片：

- 下载一次并限制重定向、字节数和解码像素数。
- 根据文件魔数和实际解码结果验证格式，不只信任响应头。
- 修正 EXIF 方向。
- 转换为模型和临时发布服务可接受的 JPEG 或 PNG。
- Qwen 输入默认将长边限制为 1600 像素，避免单图或四图 Base64 请求体过大。
- 对规范化字节计算 SHA-256。
- 在内存中共享同一份规范化结果，不重复下载或解码。

同一消息中的相同图片只预处理和搜索一次，但最终结果仍映射回原始位置。

### 3. Lens `type=all`

每张唯一图片默认执行一次：

```text
engine=google_lens
type=all
async=true
(omit no_cache to keep its default cache behavior)
auto_crop=false
```

运行规则：

- 优先使用原始 QQ 图片 URL。
- 使用异步提交并通过 Search Archive API 轮询。
- 默认轮询间隔为 0.75 秒。
- 解析 `visual_matches`、`related_content`、`ai_overview` 和明确错误状态。
- 搜索结果保留原始顺序并做长度限制，避免把过多网页文本交给 Qwen。
- Qwen 需要 exact 时才请求 `type=exact_matches`。
- Qwen 需要网页背景时才执行 SerpApi Google Search。
- `type=all` 失败时仍继续 Qwen 直接看图。

SerpApi 的服务端缓存只在 URL和所有参数完全一致时命中，且默认保存一小时。应用必须另外使用图片哈希缓存，以应对 QQ URL变化。

### 4. One Qwen Synthesis Call

所有主 Lens 任务完成、超时或明确失败后，调用一次 Qwen。该调用接收：

- 用户原始问题；
- 有界聊天上下文；
- 按消息顺序编号的所有图片；
- 每张图片对应的 Lens `all` 结果；
- 哪些图片没有可用 Lens 结果。

Qwen 使用 `enable_thinking=false` 和结构化输出。每张图输出：

- `scene_description`；
- `visible_text[]`；
- `subject_identity`；
- `work_or_affiliation`；
- `source_series_or_author`；
- `confidence`：`confirmed`、`uncertain` 或 `no_identity`；
- `reason`；
- `needs_exact`；
- `needs_web`；
- `verification_query`。

Qwen 同时输出一段面向用户问题的多图综合结论，以支持比较、排序和关系问题。

代码不建立严格语义裁决器，也不要求逐条验证 Qwen 引用的 Lens 证据。提示词要求模型谨慎处理聚合标题、多角色列表、商品页和外观相似结果；冲突明显时应返回不确定。

### 5. Conditional Fallback

只有 Qwen 请求时才执行回退：

- `needs_exact=true`：对对应图片请求 `exact_matches`。
- `needs_web=true`：使用 `verification_query` 做一次普通 Google Search。

每条消息最多执行：

- 两次 exact 回退；
- 两次 Web Search 回退。

回退结果到达后，最多执行一次短 Qwen 复判。复判只接收第一次结构化结果和新增搜索文本，不再次上传图片。

不得出现模型反复请求工具的循环。

## Judgment Policy

这是聊天机器人级别的轻量判断策略：

- Qwen 负责综合原图和搜索结果，代码负责调度、超时、缓存和失败降级。
- Qwen 判断足够明确时可直接输出人物、作品和来源。
- 聚合结果一次列出多个角色时，不应仅凭该标题选择其中一人。
- 搜索结果和图片特征冲突时，应返回不确定或请求回退。
- 表情包可以识别系列、作者或同人来源，不要求虚构规范角色名。
- 未知真人不主动识别身份，但可以描述外观、动作和场景。
- 不确定结果传给主对话模型时必须明确标记，避免被改写成确定事实。

## Multiple Images

- 默认每条消息最多处理四张图片。
- Lens 以每张唯一图片为单位执行，默认并发上限为二。
- Qwen 只调用一次，并同时接收最多四张图片及各自 Lens 结果。
- 图片编号严格对应 OneBot 消息段顺序。
- 一张失败不影响其他图片。
- 重复图片只消耗一次 Lens 查询，但保留所有原始位置。
- exact 和 Web 回退绑定到具体图片编号。
- 超出上限的图片保留普通消息标记，但不进入视觉调用。

## Time Budget

单图或双图消息：

- Lens `all` 软目标：20 秒；最长等待：35 秒。
- Qwen 主调用上限：20 秒。
- 主链软目标：25 秒。
- 含条件回退的整体硬截止：50 秒。

Lens 主阶段最迟在第 35 秒结束，以便给 Qwen 保留至少 15 秒。Qwen 的 20 秒组件上限仍受消息级 50 秒硬截止约束。

三图或四图消息：

- Lens 并发上限仍为二。
- 整体硬截止：70 秒。
- Lens 主阶段最迟在第 50 秒结束；未完成图片标记为 Lens 不可用，并为一次多图 Qwen 保留 20 秒。

规则：

- 组件超时都受消息级绝对截止时间约束，不能简单相加。
- 已完成结果必须保留；单个任务超时不能清空其他结果。
- 截止时取消未完成回退，并使用已有 Lens 和 Qwen 结果生成上下文。
- Cache 命中路径不等待外部服务。

## Cache

缓存按阶段拆分。

### Per-Image Cache

键使用规范化图片 SHA-256，保存：

- Lens `all` 规范化结果；
- 条件 exact 结果；
- 与图片直接相关的来源信息。

不保存：

- 原始图片字节；
- Base64；
- 未脱敏 QQ URL；
- 临时公开 URL；
- 完整第三方原始响应。

### Combined Qwen Cache

键包含：

- 有序图片哈希列表；
- 规范化用户问题；
- 有界聊天上下文的摘要哈希；
- 视觉提示词版本；
- 模型名；
- 输出 schema 版本。

相同图片但不同问题可以复用 Lens 缓存，但是否复用 Qwen 结果由组合键决定。

### In-Flight Coalescing

同一进程中对相同图片哈希的并发 Lens 请求合并为一个任务。群聊重复发送相同图片时，后续请求等待同一结果，不重复消耗 SerpApi 次数。

## Image URL Strategy

### Default

直接使用 QQ 原始 URL。生产实测中的真实 QQ 图片均可被 SerpApi Lens 读取。

### Optional Temporary Publisher

临时发布回退默认关闭：

```dotenv
VISION_TEMP_PUBLISHER_ENABLED=false
```

关闭时，QQ URL无法被 Lens 读取则跳过 Lens，由 Qwen 直接看已经下载的图片。缺少 HTTPS、域名、R2 或临时发布配置不得禁用整个识图功能。

未来启用时：

- 使用服务器公网 IP和 Let’s Encrypt IP 证书提供 HTTPS。
- 地址形如 `https://<public-ip>/vision-temp/<random-token>`。
- 只允许 `GET` 和 `HEAD`。
- 不提供任意 URL代理或任意文件读取。
- 随机令牌有效期默认为五分钟。
- 正常流程完成后立即删除，后台清理超过十分钟的遗留图片。
- 日志不得记录完整临时 URL。

本设计不要求首版同时部署该 HTTPS 回退。

## Dynamic Media

GIF 和视频保留独立动态媒体描述路径：

- Qwen 客观描述场景、文字和动作。
- 默认关闭 thinking。
- 首版不对视频帧执行 Lens-first 身份搜索。
- 动态媒体失败不影响同消息中的静态图片结果。

## Configuration

建议配置如下：

```dotenv
VISION_MODEL_ENABLED=true
VISION_MODEL_API_BASE=https://your-vision-provider.example/v1
VISION_MODEL_API_KEY=replace-with-vision-api-key
VISION_MODEL_NAME=replace-with-vision-model
VISION_MODEL_ENABLE_THINKING=false
VISION_MODEL_TIMEOUT_SECONDS=20

VISION_PIPELINE_TIMEOUT_SECONDS=50
VISION_PIPELINE_MULTI_TIMEOUT_SECONDS=70
VISION_PIPELINE_MAX_IMAGES=4
VISION_PIPELINE_MAX_DOWNLOAD_BYTES=10485760
VISION_PIPELINE_MAX_IMAGE_PIXELS=20000000
VISION_PIPELINE_MODEL_MAX_EDGE=1600
VISION_PIPELINE_CACHE_TTL_SECONDS=86400

SERPAPI_API_KEY=replace-with-serpapi-key
SERPAPI_LENS_ENABLED=true
SERPAPI_SEARCH_ENABLED=true
SERPAPI_LENS_TIMEOUT_SECONDS=35
SERPAPI_POLL_INTERVAL_SECONDS=0.75
SERPAPI_LENS_CONCURRENCY=2
SERPAPI_EXACT_FALLBACK_ENABLED=true
SERPAPI_WEB_FALLBACK_ENABLED=true
SERPAPI_MAX_EXACT_FALLBACKS_PER_MESSAGE=2
SERPAPI_MAX_WEB_FALLBACKS_PER_MESSAGE=2

VISION_TEMP_PUBLISHER_ENABLED=false
VISION_TEMP_PUBLIC_BASE_URL=
VISION_TEMP_URL_TTL_SECONDS=300
```

`type=all`、`async=true` 和 `auto_crop=false` 是实现默认值，不需要全部暴露为环境变量。异步请求省略 `no_cache` 参数，以使用 SerpApi 默认缓存行为。

旧 R2 配置不再是启动条件。配置解析可暂时容忍旧变量，但运行时不要求 R2 凭据。移除 R2 后若没有其他 boto3 用途，可一并删除 boto3 依赖。

## Observability

追踪和指标记录：

- 图片数量、去重后数量和规范化尺寸；
- 下载与预处理耗时；
- 每张图 Lens 提交、终态、耗时和结果数量；
- SerpApi 缓存状态；
- Qwen 主调用与复判耗时；
- exact 和 Web 回退原因与次数；
- 单图缓存、组合缓存和并发合并命中；
- 总耗时、超时和取消阶段；
- 多图中失败的具体图片编号。

不得记录：

- API Key 或 Authorization；
- 图片字节或 Base64；
- 完整 QQ URL查询参数；
- 完整临时公开 URL；
- 不必要的完整第三方响应。

增加一个手动生产探针，用真实密钥测试 DNS、TLS、Lens `all`、轮询终态、Qwen 和脱敏日志。探针不进入常规 CI，也不输出密钥和完整图片 URL。

## Testing

### Unit Tests

覆盖：

- 下载限制、格式魔数、方向、尺寸和规范化哈希；
- Lens `type=all` payload、异步轮询和结果解析；
- SerpApi `Success`、`Cached`、`Error`、长期 `Processing` 和网络超时；
- 异步请求省略 `no_cache`，且不会发送 `no_cache=true`；
- Lens 失败后 Qwen 直接看图；
- Qwen 结构化结果解析；
- `needs_exact` 和 `needs_web` 条件回退；
- 每条消息最多一次复判；
- 阶段部分成功不被其他失败清空；
- 单图和多图绝对截止时间；
- 四图顺序、并发二、重复图去重和位置恢复；
- 单图缓存、组合缓存、版本失效和 in-flight 合并；
- 临时发布关闭时不影响启动；
- URL、Base64 和密钥脱敏。

### Service Tests

覆盖：

- 未触发回复的图片不调用识图；
- 私聊和明确寻址的群图片调用识图；
- 多图上下文按顺序传给主模型；
- 不确定结果不会在 Vision Context 中伪装成确定身份；
- Lens、Qwen 或缓存失败保留文本回复能力；
- 回复图片和视觉跟进仍使用正确会话范围。

### Real Evaluation

使用 20 到 50 张不含隐私的人工标注图片，覆盖：

- 动漫和游戏角色；
- 低清头像和局部裁剪；
- 表情包与梗图；
- 海报和 OCR 密集截图；
- 作品相似但角色不同的干扰图；
- 同消息多图比较；
- 普通真人；
- AI 图、同人图和 cosplay。

记录：

- 人物或来源正确率；
- 明显误认数；
- 不确定比例；
- P50、P90 和 P95；
- 主链、exact 回退和 Web 回退占比；
- SerpApi 每张冷图平均消耗；
- 缓存命中后的实际耗时。

三张生产测试图只是方向验证，不能代替正式评估集。

## Migration

1. 将 SerpApi Lens 客户端改为 `type=all` 异步提交和轮询。
2. 修复部分成功语义，不让单个搜索失败清空其他结果。
3. 将 VisualAnalyzer 改为接收原图和每图 Lens 结果的一次综合调用。
4. 删除固定的前置视觉候选调用、Lens 候选抽取调用和确定性 resolver 主路径。
5. 加入 Qwen 请求的条件 exact/Web 回退和最多一次复判。
6. 将默认图片上限改为四张，并实现 Lens 并发二和单次多图 Qwen。
7. 重用现有图片规范化和哈希缓存，新增组合 Qwen 缓存和 in-flight 合并。
8. 移除 R2 完整性启动检查，使临时发布成为可选功能。
9. 保留服务层 vision 协议和现有触发策略，更新 Vision Context 格式。
10. 更新 `.env.example`、README、部署文档、单元测试和手动生产探针。
11. 部署时先保持新识图开关关闭，运行生产探针和人工评估集后再启用。

## Security And Privacy

用户已允许对进入识图流程的图片调用 SerpApi/Google Lens。该允许不扩大触发范围：机器人忽略的群消息图片不得上传或搜索。

继续执行：

- API Key 只存在于服务器 `.env`。
- 不提交 QQ 原始图片、测试图片、搜索原始响应和临时发布文件。
- 不在日志中保留可复用的 QQ URL查询参数。
- 外部请求使用 TLS、超时、重定向限制和大小限制。
- Qwen 不能要求程序抓取任意生成 URL。
- 临时发布关闭时不开放任何新公网端点。

## Success Criteria

- 常见单图走 `Lens all -> one Qwen` 两步主链。
- 三张已验证生产样本保持 3/3，不依赖固定 exact 或 Web 调用。
- thinking 默认关闭。
- 一至两张图软目标 25 秒，疑难回退不超过 50 秒。
- 三至四张图不超过 70 秒。
- 同一消息最多处理四张图并支持跨图问题。
- Lens、Qwen 或单图失败不清空其他已完成结果。
- QQ URL可用时无需 R2、域名或临时 HTTPS 服务。
- 临时发布关闭时识图仍可正常启动和降级。
- 重复图片命中哈希缓存且不重复消耗 SerpApi。
- 追踪能够解释时间花在哪个阶段，同时不泄露图片、URL或密钥。
