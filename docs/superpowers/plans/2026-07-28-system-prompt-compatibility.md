# System Prompt Compatibility Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 Chat Completions 中继中将 `developer` 归一为 `system`，并按开关替换三条 Claude Code 固定系统提示词文本。

**Architecture:** 只修改 `_build_workbuddy_relay_body()` 的消息处理路径。请求已被深拷贝，因此先将 developer 角色改为 system，再复用已有的 system 文本替换函数，不会改动调用方请求。默认替换规则只在开关开启、且用户没有配置自定义 JSON 时启用。

**Tech Stack:** Python 3、unittest、pytest、现有设置存储。

---

## File Structure

- `src/modules/proxy_server.py`: 角色归一化、默认替换表、请求元数据和数量日志。
- `tests/test_proxy_image.py`: 为现有请求体构造函数增加单元测试。
- `docs/codex-claude-message-compatibility-notes.md`: 记录当前实际规则和范围。

### Task 1: developer 角色归一化

**Files:**
- Modify: `tests/test_proxy_image.py`
- Modify: `src/modules/proxy_server.py`

- [ ] **Step 1: 写失败测试**
  在 `TestBuildWorkbuddyRelayBody` 添加 `test_developer_role_is_normalized_to_system`。请求含一条 `developer` 和一条 `user` 消息；断言上游第一条角色为 `system`、内容保持为 `developer instructions`、原请求仍为 `developer`，以及 `meta["developer_roles_normalized"] == 1`。

- [ ] **Step 2: 确认测试失败**
  运行 `python -m pytest tests/test_proxy_image.py::TestBuildWorkbuddyRelayBody::test_developer_role_is_normalized_to_system -v`。预期失败，因为当前没有角色转换或计数元数据。

- [ ] **Step 3: 实现最少代码**
  在 `_replace_system_prompt_sensitive_words()` 前新增 `_normalize_developer_messages_to_system(messages: list) -> int`。函数只遍历 dict 消息，将 `role == "developer"` 改为 `"system"` 并返回计数。`_build_workbuddy_relay_body()` 深拷贝 messages 后，先调用该函数，再调用已有替换函数；将计数加入 `meta` 的 `developer_roles_normalized`，日志只写计数。

- [ ] **Step 4: 确认测试通过**
  再运行同一条 pytest 命令。预期 PASS。

- [ ] **Step 5: 提交**
  执行 `git add src/modules/proxy_server.py tests/test_proxy_image.py`，随后执行 `git commit -m "feat(proxy): normalize developer messages to system"`。

### Task 2: 三条默认系统提示词兼容规则

**Files:**
- Modify: `tests/test_proxy_image.py`
- Modify: `src/modules/proxy_server.py`

- [ ] **Step 1: 写失败测试**
  从 `unittest.mock` 导入 `patch`。在 `TestBuildWorkbuddyRelayBody` 添加测试：mock `load_setting` 让 `system_prompt_sensitive_enabled` 为 `True` 且 `system_prompt_sensitive_replacements` 为空。输入 developer 内容包含 `You are Claude Code, Anthropic's official CLI for Claude.`、`PRs` 和 `github.com/anthropics/claude-code/issues`；断言输出 system 内容分别变为 `You are a Claude agent, built on Anthropic's Claude Agent SDK.`、`pull requests` 和 `github.com/anthropics/claude-code`。断言 user 内容中的 `PRs` 不变，替换计数为 3。另加开关为 `False` 的测试，断言 system 内容与计数都不变。

- [ ] **Step 2: 确认测试失败**
  运行 `python -m pytest tests/test_proxy_image.py::TestBuildWorkbuddyRelayBody -v`。预期新增的默认规则测试失败，因为当前空配置没有规则。

- [ ] **Step 3: 实现默认规则和配置覆盖**
  在 `_SYSTEM_PROMPT_REPLACEMENT_CACHE` 前新增 `DEFAULT_SYSTEM_PROMPT_COMPATIBILITY_REPLACEMENTS`，包含精确映射：`PRs` 到 `pull requests`；issues URL 到项目主页 URL；Claude Code CLI 身份句到 Claude Agent SDK 身份句。将 `_load_system_prompt_sensitive_replacements()` 的替换配置默认值由 `"[]"` 改为 `""`。开关开启时，空配置或无效 JSON 返回默认规则副本；有效 JSON 完全覆盖默认规则；开关关闭时返回空列表。

- [ ] **Step 4: 确认测试通过**
  再运行 `python -m pytest tests/test_proxy_image.py::TestBuildWorkbuddyRelayBody -v`。预期 PASS，并确认替换只影响 system 与归一化后的 developer。

- [ ] **Step 5: 回归与提交**
  运行 `python -m pytest tests/test_proxy_image.py -v`，预期 PASS。执行 `git add src/modules/proxy_server.py tests/test_proxy_image.py`，再执行 `git commit -m "feat(proxy): add system prompt compatibility replacements"`。

### Task 3: 文档和完整验证

**Files:**
- Modify: `docs/codex-claude-message-compatibility-notes.md`

- [ ] **Step 1: 更新说明**
  修改文档以说明当前项目采用的规则：Chat 中继把 `developer` 改为 `system`；当 `system_prompt_sensitive_enabled=True` 时使用三条默认替换；`system_prompt_sensitive_replacements` 的有效 JSON 可以覆盖默认规则；默认开关关闭；user、assistant、tool 消息不修改；本计划不增加 Responses API 转换。

- [ ] **Step 2: 完整验证**
  运行 `python -m pytest -v`，预期 PASS。若外部依赖使任何测试失败，记录原因，并确保 `tests/test_proxy_image.py` 全绿。运行 `git diff --check`，预期无空白错误。运行 `git status --short`，确认执行前的未跟踪文件没有被删除或覆盖。

- [ ] **Step 3: 提交文档**
  执行 `git add docs/codex-claude-message-compatibility-notes.md`，再执行 `git commit -m "docs: document system prompt compatibility behavior"`。

## Self-Review

- Task 1 覆盖 developer 到 system、原请求不变和计数。
- Task 2 覆盖三条默认替换、关闭开关与 user 不受影响。
- Task 3 覆盖文档、完整测试和工作区检查。
- 不增加 Responses 入口、不增加 Web UI、不记录完整提示词。
