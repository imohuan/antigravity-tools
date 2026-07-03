"""Proxy server control API routes"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
import threading
import logging

from src.modules.proxy_server import ProxyServer, ProxyDatabase

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
            "id": k.get("key_id", ""),
            "prefix": (k.get("api_key", "") or "")[:16],
            "suffix": (k.get("api_key", "") or "")[-4:],
            "account": k.get("label", ""),
            "quota_remaining": _parse_quota_from_key(k),
            "active": k.get("status") == "active",
            "status": k.get("status", "active"),
        } for k in keys],
    }


@router.post("/proxy/start")
def proxy_start():
    """Start the proxy server"""
    global _proxy_server, _proxy_thread
    if _proxy_server and _proxy_server.is_running:
        return {"success": True, "message": "Proxy already running"}
    try:
        _proxy_server = ProxyServer(port=8867)
        _proxy_thread = threading.Thread(target=_proxy_server.start, daemon=True)
        _proxy_thread.start()
        return {"success": True, "message": "Proxy started on port 8867"}
    except Exception as e:
        return {"success": False, "error": str(e)}


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
    """Remove a key from the pool"""
    db = _get_db()
    db.delete_upstream_key(key_id)
    return {"success": True}


@router.post("/proxy/keys/{key_id}/toggle")
def proxy_toggle_key(key_id: str):
    """Toggle a key's active status"""
    db = _get_db()
    keys = db.get_upstream_keys()
    key = next((k for k in keys if k.get("key_id") == key_id), None)
    if not key:
        raise HTTPException(status_code=404, detail="Key not found")
    current = key.get("status", "active")
    new_status = "disabled" if current in ("active", "exhausted", "cooldown", "rate_limited") else "active"
    db.update_upstream_key(key_id, {"status": new_status})
    return {"success": True, "active": new_status == "active"}
