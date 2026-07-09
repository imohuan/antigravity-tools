"""Proxy server control API routes"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
import threading
import logging

from src.modules.proxy_server import ProxyServer, ProxyDatabase
from src.utils.store import load_accounts

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
        "port": 8867,
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
        _proxy_server = ProxyServer(port=8867, default_key_mode=req.strategy)
        _proxy_thread = threading.Thread(target=_proxy_server.start, daemon=True)
        _proxy_thread.start()
        return {"success": True, "message": "Proxy started on port 8867"}
    except Exception as e:
        return {"success": False, "error": str(e)}


class SetStrategyRequest(BaseModel):
    strategy: int = 1

@router.post("/proxy/strategy")
def proxy_set_strategy(req: SetStrategyRequest):
    """实时更新全局默认策略，无需重启代理"""
    from src.modules.proxy_server import ProxyRequestHandler
    ProxyRequestHandler.default_key_mode = req.strategy
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
