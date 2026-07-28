# Codex 与 Claude 消息兼容处理说明

本文记录从 `cv-switch-web` 项目核实到的代理行为，以及在 `antigravity-tools` 中的实际实现。

## antigravity-tools 当前实现

本项目在 `_build_workbuddy_relay_body()` 的 Chat Completions 中继路径上实施了以下兼容处理：

### 1. developer 角色归一化

Chat 中继始终将 `developer` 角色转为 `system`，内容不变。转换在深拷贝后的消息列表上进行，不影响调用方的原始请求。每个请求的 `meta["developer_roles_normalized"]` 记录被转换的消息数量。

### 2. 系统提示词兼容替换（可配置开关）

当设置 `system_prompt_sensitive_enabled=True`（默认关闭）时，代理会对 system 消息（含归一化后的 developer）执行关键词替换。替换仅影响 role 为 `system` 的消息，**user、assistant、tool 消息不做任何修改**。

默认替换规则（`system_prompt_sensitive_replacements` 为空时自动启用）：

| 原文 | 替换为 |
| --- | --- |
| `You are Claude Code, Anthropic's official CLI for Claude.` | `You are a Claude agent, built on Anthropic's Claude Agent SDK.` |
| `PRs` | `pull requests` |
| `github.com/anthropics/claude-code/issues` | `github.com/anthropics/claude-code` |

**配置覆盖**：在设置中填写有效 JSON（如 `[{"key": "PRs", "value": "change requests"}]`）会完全覆盖默认规则，不再使用上述三条默认替换。

### 3. 不在范围内的功能

- 不增加 Responses API 转换。
- 不记录完整系统提示词。
- 不修改 user、assistant、tool 消息。

## Codex 请求数据流

Codex CLI 使用 Responses API。若上游仅支持 OpenAI Chat Completions，需要按下面的流程转换：

```text
Codex Responses 请求
  instructions + input + tools + model
        |
        v
代理转换
  instructions -> system message
  input -> messages
  Responses 工具 -> Chat tools
  非 GPT 模型：developer -> system
        |
        v
上游 /chat/completions
```

原项目的参考位置：

- `backend/src/routes/codexProxy.ts` 的 `handleCodexResponses()`：接收请求并发送至上游。
- `responsesToChat()`：构造 Chat Completions 请求体。
- `inputToMessages()`：将 Responses 的 `instructions` 和 `input` 转为 `messages`。

## 建议保留的 Codex 转换

### 1. instructions 转 system

`instructions` 是 Codex 的顶层指令。转为 Chat Completions 时，应保留原文并创建：

```json
{ "role": "system", "content": "<instructions 原文>" }
```

不要替换、删减或拼接指令文本。

### 2. input 转 messages

常见的转换规则：

| Responses 输入 | Chat Completions 输出 |
| --- | --- |
| 字符串 `input` | 一个 `user` message |
| `type: "message"` | 保留角色，转换其内容为文本 |
| `type: "reasoning"` | 合并到待发送的 assistant message 的 reasoning 字段（仅上游支持时） |
| `function_call` / `custom_tool_call` / `tool_search_call` | 转为 assistant 的 `tool_calls` |
| 对应的 `*_output` | 转为 `tool` message |

对多段内容，应优先支持 `text`、`input_text`、`output_text` 等文本字段。图片、文件等非文本内容不能静默丢弃；若当前上游不支持，应返回明确的兼容性错误。

### 3. developer 角色兼容

部分非 OpenAI 上游不支持 `developer` role。可以按模型能力决定是否降级：

```text
上游模型支持 developer role：保留 developer
上游模型不支持 developer role：developer 改为 system，内容不变
```

这是角色兼容，不是安全过滤。请将规则做成“按 Provider 或模型能力配置”，不要只用模型名称前缀判断。模型名判断容易在第三方模型别名下出错。

### 4. 工具定义兼容

Responses API 的工具格式和 Chat Completions 不完全相同。迁移时需要：

- 将标准 function 工具转为 Chat 的 `tools[].function`。
- 将 custom 或 tool search 工具映射为普通 function，同时保留足够的名称、说明和参数信息。
- 记录工具名称映射，用于把上游工具调用回复还原为 Responses 格式。

工具 JSON Schema 若遇到上游不支持的字段，应基于上游文档做最小兼容转换，并记录被移除的字段。不要无声修改工具描述中的文字。

## 响应侧处理

Chat Completions 的回复需要还原为 Codex Responses 格式：

- assistant 正文 -> `output` 内的 `message` 项。
- 上游 reasoning 字段 -> `reasoning` 项。
- 工具调用 -> `function_call` 项。
- 使用量 -> Responses 的 usage 字段。

有的上游会把思考内容放在 `<think>...</think>` 中。原项目会将它拆为 reasoning，并从最终显示正文移除。这是显示格式兼容；使用前应确认这不会破坏上游协议或用户需要的原始输出。

## Claude 的历史处理

原项目的 Claude 代理在 `anthropicToChat()` 中曾对 system prompt 做过以下替换：

- 将 `PRs` 改为 `pull requests`。
- 将一个 GitHub issues URL 改为项目主页 URL。
- 将 Claude Code 的身份句改为另一句身份文本。

提交说明将该做法称为 `content filter bypass`，目的是绕过某个上游服务对特定系统提示词组合的误拦截。

### antigravity-tools 中的采纳

本项目**有条件地**采纳了这三条替换规则，但做了重要的安全包装：

1. **默认关闭**：`system_prompt_sensitive_enabled` 默认为 `False`，不做任何替换。
2. **可配置覆盖**：用户可通过 `system_prompt_sensitive_replacements` 提供自定义 JSON 完全替代默认规则。
3. **限定范围**：替换仅影响 system/developer 消息，user、assistant、tool 消息不被修改。
4. **审计友好**：每次请求记录替换计数 `meta["system_prompt_sensitive_replaced"]`。

风险提示依然有效：此功能改变了系统提示词，用户应在明确需要时才启用，并理解上游审核规则可能随时变化。

## 推荐实现边界

建议把转换拆成独立模块，方便测试：

```text
responsesToChat(request, capabilities) -> chatRequest
chatToResponses(chatResponse, requestContext) -> responsesResponse
```

`capabilities` 至少应描述：

- 是否支持 `developer` role。
- 是否支持 reasoning 字段。
- 是否支持图片和其他多模态内容。
- 是否支持并行工具调用。
- 最大输出 token 字段名称。

`requestContext` 应保存工具名映射、原始模型标识及流式转换所需状态。

## 实现检查清单

- [x] Chat 中继中 `developer` 角色始终转为 `system`，内容不变。
- [x] 原始请求不被修改（深拷贝后操作）。
- [x] 系统提示词替换默认关闭（`system_prompt_sensitive_enabled=False`）。
- [x] 开启后使用三条默认替换规则；用户 JSON 配置可覆盖。
- [x] user、assistant、tool 消息不被替换。
- [x] 每次请求记录 `developer_roles_normalized` 和 `system_prompt_sensitive_replaced` 计数。
- [x] 日志不记录完整系统提示词或用户内容。
- [ ] Responses API 转换（不在本次范围）。

## 来源

调查项目：`D:\Code\Git\cv-switch-web`

- Codex 转换：`backend/src/routes/codexProxy.ts`
- Claude 转换：`backend/src/routes/claudeProxy.ts`
- Claude 历史说明：提交 `00497ff` 及 `docs/claude-code-content-filter-fix.md`
- Codex developer role 转换引入：提交 `ff71c23`
