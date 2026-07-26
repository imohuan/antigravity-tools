"""验证 toggle / activate 接口的逻辑（mock 数据库）"""
import sys
sys.path.insert(0, '.')

# 必须先 import，否则 patch 找不到属性
import src.modules.proxy_server  # noqa
from src.modules.proxy_server import ProxyDatabase
from unittest.mock import patch

# Mock 数据：模拟 7 种状态的 key
mock_keys = [
    {'key_id': 'ck_test1', 'api_key': 'ck_xxx1', 'status': 'abnormal', 'label': 'test1'},
    {'key_id': 'ck_test2', 'api_key': 'ck_xxx2', 'status': 'active', 'label': 'test2'},
    {'key_id': 'ck_test3', 'api_key': 'ck_xxx3', 'status': 'disabled', 'label': 'test3'},
    {'key_id': 'ck_test4', 'api_key': 'ck_xxx4', 'status': 'exhausted', 'label': 'test4'},
    {'key_id': 'ck_test5', 'api_key': 'ck_xxx5', 'status': 'cooldown', 'label': 'test5'},
    {'key_id': 'ck_test6', 'api_key': 'ck_xxx6', 'status': 'rate_limited', 'label': 'test6'},
    {'key_id': 'ck_test7', 'api_key': 'ck_xxx7', 'status': 'permanent_disabled', 'label': 'test7'},
]


def mock_update(key_id, updates):
    for k in mock_keys:
        if k['key_id'] == key_id or k['api_key'] == key_id:
            k.update(updates)


def find_kid(status):
    for k in mock_keys:
        if k['status'] == status:
            return k['key_id']
    return None


# 直接替换 get_instance 返回的实例
mock_instance = type('MockDB', (), {})()
mock_instance.get_upstream_keys = lambda: mock_keys
mock_instance.update_upstream_key = mock_update

with patch.object(ProxyDatabase, 'get_instance', return_value=mock_instance):
    from web.api.proxy import proxy_toggle_key, proxy_activate_key

    print('=== Test 1: toggle 系统禁用状态应该返回 400 ===')
    for status in ['abnormal', 'exhausted', 'cooldown', 'rate_limited', 'permanent_disabled']:
        kid = find_kid(status)
        try:
            proxy_toggle_key(kid)
            print(f'  FAIL: toggle {status} should raise 400')
        except Exception as e:
            detail = e.detail if hasattr(e, 'detail') else str(e)
            print(f'  OK: toggle {status} -> 400: {detail}')

    print()
    print('=== Test 2: toggle active <-> disabled 应该成功 ===')
    r = proxy_toggle_key('ck_test2')  # active -> disabled
    print(f'  toggle active -> disabled: {r}')
    r = proxy_toggle_key('ck_test3')  # disabled -> active
    print(f'  toggle disabled -> active: {r}')

    print()
    print('=== Test 3: activate 任何状态都应该成功 ===')
    # 先重置 mock 数据
    for k in mock_keys:
        if k['key_id'] == 'ck_test2':
            k['status'] = 'active'
        if k['key_id'] == 'ck_test3':
            k['status'] = 'disabled'
    for status in ['abnormal', 'exhausted', 'cooldown', 'rate_limited', 'permanent_disabled']:
        kid = find_kid(status)
        r = proxy_activate_key(kid)
        warning = (r.get('warning') or '无')[:60]
        prev = r.get('previous_status', '?')
        print(f'  activate {status:20s} -> success={r["success"]}, status={r["status"]}, prev={prev}, warning={warning}')

    print()
    print('=== Test 4: activate 已是 active 的 key 应返回提示 ===')
    r = proxy_activate_key('ck_test2')
    print(f'  activate active key: {r}')

    print()
    print('=== Test 5: toggle/activate 不存在的 key 应返回 404 ===')
    try:
        proxy_toggle_key('ck_notexist')
    except Exception as e:
        print(f'  toggle not found: 404: {e.detail}')
    try:
        proxy_activate_key('ck_notexist')
    except Exception as e:
        print(f'  activate not found: 404: {e.detail}')

print()
print('=== ALL TESTS DONE ===')
