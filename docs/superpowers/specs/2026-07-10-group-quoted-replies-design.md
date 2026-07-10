# Group Quoted Replies Design

## Goal

让机器人在群聊中发送普通回复时，使用 QQ 的引用回复能力引用触发消息，并 `@` 该消息发送者。

当一次逻辑回复包含文本、图片或表情包等多条独立消息时，只允许第一条实际发送的消息携带引用和 `@`。

## Current Behavior

- 入站消息已经能够识别 OneBot `reply` 消息段，并判断用户是否回复机器人。
- 用户直接 `@` 或回复机器人后，会为同一群、同一用户开启追问窗口。
- 追问窗口默认持续 90 秒；窗口内消息仍需包含问号或 `FOLLOWUP_TRIGGER_KEYWORDS` 才会触发回复。
- 出站消息目前通过多次 `bot.send(event, segment)` 发送，不会自动引用触发消息，也不会自动 `@` 发送者。

## Required Behavior

### Group replies with quote and mention

以下群聊回复的第一条有效出站消息使用：

```python
await bot.send(event, segment, reply_message=True, at_sender=True)
```

适用范围包括：

- 直接 `@` 机器人触发的回复；
- 用户左滑回复机器人触发的回复；
- 追问窗口内触发的后续回复；
- 关键词回复；
- 随机回复；
- 管理命令回复；
- 工具直答；
- 其他非复读、非语音的群聊回复。

### Exceptions

以下消息保持普通发送，不引用、不 `@`：

- `OutgoingReply.source == "repeat"` 的群聊复读消息；
- TTS 成功生成后发送的语音消息；
- 所有私聊消息。

### Multi-message replies

`OutgoingReply.messages` 继续按顺序逐条发送。

- 第一条成功渲染出的非空消息携带 `reply_message=True` 和 `at_sender=True`。
- 后续消息使用普通 `bot.send(event, segment)`。
- 无法渲染或为空的消息不消耗“第一条”资格。
- 如果回复来源为 `repeat`，所有消息均普通发送。

例如“文本 + 表情包”应表现为：

1. 文本引用触发消息并 `@` 发送者；
2. 表情包作为下一条普通消息发送。

## Implementation Boundary

只在 NoneBot/OneBot 发送边界实现该行为：

- 保持 `IncomingMessage`、触发决策和模型调用不变；
- 保持 `OutgoingReply` 和 `OutgoingMessage` 数据结构不变；
- 由 `send_outgoing_reply` 根据事件类型和 `OutgoingReply.source` 决定首条发送参数；
- TTS 分支继续直接发送 `record`，因此自然保持不引用、不 `@`。

该方案避免把 QQ 传输细节泄漏到服务层，也不需要新增配置。

## Testing

新增或调整插件测试，覆盖：

- 群聊单条普通回复携带引用和 `@`；
- 群聊“文本 + 图片/表情包”只有第一条携带引用和 `@`；
- 第一项为空或不可渲染时，下一条有效消息获得引用和 `@`；
- 群聊复读不携带引用和 `@`；
- 私聊普通回复不携带引用和 `@`；
- TTS 语音回复不携带引用和 `@`；
- 追问触发继续沿用普通群聊发送路径，因此携带引用和 `@`。

## Non-Goals

- 不改变追问窗口的时长或识别规则；
- 不改变群白名单、启用、静音、关键词、随机概率或复读策略；
- 不把文本和表情包合并成一条 OneBot 消息；
- 不为私聊增加引用回复。
