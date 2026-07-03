"""Account management API routes"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
from datetime import datetime
import logging

from src.models import Account, Platform, AccountStatus, PlanType
from src.utils.store import load_accounts, save_account, delete_account
from src.modules.api_client import ApiClient

logger = logging.getLogger(__name__)
router = APIRouter(tags=["accounts"])


class AddAccountRequest(BaseModel):
    method: str  # "apikey" | "jwt"
    api_key: Optional[str] = None
    access_token: Optional[str] = None
    uid: Optional[str] = None
    domain: Optional[str] = "www.codebuddy.cn"
    nickname: Optional[str] = None


@router.get("/accounts")
def list_accounts():
    """Get all accounts"""
    accounts = load_accounts()
    result = []
    for a in accounts:
        result.append({
            "uid": a.uid,
            "nickname": a.nickname or a.uid,
            "platform": a.platform.value,
            "status": a.status.value,
            "plan_type": a.plan_type.value,
            "api_key": a.api_key[:20] + "..." if len(a.api_key) > 20 else a.api_key,
            "quota_remaining": a.quota.credits_remaining,
            "quota_total": a.quota.credits_total,
            "checked_today": a.checkin.checked_today,
            "streak_days": a.checkin.streak_days,
        })
    return {"accounts": result, "total": len(result)}


@router.post("/accounts/add")
def add_account(req: AddAccountRequest):
    """Add a new account via API Key or JWT"""
    account = Account(
        platform=Platform.CODEBUDDY,
        status=AccountStatus.ACTIVE,
        plan_type=PlanType.FREE,
        created_at=datetime.now(),
    )

    if req.method == "apikey":
        if not req.api_key or not req.api_key.startswith("ck_"):
            raise HTTPException(status_code=400, detail="Invalid API Key (must start with ck_)")
        account.api_key = req.api_key
        account.auth_token = req.api_key
        # Verify the key works
        client = ApiClient.from_api_key(req.api_key)
        qr = client.get_user_resource()
        if not qr.get("success"):
            raise HTTPException(status_code=400, detail=f"API Key verification failed: {qr.get('error', 'unknown')}")
        account.uid = req.api_key[:32]
        account.quota.credits_remaining = qr.get("remaining_credits", 0)
        account.quota.credits_total = qr.get("total_credits", 0)
        account.nickname = req.nickname or f"Key-{req.api_key[:8]}"

    elif req.method == "jwt":
        if not req.access_token:
            raise HTTPException(status_code=400, detail="Access token is required for JWT method")
        if not req.uid:
            raise HTTPException(status_code=400, detail="UID is required for JWT method")
        account.auth_token = req.access_token
        account.uid = req.uid
        account.domain = req.domain or "www.codebuddy.cn"
        # Verify
        client = ApiClient(access_token=req.access_token, uid=req.uid, domain=account.domain)
        qr = client.get_user_resource()
        if not qr.get("success"):
            raise HTTPException(status_code=400, detail=f"JWT verification failed: {qr.get('error', 'unknown')}")
        account.quota.credits_remaining = qr.get("remaining_credits", 0)
        account.quota.credits_total = qr.get("total_credits", 0)
        account.nickname = req.nickname or req.uid[:12]

    else:
        raise HTTPException(status_code=400, detail=f"Unknown method: {req.method}")

    save_account(account)
    logger.info(f"Account added: {account.display_name}")
    return {"success": True, "uid": account.uid, "nickname": account.nickname}


@router.post("/accounts/{uid}/delete")
def remove_account(uid: str):
    """Delete an account"""
    accounts = load_accounts()
    target = next((a for a in accounts if a.uid == uid), None)
    if not target:
        raise HTTPException(status_code=404, detail="Account not found")
    delete_account(uid)
    logger.info(f"Account deleted: {target.display_name}")
    return {"success": True}
