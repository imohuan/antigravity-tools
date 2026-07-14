# Antigravity Tools v1.6.1 更新日志

## 📌 版本跨度
v1.5.9 → v1.6.1（含 v1.6.0 + v1.6.1 两版合并发布）

---

## 🔥 重点更新

### 图片识别功能修复（v1.6.1 核心改动）
- **修复 WorkBuddy 发图片"读不了图"的问题**
  - 根因：WorkBuddy 客户端发送的图片格式是 `input_image`（非标准 OpenAI 格式），上游 copilot 在纯 API 模式下不识别
  - 修复：代理转发前自动将 `input_image` / `image` 格式归一化为标准 `image_url` 格式
  - 日志新增 `img_normalized=N` 字段，可确认归一化是否生效

### 历史图片智能替换（v1.6.1）
- **多轮对话不再因历史图片导致上下文爆炸**
  - 只保留最后一条用户消息的图片原图
  - 历史消息中的图片自动替换为文本描述
  - 描述来源：上一轮 assistant 的回复内容（零成本，不需要额外请求模型）
  - 无回复记录时使用兜底文案

---

## 🛠 功能改进

### 请求头/请求体白名单制（v1.6.1）
- 请求头改为白名单制：只发 `Content-Type` + `Accept` + `Authorization`，去掉 `X-Request-ID`
- 请求体改为白名单制：只转发上游已知接受的 20 个字段，其余字段删除并记日志
- 防止客户端未知字段导致上游 400 错误

### CORS 预检放宽（v1.6.1）
- `Access-Control-Allow-Headers` 改为 `*`
- 入站允许客户端发送任意头，出站仍由白名单过滤

### glm-5.1/5.2 图片支持（v1.6.0）
- `MODEL_SUPPORTS_IMAGES` 中 glm-5.1/5.2 改为 `True`
- `/v1/models` 接口返回 `supportsImages: true`
- 不再拦截这两个模型的图片请求

### 旧图片拦截逻辑移除（v1.6.1）
- 移除"模型不支持图片 → 400 拒绝 / 剥离历史图片"的旧逻辑
- 现在所有图片默认透传，由上游判断模型能力

---

## 🐛 Bug 修复

### 上游 400 错误处理优化（v1.6.0）
- **400 空 body**：直接换 Key 重试，所有 Key 失败后返回 `502 上游返回为空，请重试`
- **400 input length too long**：先 AI 摘要压缩 → 压缩失败截断 → 换 Key 重试
- **400 canceled**：处理耗时过长导致客户端超时，简化后秒级完成
- 上游 400 原始错误写入日志面板，方便排查

### 查分接口兼容（v1.6.0）
- 上游返回结构变更：`accounts` → `data.Response.Data.Accounts`
- 兼容新旧两种格式 + 新旧字段名

### 积分实时扣除（v1.6.0）
- 每次请求完成后立即扣除积分
- 5 分钟定时查分修正，避免累积误差

### 定时刷新覆盖问题（v1.6.0）
- 服务运行中刷新表格直接读内存，不从文件重载，避免覆盖实时积分

### 11133 错误诊断增强（v1.6.0）
- select_key 返回 None 时增加详细诊断日志
- 400 排查日志增加图片检测、messages 数量等上下文

### UI 修复（v1.6.0）
- Key 使用中绿色标记 + 置顶排序
- 浅色模式深色背景修复（多个页面）
- QColor 导入错误修复

### 流式响应（v1.6.0）
- 删除流中超长检测，不再提前终止流，完全信任上游返回

---

## 📦 涉及文件
- `src/modules/proxy_server.py`
- `src/ui/pages/api_proxy.py`
- `src/ui/pages/accounts.py`
- `src/ui/pages/checkin.py`
- `src/ui/theme.py`
- `src/ui/components/sidebar.py`
- `src/modules/updater.py`
- `src/VERSION`

---

## 📝 备注
- 本次更新不含破坏性变更，配置和数据兼容 v1.5.9
- 如遇问题可通过代码中 `[v1.6.1-CHANGE]` / `[v1.6.1-fix]` 标记逐项回滚
