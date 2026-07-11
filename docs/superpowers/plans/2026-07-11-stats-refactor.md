# 统计系统重构实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 消灭定时器 + 写时预聚合，把统计变成"每条请求写完瞬间就有统计"

**Architecture:** 只用 request_logs.db 一个 SQLite 文件，3 张新聚合表在 INSERT 时同事务 UPSERT。删除 daily_stats.json 和 proxy_db.json 里的 request_logs。去掉 60 秒定时器。

**Tech Stack:** Python + SQLite WAL + FastAPI

---

## File Structure

| 操作 | 文件 | 职责 |
|------|------|------|
| 修改 | `src/modules/log_store.py` | 建聚合表 + insert 时 UPSERT |
| 修改 | `src/modules/daily_stats.py` | 查聚合表，删 sync_today |
| 修改 | `src/modules/proxy_server.py` | 删定时器 + get_request_logs 改查 SQLite |
| 修改 | `web/api/proxy.py` | 不改（API 接口签名不变） |
| 创建 | `scripts/migrate_stats.py` | 一次性历史数据迁移 |

---

### Task 1: 给 LogStore 加聚合表 + 改 insert()

**Files:**
- Modify: `src/modules/log_store.py`

- [ ] **Step 1: 在 __init__ 建表时新增三张聚合表**

在 `CREATE TABLE IF NOT EXISTS request_logs` 之后，新增三张表：

```sql
CREATE TABLE IF NOT EXISTS daily_stats (
    date TEXT PRIMARY KEY,
    requests INTEGER DEFAULT 0,
    success INTEGER DEFAULT 0,
    failed INTEGER DEFAULT 0,
    tokens INTEGER DEFAULT 0,
    credits REAL DEFAULT 0.0,
    duration_sum INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS daily_model_stats (
    date TEXT NOT NULL,
    model TEXT NOT NULL,
    count INTEGER DEFAULT 0,
    credits REAL DEFAULT 0.0,
    PRIMARY KEY (date, model)
);

CREATE TABLE IF NOT EXISTS daily_key_stats (
    date TEXT NOT NULL,
    key_label TEXT NOT NULL,
    count INTEGER DEFAULT 0,
    credits REAL DEFAULT 0.0,
    PRIMARY KEY (date, key_label)
);
```

- [ ] **Step 2: 把 insert() 改成写完后同事务 UPSERT 三张聚合表**

在 `self.conn.commit()` 之前，用同一个连接执行 UPSERT：

```python
# INSERT 明细后，立即 UPSERT 三张聚合表
date_str = datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
model = log.get("model", "") or "unknown"
key_label = log.get("main_key_label", "") or "unknown"
status = log.get("status", "success")
is_success = 1 if status == "success" else 0
is_failed = 0 if status == "success" else 1
credit = log.get("credit", 0.0) or 0.0
tokens = log.get("total_tokens", 0) or 0
duration = log.get("duration_ms", 0) or 0

# daily_stats
self.conn.execute("""
    INSERT INTO daily_stats (date, requests, success, failed, tokens, credits, duration_sum)
    VALUES (?, 1, ?, ?, ?, ?, ?)
    ON CONFLICT(date) DO UPDATE SET
        requests = requests + 1,
        success = success + ?,
        failed = failed + ?,
        tokens = tokens + ?,
        credits = credits + ?,
        duration_sum = duration_sum + ?
""", (date_str, is_success, is_failed, tokens, credit, duration,
      is_success, is_failed, tokens, credit, duration))

# daily_model_stats
self.conn.execute("""
    INSERT INTO daily_model_stats (date, model, count, credits)
    VALUES (?, ?, 1, ?)
    ON CONFLICT(date, model) DO UPDATE SET
        count = count + 1,
        credits = credits + ?
""", (date_str, model, credit, credit))

# daily_key_stats
self.conn.execute("""
    INSERT INTO daily_key_stats (date, key_label, count, credits)
    VALUES (?, ?, 1, ?)
    ON CONFLICT(date, key_label) DO UPDATE SET
        count = count + 1,
        credits = credits + ?
""", (date_str, key_label, credit, credit))

# 最后一次性 commit
self.conn.commit()
```

- [ ] **Step 3: 提交**

```bash
git add src/modules/log_store.py
git commit -m "feat: LogStore.insert() 写时预聚合 daily_stats / model / key 三张表"
```

---

### Task 2: 给 DailyStatsManager 改查聚合表

**Files:**
- Modify: `src/modules/daily_stats.py`

- [ ] **Step 1: get_overview() 改为查 daily_stats 聚合表**

```python
def get_overview(self) -> dict:
    row = self._log_store.conn.execute(
        "SELECT COALESCE(SUM(requests),0), COALESCE(SUM(success),0), COALESCE(SUM(failed),0), "
        "COALESCE(SUM(tokens),0), COALESCE(SUM(credits),0), "
        "CASE WHEN SUM(requests)>0 THEN CAST(SUM(duration_sum) AS REAL)/SUM(requests) ELSE 0 END "
        "FROM daily_stats"
    ).fetchone()

    total_requests = row[0]
    total_success = row[1]
    total_failed = row[2]
    total_tokens = row[3]
    total_credits = round(row[4], 4)
    avg_duration_ms = int(row[5])

    success_rate = round(total_success / total_requests * 100, 1) if total_requests > 0 else 0

    model_rows = self._log_store.conn.execute(
        "SELECT model, SUM(count) as cnt, SUM(credits) as credits "
        "FROM daily_model_stats GROUP BY model ORDER BY credits DESC LIMIT 10"
    ).fetchall()

    key_rows = self._log_store.conn.execute(
        "SELECT key_label, SUM(count) as cnt, SUM(credits) as credits "
        "FROM daily_key_stats GROUP BY key_label ORDER BY credits DESC LIMIT 10"
    ).fetchall()

    return {
        "total_requests": total_requests,
        "total_success": total_success,
        "total_failed": total_failed,
        "success_rate": success_rate,
        "total_tokens": total_tokens,
        "total_credits": total_credits,
        "avg_duration_ms": avg_duration_ms,
        "by_model": [
            {"name": r[0] or "unknown", "credits": round(r[2], 4), "count": r[1]}
            for r in model_rows
        ],
        "by_key": [
            {"name": r[0] or "unknown", "credits": round(r[2], 4), "count": r[1]}
            for r in key_rows
        ],
    }
```

- [ ] **Step 2: get_calendar() 改为查 daily_stats 表**

```python
def get_calendar(self, months: int = 4) -> list[dict]:
    rows = self._log_store.conn.execute(
        "SELECT date, credits, requests FROM daily_stats "
        "WHERE date >= date('now', ?) ORDER BY date",
        (f"-{months} months",)
    ).fetchall()
    return [
        {"date": r[0], "credits": round(r[1], 4), "count": r[2]}
        for r in rows
    ]
```

- [ ] **Step 3: 删掉 sync_today() 和 _load/_save**

这三个方法全部删除。

- [ ] **Step 4: __init__ 去掉 stats_path 参数**

构造函数改为只接收 log_store：
```python
def __init__(self, log_store: LogStore):
    self._log_store = log_store
```

- [ ] **Step 5: 提交**

```bash
git add src/modules/daily_stats.py
git commit -m "refactor: DailyStatsManager 改查聚合表，删掉 sync_today + daily_stats.json"
```

---

### Task 3: 清理 ProxyDatabase 里的旧逻辑

**Files:**
- Modify: `src/modules/proxy_server.py`

- [ ] **Step 1: 删掉 start_stats_timer() 方法**

整个方法删除（约 1060-1086 行）。同时删掉 `self._stats_timer = None` 初始化。

- [ ] **Step 2: __init__ 里去掉 self.start_stats_timer() 调用**

删掉 ProxyDatabase.__init__ 里第 552 行的 `self.start_stats_timer()`。

- [ ] **Step 3: ProxyServer.start() 里去掉 self.db.start_stats_timer() 调用**

删掉 ProxyServer.start() 里第 3135 行的 `self.db.start_stats_timer()`。

- [ ] **Step 4: 删掉 _aggregate_historical_logs()**

整个方法删除。

- [ ] **Step 5: add_request_log() 不再写 proxy_db.json 的 request_logs**

只保留 SQLite 写入，删掉 with self._lock 块里往 `self._data["request_logs"]` 追加的部分。

即 add_request_log 变成：
```python
def add_request_log(self, log: dict):
    try:
        self.log_store.insert(log)
    except Exception as e:
        logger.error(f"[add_request_log] SQLite写入失败: {e}")
```

- [ ] **Step 6: get_request_logs() 改为查 SQLite**

```python
def get_request_logs(self, since: float = 0, limit: int = 50, page: int = 1, reverse: bool = True) -> dict:
    order = "DESC" if reverse else "ASC"
    offset = (page - 1) * limit

    if since > 0:
        total = self.log_store.conn.execute(
            "SELECT COUNT(*) FROM request_logs WHERE timestamp > ?", (since,)
        ).fetchone()[0]
        rows = self.log_store.conn.execute(
            f"SELECT * FROM request_logs WHERE timestamp > ? ORDER BY timestamp {order} LIMIT ? OFFSET ?",
            (since, limit, offset)
        ).fetchall()
    else:
        total = self.log_store.conn.execute(
            "SELECT COUNT(*) FROM request_logs"
        ).fetchone()[0]
        rows = self.log_store.conn.execute(
            f"SELECT * FROM request_logs ORDER BY timestamp {order} LIMIT ? OFFSET ?",
            (limit, offset)
        ).fetchall()

    cols = [desc[0] for desc in self.log_store.conn.execute(
        "SELECT * FROM request_logs LIMIT 0"
    ).description]
    logs = [dict(zip(cols, row)) for row in rows]

    total_pages = max(1, (total + limit - 1) // limit) if total > 0 else 0
    return {"logs": logs, "total": total, "page": page, "limit": limit, "total_pages": total_pages}
```

- [ ] **Step 7: proxy_db.json 默认数据去掉 request_logs**

__init__ 里 `self._data` 默认值从包含 `"request_logs": []` 改为不包含它。

- [ ] **Step 8: 提交**

```bash
git add src/modules/proxy_server.py
git commit -m "refactor: 去掉定时器，请求日志改读 SQLite，删掉 proxy_db.json request_logs"
```

---

### Task 4: 给 request_logs 表补全前端需要的字段

**Files:**
- Modify: `src/modules/log_store.py`

前端表格显示字段: `timestamp, model, main_key_label, key_mode, status, credit, prompt_tokens, completion_tokens, first_token_ms, duration_ms, attempt, error`

当前 SQLite 表缺: `key_mode, error, first_token_ms, attempt`

- [ ] **Step 1: 用 ALTER TABLE 补列**

在 __init__ 建表后加：
```python
for col, col_type in [
    ("key_mode", "TEXT DEFAULT ''"),
    ("error", "TEXT DEFAULT ''"),
    ("first_token_ms", "INTEGER DEFAULT 0"),
    ("attempt", "INTEGER DEFAULT 1"),
]:
    try:
        self._conn.execute(f"ALTER TABLE request_logs ADD COLUMN {col} {col_type}")
    except sqlite3.OperationalError:
        pass
self._conn.commit()
```

- [ ] **Step 2: insert() 里写入新字段**

在 INSERT 语句 VALUES 里加上 `key_mode, error, first_token_ms, attempt` 四个字段：
```python
log.get("key_mode", ""),
log.get("error", ""),
log.get("first_token_ms", 0),
log.get("attempt", 1),
```

- [ ] **Step 3: 提交**

```bash
git add src/modules/log_store.py
git commit -m "fix: request_logs 表补全前端需要的 key_mode/error/first_token_ms/attempt 字段"
```

---

### Task 5: 迁移历史数据 + 验证

**Files:**
- Create: `scripts/migrate_stats.py`

- [ ] **Step 1: 写迁移脚本**

```python
"""一次性脚本: 从 request_logs 明细表反算聚合表"""
import sqlite3, os

db_path = os.path.join(
    os.environ.get("USERPROFILE", os.path.expanduser("~")),
    ".antigravity-tools", "request_logs.db"
)
conn = sqlite3.connect(db_path)
conn.execute("PRAGMA journal_mode=WAL")

conn.execute("DELETE FROM daily_stats")
conn.execute("DELETE FROM daily_model_stats")
conn.execute("DELETE FROM daily_key_stats")

conn.execute("""
    INSERT INTO daily_stats (date, requests, success, failed, tokens, credits, duration_sum)
    SELECT date, COUNT(*),
        SUM(CASE WHEN status='success' THEN 1 ELSE 0 END),
        SUM(CASE WHEN status!='success' THEN 1 ELSE 0 END),
        COALESCE(SUM(total_tokens), 0), COALESCE(SUM(credit), 0),
        COALESCE(SUM(duration_ms), 0)
    FROM request_logs GROUP BY date
""")

conn.execute("""
    INSERT INTO daily_model_stats (date, model, count, credits)
    SELECT date, COALESCE(NULLIF(model,''),'unknown'),
        COUNT(*), COALESCE(SUM(credit), 0)
    FROM request_logs WHERE credit > 0
    GROUP BY date, COALESCE(NULLIF(model,''),'unknown')
""")

conn.execute("""
    INSERT INTO daily_key_stats (date, key_label, count, credits)
    SELECT date, COALESCE(NULLIF(main_key_label,''),'unknown'),
        COUNT(*), COALESCE(SUM(credit), 0)
    FROM request_logs WHERE credit > 0
    GROUP BY date, COALESCE(NULLIF(main_key_label,''),'unknown')
""")

conn.commit()
print("Migration done!")
for t in ["daily_stats", "daily_model_stats", "daily_key_stats"]:
    n = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
    print(f"  {t}: {n} rows")
conn.close()
```

- [ ] **Step 2: 运行迁移**

```bash
python scripts/migrate_stats.py
```

- [ ] **Step 3: 验证**

启动服务，打几个代理请求，打开仪表盘看数据是否实时更新。

- [ ] **Step 4: 提交**

```bash
git add scripts/migrate_stats.py
git commit -m "feat: 历史数据迁移脚本"
```

---

## Self-Review

1. **Spec coverage:** 所有需求已覆盖 - 写时聚合、删定时器、删 daily_stats.json、删 proxy_db.json request_logs
2. **Placeholder scan:** 无 TBD/TODO/占位符
3. **Type consistency:** log_store 接口不变，daily_stats 接口不变，proxy_server 对外接口不变

---

**Plan complete and saved to `docs/superpowers/plans/2026-07-11-stats-refactor.md`. Two execution options:**

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**
