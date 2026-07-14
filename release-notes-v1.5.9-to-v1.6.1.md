# antigravity-tools 更新日志（v1.5.9 → v1.6.1）

> 汇总 v1.5.9 发布后至 v1.6.1 的所有未发布更新。
> 包含 2026-07-01（v1.6.0）和 2026-07-02（v1.6.1）两批改动。

---

## v1.6.0（2026-07-01）

### 1. 多模态图片支持
- **glm-5.1/5.2 支持图片输入**
  - `MODEL_SUPPORTS_IMAGES` 字典中 `glm-5.1` / `glm-5.2` 从 `False` 改为 `True`
  - `/v1/models` 接口返回 `supportsImages: true`，WorkBuddy 客户端识别为支持图片
  - 不再拦截 glm-5.1/5.2 的图片请求，不再返回 `model_image_not_supported` 错误

### 2. 上游 400 错误处理优化
- **400 错误日志透传**
  - 上游返回 400 时，保持客户端返回 502（避免 WorkBuddy 重新登录）
  - 在代理日志面板写入原始上游 400 错误内容（`event="upstream_error"`），方便排查
- **400 空 body / input length too long 换 Key 重试**
  - 上游偶发 400 空 body 时，先尝试 AI 摘要压缩，压缩失败则换 Key 重试
  - 连续 2+ 个 Key 都失败才返回"上下文过长"提示
  - 400 空 body 最终简化：不再尝试压缩，直接换 Key，所有 Key 失败后返回 `502 上游返回为空，请重试`
- **"400 canceled" 问题修复**
  - 处理 400 空 body 耗时过长导致 WorkBuddy 客户端超时 abort
  - 简化后处理秒级完成，不再触发客户端取消

### 3. 查分接口新格式兼容
- 上游返回结构变更：`accounts` 字段迁移到 `data.Response.Data.Accounts`
- 兼容新旧两种格式 + 新旧字段名：`cycle_remain` → `CycleCapacityRemain`

### 4. 上游 Key 使用状态可视化
- 正在使用的 Key 在 UI 中用浅绿色标记，并显示 `🟢 使用中(N)`
- 使用中的 Key 置顶排序

### 5. 积分实时扣除
- 每次请求完成后立即从积分余额扣除本次消耗
- 5 分钟定时查分用真实值修正，避免累积误差

### 6. UI 修复
- **定时刷新不从文件重载**：服务运行中刷新表格时直接读内存，避免覆盖实时积分
- **QColor UnboundLocalError 修复**：删除局部 import，统一使用顶部导入
- **浅色模式深色背景修复**：多个页面的硬编码深色背景改为透明/rgba，跟随主题

### 7. 流式响应处理
- **删除流中超长检测**：不再扫描回复文本关键词提前终止流，完全信任上游返回
- 保留首 chunk 延迟首输检测

### 8. 诊断增强
- **11133 错误诊断增强**：select_key 返回 None 时增加详细诊断日志（总计/active/cooldown/excluded/model_cooldown）
- 通用 400 日志增加 `has_image`、messages 数量、`stream_options_removed` 状态

### 9. 验证
- 图片转发功能完整测试：8x8/200x200/500x500 红色 PNG + 200K tokens 长上下文均成功

---

## v1.6.1（2026-07-02）

### 1. 请求头白名单制
- 主请求头和摘要请求头统一：
  - 旧：`Content-Type + Authorization + X-Request-ID`
  - 新：`Content-Type + Accept + Authorization`
- 去掉 `X-Request-ID`（trace 头不需要发给上游），新增 `Accept: application/json, text/event-stream`

### 2. 请求体白名单制
- 旧：原样透传 `request_data`（客户端发啥转啥）
- 新：只保留上游已知接受的字段，其余删除并记日志
- 白名单字段（20 个）：
  - `model, messages, stream, stream_options`
  - `temperature, top_p, max_tokens, presence_penalty, frequency_penalty, stop, tools, tool_choice, response_format`
  - `parallel_tool_calls, seed, user, metadata, logprobs, top_logprobs, n`

### 3. 图片格式归一化
- 新增 `_normalize_messages_for_upstream()` 函数
- 转发前将 WorkBuddy 的 `input_image` / `image` 格式转换为标准 OpenAI `image_url` 格式
- `image_blob_ref` 和无法提取的格式保持原样透传（不替换为文本占位）
- 日志新增 `img_normalized=N` 字段统计归一化数量

### 4. 历史图片替换为文本描述
- 新增 4 个辅助函数：
  - `_extract_message_text()`：从 content 提取纯文本
  - `_find_following_assistant_description()`：取图片 user 消息后最近 assistant 回复作为描述
  - `_part_is_image()`：判断 content part 是否图片
  - `_strip_history_images_with_description()`：只保留最后一条 user 消息的图片，历史图片替换成后续 assistant 回复摘要
- 描述来源：上一轮 assistant 回复文本（最多 1200 字，超长截断）
- 无后续 assistant 回复时使用兜底文案

### 5. 请求体校验增强
- `model` 缺失时 `auto` 默认值写回 `request_data`
- `messages` 严格校验：`isinstance(messages, list) and messages`，不合法返回 400

### 6. CORS 预检放宽
- `Access-Control-Allow-Headers` 从 `Authorization, Content-Type, Accept` 改为 `*`
- 入站允许客户端发送任意头，出站仍由白名单丢弃

### 7. UI 状态检测请求头统一
- `src/ui/pages/api_proxy.py` 的 `check_status` 请求去掉 `X-Request-ID`，补 `Accept`，与主链路一致

### 8. 旧图片拦截逻辑移除
- 注释 `_latest_user_message_index()` / `_message_has_image()` / `_strip_historical_images_for_text_model()` 三个函数
- 移除"模型不支持图片 → 400 拒绝 / 剥离历史图片"的旧逻辑
- 现在所有图片默认透传，由上游判断模型能力

---

## 涉及文件

- `src/modules/proxy_server.py`（主逻辑，Win + Mac 同步）
- `src/ui/pages/api_proxy.py`（UI，Win + Mac 同步）
- `src/ui/pages/accounts.py`（浅色模式修复，v1.6.0）
- `src/ui/pages/checkin.py`（浅色模式修复，v1.6.0）
- `src/ui/theme.py`（浅色模式修复，v1.6.0）

## 回滚信息

- v1.6.1 改动：代码中搜索 `[v1.6.1-CHANGE]` 和 `[v1.6.1-fix]` 标记，按 `[ROLLBACK]` 注释恢复
- v1.6.0 改动：详细回滚说明见 `2026-07-01.md` 工作日志

## 验证状态

- 语法检查通过（`py_compile`）
- Windows / Mac 源码同步（`diff` 无差异）
- 图片历史描述逻辑已用本地测试用例验证
- 待用户实际测试图片识别功能确认效果
