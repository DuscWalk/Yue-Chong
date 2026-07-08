# Vision Media Search Design

## Goal

在已存在的双模型链路上扩展视觉上下文：DeepSeek 继续负责最终对话，Qwen 视觉模型只在机器人已经决定回复后，对聊天里的图片、表情包、动图或视频生成参考摘要，并在需要识别来源或梗图时补充联网/图搜结果。

## Scope

- 支持 OneBot `image` 段里的公网 HTTP(S) 图片 URL。
- 支持 OneBot `video` 段里的公网 HTTP(S) 视频 URL。
- 将 URL 后缀明显是动态媒体的图片段（例如 `.gif`、`.mp4`、`.mov`、`.webm`）按动态媒体传给视觉模型。
- 对图片启用 Responses API 的 `image_search` 和 `web_search` 工具，生成短搜索摘要。
- 对视觉 Chat Completions 调用开启 `enable_thinking=true`，以覆盖复杂图片、动图和视频理解。
- 任一视觉或搜索调用失败时静默降级，不阻塞主回复。

## Architecture

`qq_rolebot/message_segments.py` 负责从 OneBot 消息段里抽取媒体 URL，并按 `image` / `video` 分类。`qq_rolebot/vision_client.py` 负责两类外部调用：Chat Completions 用于图片/视频摘要，Responses API 用于图片搜索/联网补充。`qq_rolebot/service.py` 只接收最终拼好的 `Vision Context` 文本，把它附加到主模型系统上下文里。

## Data Flow

1. 插件收到消息后提取文本摘要和媒体 URL。
2. 策略层先判断是否要回复。
3. 如果决定回复且存在媒体 URL，调用视觉客户端。
4. 视觉客户端先用 Chat Completions 摘要图片/动态媒体，再按配置对图片调用 Responses API 工具。
5. 服务层把可用摘要合并成 `Vision Context`，DeepSeek 基于该上下文生成最终回复。

## Configuration

- `VISION_MODEL_ENABLE_THINKING=true`：默认开启视觉模型思考。
- `VISION_MODEL_ENABLE_SEARCH=true`：默认开启视觉联网/图搜。
- `VISION_MODEL_VIDEO_FPS=2`：默认视频抽帧频率。
- 继续沿用 `VISION_MODEL_ENABLED`、`VISION_MODEL_API_BASE`、`VISION_MODEL_API_KEY`、`VISION_MODEL_NAME`、`VISION_MODEL_TIMEOUT_SECONDS`、`VISION_MODEL_MAX_IMAGES`。

## Testing

- 媒体段提取测试覆盖图片、视频、GIF URL、非 HTTP(S) URL。
- 视觉客户端测试覆盖 `image_url`、`video_url`、`enable_thinking`、Responses API 工具 payload 和失败降级。
- 服务层测试覆盖“未触发回复不调用视觉模型”和“触发回复时把视觉/搜索上下文传给 DeepSeek”。
- 插件 smoke test 覆盖 OneBot 图片/视频段进入 `IncomingMessage`。
