"""
Antigravity Tools 自动化测试脚本
测试 API 端点功能完整性
"""
import requests
import json
import sys

BASE = "http://127.0.0.1:8866"
PASSED = 0
FAILED = 0

def test(name, condition, detail=""):
    global PASSED, FAILED
    if condition:
        PASSED += 1
        print(f"  [PASS] {name}")
    else:
        FAILED += 1
        print(f"  [FAIL] {name}  -- {detail}")

def test_api(path, checks=None):
    try:
        r = requests.get(f"{BASE}{path}", timeout=10)
        d = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        if checks:
            for name, fn in checks:
                test(name, fn(d), f"response: {json.dumps(d, ensure_ascii=False)[:200]}")
        return d
    except Exception as e:
        test(f"API {path} - connection", False, str(e))
        return {}

print("=" * 60)
print("Antigravity Tools API Test")
print("=" * 60)

# 1. Proxy Status
print("\n--- Proxy Status ---")
d = test_api("/api/proxy/status", [
    ("has running", lambda d: "running" in d),
    ("running is bool", lambda d: isinstance(d.get("running"), bool)),
    ("strategy is int 1-4", lambda d: isinstance(d.get("strategy"), int) and 1 <= d.get("strategy") <= 4),
    ("has keys list", lambda d: isinstance(d.get("keys"), list)),
])

# 2. Quota API
print("\n--- Quota API ---")
d = test_api("/api/proxy/quota?cache=true", [
    ("success=True", lambda d: d.get("success") == True),
    ("has summary", lambda d: isinstance(d.get("summary"), dict)),
    ("has totalRemain", lambda d: "totalRemain" in d.get("summary", {})),
    ("has totalCredits", lambda d: "totalCredits" in d.get("summary", {})),
    ("has accountCount", lambda d: "accountCount" in d.get("summary", {})),
    ("accounts is list", lambda d: isinstance(d.get("accounts"), list)),
    ("account count matches", lambda d: len(d.get("accounts", [])) == d.get("summary", {}).get("accountCount", -1)),
])

for acc in d.get("accounts", [])[:3]:
    prefix = f"account {acc.get('name', '?')}"
    test(f"{prefix} has name", "name" in acc)
    test(f"{prefix} has totalRemain", "totalRemain" in acc)
    test(f"{prefix} has packages", isinstance(acc.get("packages"), list))

# 3. Logs API
print("\n--- Logs API ---")
d = test_api("/api/proxy/logs?limit=10&page=1", [
    ("success=True", lambda d: d.get("success") == True),
    ("has total", lambda d: isinstance(d.get("total"), int)),
    ("page=1", lambda d: d.get("page") == 1),
    ("has total_pages", lambda d: isinstance(d.get("total_pages"), int)),
    ("logs is list", lambda d: isinstance(d.get("logs"), list)),
])

logs = d.get("logs", [])
if logs:
    log = logs[0]
    test("log has timestamp", "timestamp" in log)
    test("log has model", "model" in log)
    test("log has status", "status" in log)
    test("log has credit", "credit" in log)

# 4. Pagination
print("\n--- Logs Pagination ---")
d2 = test_api("/api/proxy/logs?limit=5&page=2", [
    ("page=2", lambda d: d.get("page") == 2),
])

# 5. Dashboard
print("\n--- Dashboard ---")
d = test_api("/api/proxy/stats/overview", [
    ("success=True", lambda d: d.get("success") == True),
    ("has total_requests", lambda d: "total_requests" in d),
    ("has total_credits", lambda d: "total_credits" in d),
    ("has success_rate", lambda d: "success_rate" in d),
])

# 6. Calendar
print("\n--- Calendar ---")
d = test_api("/api/proxy/stats/calendar?months=4", [
    ("success=True", lambda d: d.get("success") == True),
    ("data is list", lambda d: isinstance(d.get("data"), list)),
])

# 7. Strategy
print("\n--- Strategy ---")
r = requests.post(f"{BASE}/api/proxy/strategy", json={"strategy": 2})
d = r.json()
test("switch to 2", d.get("success") == True and d.get("strategy") == 2)
r = requests.post(f"{BASE}/api/proxy/strategy", json={"strategy": 1})
d = r.json()
test("switch back to 1", d.get("success") == True and d.get("strategy") == 1)

# 8. Accounts
print("\n--- Accounts ---")
d = test_api("/api/accounts", [
    ("has accounts", lambda d: isinstance(d.get("accounts"), list)),
    ("has total", lambda d: isinstance(d.get("total"), int)),
])

# Summary
print("\n" + "=" * 60)
print(f"Results: {PASSED} passed, {FAILED} failed")
print("=" * 60)

if FAILED > 0:
    sys.exit(1)
else:
    print("\nAll tests passed!")
    sys.exit(0)
