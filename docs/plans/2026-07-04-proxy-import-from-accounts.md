# Proxy: Import Keys From Accounts (替换手动添加密钥)

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 将 Web UI 代理页的 "添加代理密钥" 手动输入弹窗替换为 "从账号导入"，与桌面 UI 行为对齐——从已有账号的 `api_key`/`auth_token` 自动导入，无需手动输入。

**Architecture:** 新增 API 端点 `POST /proxy/keys/import-from-accounts`，后端直接读取 accounts 数据库获取完整 API Key（不走 `/accounts` 列表接口，因为那个接口截断了 api_key）。前端用 Vue 3 reactive 状态管理导入弹窗，展示账号列表 + 勾选框，已导入的默认勾选。

**Tech Stack:** FastAPI (Python) + Vue 3 CDN (vanilla JS, no build)

---

## 参考：桌面 UI 实现

桌面 UI 的核心逻辑在 `src/ui/pages/api_proxy.py:1220-1261`：

- `ImportFromAccountsDialog` 加载 `load_accounts()` → 过滤有 `api_key.startswith("ck_")` 或 `auth_token` 的账号
- 传入 `existing_api_keys` 集合防重复，已导入行默认勾选 + 灰显
- 导入时优先用 `api_key`，其次 `auth_token`；标签用 `display_name` 或 `uid`；积分从 `acc.quota` 自动填充

---

### Task 1: 新增后端 API 端点 `POST /proxy/keys/import-from-accounts`

**Files:**
- Modify: `web/api/proxy.py`

**Step 1: 添加 ImportFromAccountsRequest 模型和端点**

在 `web/api/proxy.py` 末尾添加：

```python
class ImportFromAccountsRequest(BaseModel):
    uids: list[str]


@router.post("/proxy/keys/import-from-accounts")
def proxy_import_from_accounts(req: ImportFromAccountsRequest):
    """从已有账号导入 API Key 到上游 Key 池"""
    import secrets, datetime as dt

    accounts = load_accounts()
    uid_map = {a.uid: a for a in accounts}

    db = _get_db()
    existing_keys = db.get_upstream_keys()
    existing_api_keys = {k.get("api_key", "") for k in existing_keys}

    imported = 0
    skipped = 0
    for uid in req.uids:
        acc = uid_map.get(uid)
        if not acc:
            skipped += 1
            continue

        # 优先 API Key (ck_xxx)，其次 auth_token
        import_key = acc.api_key if (acc.api_key and acc.api_key.startswith("ck_")) else acc.auth_token
        if not import_key:
            skipped += 1
            continue

        # 去重
        if import_key in existing_api_keys:
            skipped += 1
            continue

        key_data = {
            "key_id": f"ck_{secrets.token_hex(4)}",
            "api_key": import_key,
            "label": acc.display_name or acc.uid,
            "status": "active",
            "used_count": 0,
            "points": f"{acc.quota.credits_remaining:.0f}/{acc.quota.credits_total:.0f}" if acc.quota and acc.quota.credits_total > 0 else "",
            "points_updated_at": "imported" if acc.quota and acc.quota.credits_total > 0 else "",
            "created_at": dt.datetime.now().isoformat(),
        }
        db.add_upstream_key(key_data)
        imported += 1

    return {"success": True, "imported": imported, "skipped": skipped}
```

**Step 2: 添加 import**

在 `web/api/proxy.py` 头部添加：

```python
from src.utils.store import load_accounts
```

**Step 3: 验证端点**

```bash
# 启动 dev server，用 curl 测试
curl -X POST http://localhost:8866/api/proxy/keys/import-from-accounts \
  -H "Content-Type: application/json" \
  -d '{"uids": ["test-uid-1"]}'
```

---

### Task 2: 新增 `POST /proxy/accounts-with-keys` 端点（前端获取可导入账号列表用）

**Files:**
- Modify: `web/api/proxy.py`

**Step 1: 添加端点**

前端需要展示哪些账号可导入、哪些已导入。当前 `/accounts` 接口返回的 `api_key` 被截断（`[:20]+"..."`），无法判断是否已存在。新增一个专用端点：

```python
@router.get("/proxy/accounts-with-keys")
def proxy_accounts_with_keys():
    """返回可用于导入代理 Key 池的账号列表（含完整 api_key 前缀用于匹配）"""
    accounts = load_accounts()
    db = _get_db()
    existing_keys = db.get_upstream_keys()
    existing_api_keys = {k.get("api_key", "") for k in existing_keys}

    result = []
    for acc in accounts:
        import_key = acc.api_key if (acc.api_key and acc.api_key.startswith("ck_")) else acc.auth_token
        if not import_key:
            continue

        is_already_imported = import_key in existing_api_keys
        result.append({
            "uid": acc.uid,
            "nickname": acc.nickname or acc.uid,
            "display_name": acc.display_name or acc.uid,
            "already_imported": is_already_imported,
            "has_api_key": bool(acc.api_key),
            "has_auth_token": bool(acc.auth_token),
            "quota_remaining": acc.quota.credits_remaining,
            "quota_total": acc.quota.credits_total,
        })

    return {"accounts": result}
```

**Step 2: 验证**

```bash
curl http://localhost:8866/api/proxy/accounts-with-keys | python -m json.tool
```

---

### Task 3: 前端 — 替换 "添加代理密钥" 弹窗为 "从账号导入"

**Files:**
- Modify: `web/static/index.html`

**Step 1: 删除旧代码**

删除以下死代码：

**第 672 行**：删除 `showAddKeyModal`, `addKeyLoading`, `addKeyError`, `addKeyForm`
```javascript
// 删除: const showAddKeyModal = ref(false); const addKeyLoading = ref(false); ...
// 替换为: const showImportKeysModal = ref(false); const importKeysAccounts = ref([]); const importKeysLoading = ref(false);
```

**第 704 行**：删除 `addProxyKey()` 函数

**第 485-514 行**：删除整个旧弹窗模板

**第 319 行**：修改按钮
```html
<!-- 旧: @click="showAddKeyModal=true" 文本: "添加" -->
<!-- 新: @click="openImportKeysModal" 文本: "从账号导入" -->
```

**第 710 行的 return**：删除旧变量，添加新变量
```javascript
// 删: showAddKeyModal, addKeyForm, addKeyLoading, addKeyError, addProxyKey
// 加: showImportKeysModal, importKeysAccounts, importKeysLoading, openImportKeysModal, importSelectedKeys
```

**Step 2: 添加新的导入弹窗模板**

在旧弹窗位置（第 485 行之后）替换为：

```html
<Transition name="fade">
  <div v-if="showImportKeysModal" class="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-md"
    @click.self="showImportKeysModal=false">
    <div
      class="bg-surface-container-lowest border border-outline-variant rounded-xl w-full max-w-lg overflow-hidden pro-shadow"
      @click.stop>
      <div class="h-12 border-b border-outline-variant flex items-center justify-between px-md">
        <h3 class="font-headline-sm text-body-md font-semibold text-primary">从账号导入到 Key 池</h3>
        <button @click="showImportKeysModal=false"
          class="w-8 h-8 flex items-center justify-center text-secondary hover:bg-surface-container-low rounded-lg transition-colors"><span
            class="material-symbols-outlined">close</span></button>
      </div>
      <p class="px-md pt-md text-body-sm text-secondary">选择已有账号导入到上游 Key 池。只有含 API Key 的账号才可导入。已导入的会默认勾选。</p>
      <div class="p-lg space-y-md max-h-[60vh] overflow-y-auto">
        <table class="w-full text-body-sm" v-if="importKeysAccounts.length > 0">
          <thead>
            <tr class="border-b border-outline-variant text-secondary">
              <th class="text-left py-sm pr-sm w-12"><input type="checkbox" @change="toggleSelectAllImport" :checked="importAllSelected" class="w-3.5 h-3.5 rounded accent-primary"></th>
              <th class="text-left py-sm pr-sm">昵称</th>
              <th class="text-left py-sm pr-sm">UID</th>
              <th class="text-left py-sm">状态</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="a in importKeysAccounts" :key="a.uid" :class="{'text-outline': a.already_imported}" class="border-b border-outline-variant/50">
              <td class="py-sm pr-sm">
                <input type="checkbox" v-model="a.selected" :disabled="a.already_imported" class="w-3.5 h-3.5 rounded accent-primary">
              </td>
              <td class="py-sm pr-sm">{{a.display_name}}</td>
              <td class="py-sm pr-sm font-label-md text-[11px]">{{a.uid}}</td>
              <td class="py-sm text-[11px]">
                <span v-if="a.already_imported" class="text-secondary">已导入</span>
                <span v-else class="text-[#1e7e34]">{{a.has_api_key ? '有 API Key' : ''}}{{a.has_auth_token ? '有 Token' : ''}}</span>
              </td>
            </tr>
          </tbody>
        </table>
        <p v-else class="text-body-sm text-secondary text-center py-lg">没有可导入的账号</p>
        <div class="flex justify-end gap-sm pt-sm border-t border-outline-variant">
          <button @click="showImportKeysModal=false"
            class="px-3 py-1.5 text-secondary font-label-md text-label-md rounded-lg hover:bg-surface-container-low transition-colors">取消</button>
          <button @click="importSelectedKeys" :disabled="importKeysLoading"
            class="inline-flex items-center gap-xs px-3 py-1.5 bg-primary text-on-primary font-label-md text-label-md rounded-lg hover:opacity-90 transition-opacity disabled:opacity-30"><span
              v-if="importKeysLoading"
              class="spinner inline-block w-3.5 h-3.5 border-2 border-on-primary/30 border-t-on-primary rounded-full"></span>导入选中</button>
        </div>
      </div>
    </div>
  </div>
</Transition>
```

**Step 3: 添加 Vue 响应式状态和函数**

```javascript
// 状态
const showImportKeysModal = ref(false);
const importKeysAccounts = ref([]);
const importKeysLoading = ref(false);
const importAllSelected = ref(false);

// 函数
async function openImportKeysModal() {
  importKeysLoading.value = true;
  showImportKeysModal.value = true;
  const d = await api('/api/proxy/accounts-with-keys');
  if (d && d.accounts) {
    importKeysAccounts.value = d.accounts.map(a => ({
      ...a,
      selected: a.already_imported  // 已导入的默认勾选
    }));
    importAllSelected.value = importKeysAccounts.value.every(a => a.selected || a.already_imported);
  }
  importKeysLoading.value = false;
}

function toggleSelectAllImport(e) {
  const checked = e.target.checked;
  importAllSelected.value = checked;
  importKeysAccounts.value.forEach(a => {
    if (!a.already_imported) a.selected = checked;
  });
}

async function importSelectedKeys() {
  const selected = importKeysAccounts.value.filter(a => a.selected && !a.already_imported);
  if (selected.length === 0) {
    showToast('请选择要导入的账号');
    return;
  }
  importKeysLoading.value = true;
  const r = await fetch('/api/proxy/keys/import-from-accounts', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ uids: selected.map(a => a.uid) })
  });
  const d = await r.json();
  importKeysLoading.value = false;
  if (r.ok) {
    showToast(`成功导入 ${d.imported} 个 Key` + (d.skipped ? `，跳过 ${d.skipped} 个` : ''));
    showImportKeysModal.value = false;
    await loadProxyStatus();
  } else {
    showToast(d.detail || '导入失败', 'error');
  }
}
```

**Step 4: 更新 return 的 bindings**

确保 `return { ... }` 中包含了：
- `showImportKeysModal`, `importKeysAccounts`, `importKeysLoading`
- `openImportKeysModal`, `importSelectedKeys`, `toggleSelectAllImport`
- 移除了旧的 `showAddKeyModal`, `addKeyForm`, `addKeyLoading`, `addKeyError`, `addProxyKey`

---

### Task 4: 验证全流程

**Step 1: 重启 web server**

```bash
cd d:/Code/Learn/antigravity-tools
# 重启服务
```

**Step 2: 手动测试**

1. 打开 web UI → 代理页
2. 确认按钮文字是 "从账号导入"（不是 "添加"）
3. 点击 → 弹窗显示账号列表
4. 已导入账号默认勾选 + 灰显
5. 勾选部分账号 → 点击 "导入选中"
6. 确认 Key 池表格刷新
7. 再次打开弹窗 → 刚导入的账号显示 "已导入"

**Step 3: 回归检查**

- 代理启动/停止正常
- 密钥启用/禁用/删除正常
- 设置页面不受影响
- 账号管理页面不受影响

---

### Task 5: 账号表格补齐 UID / TK / CK / API状态 列

用户反馈 Web UI 账号表格缺少桌面 GUI 中的红框列：UID、TK、CK、API状态。

**Files:**
- Modify: `web/api/accounts.py`
- Modify: `web/static/index.html`

**Step 1: 后端 API 返回额外字段**

修改 `web/api/accounts.py` 中 `list_accounts()`：

```python
result.append({
    "uid": a.uid,
    "nickname": a.nickname or a.uid,
    "platform": a.platform.value,
    "status": a.status.value,
    "plan_type": a.plan_type.value,
    "api_key": a.api_key[:20] + "..." if len(a.api_key) > 20 else a.api_key,
    "has_api_key": bool(a.api_key),
    "auth_token": a.auth_token[:20] + "..." if len(a.auth_token) > 20 else a.auth_token,
    "has_auth_token": bool(a.auth_token),
    "quota_remaining": a.quota.credits_remaining,
    "quota_total": a.quota.credits_total,
    "checked_today": a.checkin.checked_today,
    "streak_days": a.checkin.streak_days,
})
```

**Step 2: 前端表格加列**

修改 `web/static/index.html` 第 133-144 行表头为：

```html
<tr>
  <th class="text-left px-md py-sm w-10">
    <input type="checkbox" @change="toggleSelectAll" :checked="isAllSelected" class="accent-primary w-4 h-4 cursor-pointer">
  </th>
  <th class="text-left px-md py-sm">昵称</th>
  <th class="text-left px-md py-sm">UID</th>
  <th class="text-left px-md py-sm">平台</th>
  <th class="text-left px-md py-sm">积分</th>
  <th class="text-left px-md py-sm">TK</th>
  <th class="text-left px-md py-sm">CK</th>
  <th class="text-left px-md py-sm">API状态</th>
  <th class="text-left px-md py-sm">签到</th>
  <th class="text-left px-md py-sm">状态</th>
  <th class="text-left px-md py-sm">操作</th>
</tr>
```

修改第 147-182 行表格行为：

```html
<tr v-for="a in accounts" :key="a.uid" class="hover:bg-surface-container-low/50 transition-colors">
  <td class="px-md py-sm"><input type="checkbox" v-model="selectedAccounts" :value="a.uid" class="accent-primary w-4 h-4 cursor-pointer"></td>
  <td class="px-md py-sm font-medium text-primary">{{a.nickname}}</td>
  <td class="px-md py-sm font-label-md text-[11px] text-on-surface-variant">{{a.uid}}</td>
  <td class="px-md py-sm text-secondary">{{a.platform}}</td>
  <td class="px-md py-sm">
    <div class="flex items-center gap-sm">
      <div class="w-16 bg-surface-container-low rounded-full h-1.5 overflow-hidden">
        <div class="h-full bg-primary rounded-full transition-all duration-500" :style="{width:a.quota_total>0?(a.quota_remaining/a.quota_total*100)+'%':'0%'}"></div>
      </div><span class="text-secondary text-[11px] font-label-md">{{fmtNum(a.quota_remaining)}}</span>
    </div>
  </td>
  <td class="px-md py-sm font-label-md text-[10px] text-secondary truncate max-w-[80px]" :title="a.auth_token">{{a.has_auth_token ? a.auth_token : '—'}}</td>
  <td class="px-md py-sm font-label-md text-[10px] text-secondary truncate max-w-[80px]" :title="a.api_key">{{a.has_api_key ? a.api_key : '—'}}</td>
  <td class="px-md py-sm">
    <div class="flex items-center gap-xs text-[11px] font-label-md">
      <span v-if="a.has_api_key" class="text-[#1e7e34]">✅ API</span>
      <span v-if="a.has_auth_token" class="text-[#1e7e34]">✅ TK</span>
      <span v-if="!a.has_api_key && !a.has_auth_token" class="text-error">—</span>
    </div>
  </td>
  <td class="px-md py-sm"><span :class="a.checked_today?'bg-secondary-container text-on-secondary-container':'bg-surface-container text-secondary'" class="font-label-md text-[10px] px-2 py-0.5 rounded">{{a.checked_today?'已完成':'待处理'}}</span></td>
  <td class="px-md py-sm"><span :class="a.status==='active'?'bg-secondary-container text-on-secondary-container':'bg-error-container text-on-error-container'" class="font-label-md text-[10px] px-2 py-0.5 rounded">{{a.status}}</span></td>
  <td class="px-md py-sm">
    <div class="flex items-center gap-xs">
      <button @click="querySingleQuota(a)" ...>...</button>
      <button @click="checkinSingle(a.uid)" ...>...</button>
      <button @click="deleteAccount(a.uid)" ...>...</button>
    </div>
  </td>
</tr>
```

**Step 3: 验证**

打开账号页，确认表格列与桌面 GUI 对齐。

---

### Task 6: 提交

```bash
git add web/api/accounts.py web/api/proxy.py web/static/index.html
git commit -m "feat: 代理页从账号导入Key + 账号表格补齐UID/TK/CK/API状态列"
```
