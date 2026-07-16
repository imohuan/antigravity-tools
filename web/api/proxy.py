"""Proxy server control API routes"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
import threading
import logging

from src.modules.proxy_server import ProxyServer, ProxyDatabase, ProxyRequestHandler
from src.utils.store import load_accounts, load_setting, save_setting

logger = logging.getLogger(__name__)
router = APIRouter(tags=["proxy"])

_proxy_server: Optional[ProxyServer] = None
_proxy_thread: Optional[threading.Thread] = None


class AddKeyRequest(BaseModel):
    api_key: str
    account_name: Optional[str] = None


def _get_db():
    return ProxyDatabase.get_instance()


def _parse_quota_from_key(k: dict) -> float:
    """从 points 字符串 "剩余/总量" 提取剩余数值，失败返回 0"""
    pts = k.get("points", "")
    if pts and "/" in pts:
        try:
            return float(pts.split("/")[0])
        except (ValueError, IndexError):
            pass
    return 0


@router.get("/proxy/status")
def proxy_status():
    """Get proxy server status and key pool info"""
    db = _get_db()
    keys = db.get_upstream_keys()
    active_keys = [k for k in keys if k.get("status") == "active"]
    return {
        "running": _proxy_server is not None and _proxy_server.is_running,
        "strategy": int(load_setting("proxyStrategy", "1")),
        "port": int(load_setting("proxyPort", "8867")),
        "total_keys": len(keys),
        "active_keys": len(active_keys),
        "exhausted_keys": len(keys) - len(active_keys),
        "keys": [{
            "id": k.get("key_id") or k.get("api_key", ""),
            "prefix": (k.get("api_key", "") or "")[:16],
            "suffix": (k.get("api_key", "") or "")[-4:],
            "account": k.get("label", ""),
            "quota_remaining": _parse_quota_from_key(k),
            "active": k.get("status") == "active",
            "status": k.get("status", "active"),
        } for k in keys],
    }


class StartProxyRequest(BaseModel):
    strategy: int = 1  # 1=专一, 2=临期优先, 3=轮询, 4=会话亲和

@router.post("/proxy/start")
def proxy_start(req: StartProxyRequest = StartProxyRequest()):
    """Start the proxy server"""
    global _proxy_server, _proxy_thread
    if _proxy_server and _proxy_server.is_running:
        return {"success": True, "message": "Proxy already running"}
    try:
        port = int(load_setting("proxyPort", "8867"))
        _proxy_server = ProxyServer(port=port)
        ProxyRequestHandler.default_key_mode = req.strategy
        save_setting("proxyStrategy", str(req.strategy))
        _proxy_thread = threading.Thread(target=_proxy_server.start, daemon=True)
        _proxy_thread.start()
        return {"success": True, "message": f"Proxy started on port {port}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


class SetStrategyRequest(BaseModel):
    strategy: int = 1

@router.post("/proxy/strategy")
def proxy_set_strategy(req: SetStrategyRequest):
    """实时更新全局默认策略，无需重启代理"""
    ProxyRequestHandler.default_key_mode = req.strategy
    save_setting("proxyStrategy", str(req.strategy))
    return {"success": True, "strategy": req.strategy}

@router.post("/proxy/stop")
def proxy_stop():
    """Stop the proxy server"""
    global _proxy_server, _proxy_thread
    if _proxy_server:
        try:
            _proxy_server.stop()
        except Exception:
            pass
        _proxy_server = None
    _proxy_thread = None
    return {"success": True, "message": "Proxy stopped"}


@router.post("/proxy/keys/add")
def proxy_add_key(req: AddKeyRequest):
    """Add an upstream API key to the pool"""
    if not req.api_key.startswith("ck_"):
        raise HTTPException(status_code=400, detail="API Key must start with ck_")
    db = _get_db()
    key_data = {"api_key": req.api_key, "label": req.account_name or req.api_key[:8]}
    db.add_upstream_key(key_data)
    return {"success": True, "key_prefix": req.api_key[:16]}


@router.post("/proxy/keys/{key_id}/delete")
def proxy_delete_key(key_id: str):
    """Remove a key from the pool (matches by key_id or api_key)"""
    db = _get_db()
    db.delete_upstream_key(key_id)
    return {"success": True}


@router.post("/proxy/keys/{key_id}/toggle")
def proxy_toggle_key(key_id: str):
    """Toggle a key's active status (matches by key_id or api_key)"""
    db = _get_db()
    keys = db.get_upstream_keys()
    key = next((k for k in keys if k.get("key_id") == key_id or k.get("api_key") == key_id), None)
    if not key:
        raise HTTPException(status_code=404, detail="Key not found")
    current = key.get("status", "active")
    new_status = "disabled" if current in ("active", "exhausted", "cooldown", "rate_limited") else "active"
    db.update_upstream_key(key_id, {"status": new_status})
    return {"success": True, "active": new_status == "active"}


class ImportFromAccountsRequest(BaseModel):
    uids: list[str]


@router.get("/proxy/accounts-with-keys")
def proxy_accounts_with_keys():
    """Return accounts that can be imported into proxy key pool (with import status)"""
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


@router.post("/proxy/keys/import-from-accounts")
def proxy_import_from_accounts(req: ImportFromAccountsRequest):
    """Import API keys from existing accounts into upstream key pool"""
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

        import_key = acc.api_key if (acc.api_key and acc.api_key.startswith("ck_")) else acc.auth_token
        if not import_key:
            skipped += 1
            continue

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

# ─── 配额接口：返回代理 Key 池的配额数据 ───
@router.get("/proxy/quota")
def proxy_quota(cache: str = "true"):
    """获取代理 Key 池的配额数据。
    cache=true（默认）：直接读数据库缓存（快，但 packages 可能不完整）。
    cache=false：实时查询每个 Key 的积分（慢，但 packages 完整）。
    """
    db = _get_db()
    keys = db.get_upstream_keys()

    # cache=false 时：实时查询每个 Key 的积分，更新数据库缓存
    if cache.lower() != "true":
        import logging as _log
        _log.getLogger(__name__).info("proxy/quota: cache=false, 实时查询 %d 个 Key", len(keys))
        from src.modules.api_client import ApiClient
        updated_keys = []
        for k in keys:
            api_key = k.get("api_key", "")
            if not api_key:
                updated_keys.append(k)
                continue
            try:
                key_type = k.get("key_type", "")
                if api_key.startswith("ck_") or key_type == "apikey":
                    client = ApiClient.from_api_key(api_key)
                else:
                    uid = k.get("uid", "")
                    domain = k.get("domain", "www.codebuddy.cn")
                    if not uid:
                        # 老数据没有 uid，尝试从 accounts 匹配
                        from src.utils.store import load_accounts as _la
                        accs = _la()
                        matched = next((a for a in accs if a.auth_token == api_key or a.api_key == api_key), None)
                        if matched:
                            uid = matched.uid
                            domain = matched.domain or "www.codebuddy.cn"
                        else:
                            updated_keys.append(k)
                            continue
                    client = ApiClient(access_token=api_key, uid=uid, domain=domain)
                qr = client.get_user_resource()
                if qr.get("success"):
                    key_total = float(qr.get("total_credits", 0))
                    key_remain = float(qr.get("remaining_credits", 0))
                    raw_packages = qr.get("packages", [])
                    packages_dicts = []
                    for p in raw_packages:
                        if hasattr(p, '__dict__'):
                            d = {}
                            for attr in ['package_name', 'type_label', 'cycle_remain', 'cycle_size',
                                          'cycle_start', 'cycle_end', 'package_type', 'capacity_unit']:
                                val = getattr(p, attr, None)
                                if val is not None:
                                    d[attr] = str(val) if not isinstance(val, (int, float)) else val
                            packages_dicts.append(d)
                        elif isinstance(p, dict):
                            packages_dicts.append(p)
                    from datetime import datetime
                    db.update_upstream_key(api_key, {
                        "points": f"{key_remain:.0f}/{key_total:.0f}",
                        "packages": packages_dicts,
                        "points_updated_at": datetime.now().isoformat(),
                    })
                    k["points"] = f"{key_remain:.0f}/{key_total:.0f}"
                    k["packages"] = packages_dicts
            except Exception as e:
                _log.getLogger(__name__).warning("proxy/quota: Key %s 实时查询失败: %s", api_key[:16], e)
            updated_keys.append(k)
        keys = updated_keys

    accounts = []
    total_remaining = 0.0
    total_credits = 0.0

    for k in keys:
        packages = k.get("packages", []) or []
        key_total = 0.0
        key_remain = 0.0

        pkg_list = []
        for pkg in packages:
            if not isinstance(pkg, dict):
                continue
            remain = float(pkg.get("cycle_remain", 0))
            total = float(pkg.get("cycle_size", 0))
            if total <= 0 and remain <= 0:
                continue
            # 显示用的 total：如果 cycle_size 缺失，用 cycle_remain 代替（旧数据兼容）
            display_total = total if total > 0 else remain
            # 汇总用的 total：只有真实的 cycle_size 才参与汇总，否则用 points 兜底
            if total > 0:
                key_total += total
            key_remain += remain

            # 计算过期天数
            days_left = -1
            cycle_end = str(pkg.get("cycle_end", ""))
            if cycle_end:
                try:
                    from datetime import datetime
                    ed = datetime.strptime(cycle_end.replace("T", " ").replace("Z", ""), "%Y-%m-%d %H:%M:%S")
                    days_left = max(0, (ed - datetime.now()).days)
                except Exception:
                    try:
                        ed = datetime.fromisoformat(cycle_end.replace("Z", "+00:00"))
                        days_left = max(0, (ed - datetime.now()).days)
                    except Exception:
                        pass

            pkg_list.append({
                "name": pkg.get("package_name", pkg.get("name", "未知套餐")),
                "type": pkg.get("type", pkg.get("type_label", "?")),
                "remain": remain,
                "total": display_total,
                "remainPercent": round(remain / display_total * 100, 1) if display_total > 0 else 0,
                "cycle": pkg.get("cycle_start", "")[:7] if pkg.get("cycle_start") else "--",
                "daysLeft": days_left,
            })

        # 从 points 字符串补充
        pts = k.get("points", "")
        if pts and "/" in pts and key_total == 0:
            try:
                parts = pts.split("/")
                key_remain = float(parts[0])
                key_total = float(parts[1])
            except (ValueError, IndexError):
                pass

        if key_total > 0:
            total_remaining += key_remain
            total_credits += key_total

        label = k.get("label", k.get("key_id", "")[:8])
        accounts.append({
            "name": label,
            "totalRemain": key_remain,
            "totalQuota": key_total,
            "remainPercent": round(key_remain / key_total * 100, 1) if key_total > 0 else 0,
            "packages": pkg_list,
            "status": k.get("status", "active"),
        })

    return {
        "success": True,
        "source": "server",
        "summary": {
            "totalRemain": total_remaining,
            "totalCredits": total_credits,
            "accountCount": len(accounts),
        },
        "accounts": accounts,
    }


# ─── 请求日志接口 ───
@router.get("/proxy/logs")
def proxy_logs(since: float = 0, limit: int = 50, page: int = 1):
    """获取代理请求日志（分页，最新的在前）"""
    db = _get_db()
    result = db.get_request_logs(since=since, limit=limit, page=page, reverse=True)
    return {
        "success": True,
        **result,
    }


# --- 仪表盘统计 API ---

@router.get("/proxy/stats/overview")
def proxy_stats_overview():
    """获取全局仪表盘总览数据"""
    db = _get_db()
    return {
        "success": True,
        **db.get_stats_overview(),
    }


@router.get("/proxy/stats/calendar")
def proxy_stats_calendar(months: int = 4):
    """获取日历热力图数据（最近 N 个月）"""
    db = _get_db()
    return {
        "success": True,
        "data": db.get_calendar_data(months),
    }


@router.get("/proxy/stats/daily")
def proxy_stats_daily():
    """获取所有每日聚合数据"""
    db = _get_db()
    return {
        "success": True,
        "data": db.get_all_daily_stats(),
    }
