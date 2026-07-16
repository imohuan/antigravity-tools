"""
Antigravity Tools 完整自动化测试
测试 API 端点 + 日志记录功能
"""
import requests, json, sys, time

BASE = "http://127.0.0.1:8866"
PROXY = "http://127.0.0.1:8002"
PASSED = 0
FAILED = 0

def test(name, condition, detail=""):
    global PASSED, FAILED
    if condition:
        PASSED += 1
        print("  [PASS] %s" % name)
    else:
        FAILED += 1
        print("  [FAIL] %s -- %s" % (name, detail))

def test_api(path, checks=None):
    try:
        r = requests.get("%s%s" % (BASE, path), timeout=10)
        d = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        if checks:
            for name, fn in checks:
                test(name, fn(d), "response: %s" % json.dumps(d, ensure_ascii=False)[:200])
        return d
    except Exception as e:
        test("API %s - connection" % path, False, str(e))
        return {}

print("=" * 60)
print("Antigravity Tools Full Test Suite")
print("=" * 60)

# === Part 1: API 端点测试 ===
print("\n--- 1. Proxy Status ---")
d = test_api("/api/proxy/status", [
    ("has running", lambda d: "running" in d),
    ("running is bool", lambda d: isinstance(d.get("running"), bool)),
    ("strategy is int", lambda d: isinstance(d.get("strategy"), int) and 1 <= d.get("strategy") <= 4),
    ("has keys", lambda d: isinstance(d.get("keys"), list)),
])

print("\n--- 2. Quota API ---")
d = test_api("/api/proxy/quota?cache=true", [
    ("success", lambda d: d.get("success") == True),
    ("has summary", lambda d: isinstance(d.get("summary"), dict)),
    ("has totalRemain", lambda d: "totalRemain" in d.get("summary", {})),
    ("has totalCredits", lambda d: "totalCredits" in d.get("summary", {})),
    ("accounts is list", lambda d: isinstance(d.get("accounts"), list)),
])
for acc in d.get("accounts", [])[:2]:
    test("account %s has packages" % acc.get("name","?"), isinstance(acc.get("packages"), list))

print("\n--- 3. Logs API ---")
d = test_api("/api/proxy/logs?limit=5&page=1", [
    ("success", lambda d: d.get("success") == True),
    ("has total", lambda d: isinstance(d.get("total"), int)),
    ("page=1", lambda d: d.get("page") == 1),
    ("logs is list", lambda d: isinstance(d.get("logs"), list)),
])

print("\n--- 4. Dashboard ---")
d = test_api("/api/proxy/stats/overview", [
    ("success", lambda d: d.get("success") == True),
    ("has total_requests", lambda d: "total_requests" in d),
    ("has success_rate", lambda d: "success_rate" in d),
])

print("\n--- 5. Calendar ---")
d = test_api("/api/proxy/stats/calendar?months=4", [
    ("success", lambda d: d.get("success") == True),
    ("data is list", lambda d: isinstance(d.get("data"), list)),
])

print("\n--- 6. Strategy ---")
r = requests.post("%s/api/proxy/strategy" % BASE, json={"strategy": 2})
test("switch to 2", r.json().get("success") == True)
r = requests.post("%s/api/proxy/strategy" % BASE, json={"strategy": 1})
test("switch to 1", r.json().get("success") == True)

print("\n--- 7. Accounts ---")
d = test_api("/api/accounts", [
    ("has accounts", lambda d: isinstance(d.get("accounts"), list)),
    ("has total", lambda d: isinstance(d.get("total"), int)),
])

# === Part 2: 日志记录测试 ===
print("\n--- 8. Log Recording (via DB) ---")
sys.path.insert(0, r"D:\Code\Learn\antigravity-tools")
from src.modules.proxy_server import ProxyDatabase
db = ProxyDatabase.get_instance()

# 清空
db.log_store.conn.execute("DELETE FROM request_logs")
db.log_store.conn.commit()

# 模拟 end 事件
db.add_request_log({
    "timestamp": time.time(),
    "main_key_id": "ck_test1",
    "main_key_label": "test-key",
    "model": "deepseek-v4-pro",
    "event": "end",
    "duration_ms": 1200,
    "prompt_tokens": 3000,
    "completion_tokens": 1500,
    "credit": 3.5,
    "key_mode": "1",
    "first_token_ms": 250,
    "request_path": "/v1/chat/completions",
})

# 模拟 auth_fail
db.add_request_log({
    "timestamp": time.time(),
    "model": "",
    "event": "auth_fail",
    "error": "Invalid key",
    "request_path": "/v1/chat/completions",
})

# 模拟 upstream_error
db.add_request_log({
    "timestamp": time.time(),
    "main_key_id": "ck_bad",
    "main_key_label": "bad-key",
    "model": "glm-5.2",
    "event": "upstream_error",
    "error": "429",
    "key_mode": "2",
    "request_path": "/v1/chat/completions",
})

time.sleep(0.5)

rows = db.log_store.conn.execute("SELECT * FROM request_logs ORDER BY id").fetchall()
cols = [d[0] for d in db.log_store.conn.execute("SELECT * FROM request_logs LIMIT 0").description]

test("3 logs inserted", len(rows) == 3, "got %d" % len(rows))

for row in rows:
    d = dict(zip(cols, row))
    if d['credit'] > 0 and d['model'] == 'deepseek-v4-pro':
        test("end log: status=success", d['status'] == 'success')
        test("end log: credit=3.5", d['credit'] == 3.5)
        test("end log: key_mode=1", d['key_mode'] == '1')
        test("end log: total_tokens=4500", d['total_tokens'] == 4500)
    elif d['error'] == 'Invalid key':
        test("auth_fail: status=failed", d['status'] == 'failed')
        test("auth_fail: credit=0", d['credit'] == 0)
    elif d['error'] == '429':
        test("upstream_error: status=failed", d['status'] == 'failed')
        test("upstream_error: key_mode=2", d['key_mode'] == '2')

# 通过 API 验证日志
r = requests.get("%s/api/proxy/logs?limit=10&page=1" % BASE)
logs_data = r.json()
test("API returns 3 logs", logs_data.get("total") == 3)

# 验证日志中的策略显示
for log in logs_data.get("logs", []):
    if log.get("credit", 0) > 0:
        test("API log has key_mode", log.get("key_mode", "") != "", "got: %s" % log.get("key_mode"))

# === Part 3: GET/OPTIONS 不产生日志 ===
print("\n--- 9. No log for GET/OPTIONS ---")
count_before = db.log_store.conn.execute("SELECT COUNT(*) FROM request_logs").fetchone()[0]
try:
    requests.get("%s/v1/models" % PROXY, timeout=5)
except:
    pass
try:
    requests.options("%s/v1/chat/completions" % PROXY, timeout=5)
except:
    pass
time.sleep(0.5)
count_after = db.log_store.conn.execute("SELECT COUNT(*) FROM request_logs").fetchone()[0]
test("GET/OPTIONS produce no logs", count_before == count_after,
     "before=%d after=%d" % (count_before, count_after))

# 清理
db.log_store.conn.execute("DELETE FROM request_logs")
db.log_store.conn.commit()

# === Summary ===
print("\n" + "=" * 60)
print("Results: %d passed, %d failed" % (PASSED, FAILED))
print("=" * 60)

if FAILED > 0:
    sys.exit(1)
else:
    print("\nALL TESTS PASSED!")
    sys.exit(0)
