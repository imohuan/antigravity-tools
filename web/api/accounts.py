"""Account management API routes"""

from typing import List, Optional
from datetime import datetime
import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

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


class ImportAccountItem(BaseModel):
    method: str  # "apikey" | "jwt"
    api_key: Optional[str] = None
    access_token: Optional[str] = None
    auth_token: Optional[str] = None  # alias for access_token (export compatibility)
    uid: Optional[str] = None
    domain: Optional[str] = "www.codebuddy.cn"
    nickname: Optional[str] = None


class ImportRequest(BaseModel):
    items: List[ImportAccountItem]


class ExportRequest(BaseModel):
    uids: List[str]


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
            "has_api_key": bool(a.api_key),
            "auth_token": a.auth_token[:20] + "..." if len(a.auth_token) > 20 else a.auth_token,
            "has_auth_token": bool(a.auth_token),
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


@router.post("/accounts/import")
def import_accounts(req: ImportRequest):
    """Bulk import accounts from JSON config"""
    total = len(req.items)
    if total == 0:
        return {"success": True, "total": 0, "added": 0, "failed": 0, "errors": []}

    added = 0
    failed = 0
    errors = []
    existing_uids = {a.uid for a in load_accounts()}

    for item in req.items:
        try:
            # Normalize: accept both access_token and auth_token
            access_token = item.access_token or getattr(item, 'auth_token', None)
            api_key = item.api_key

            if item.method == "apikey":
                if not api_key or not api_key.startswith("ck_"):
                    errors.append(f"Invalid API Key (must start with ck_): {item.nickname or 'unknown'}")
                    failed += 1
                    continue
                account = Account(
                    platform=Platform.CODEBUDDY,
                    status=AccountStatus.ACTIVE,
                    plan_type=PlanType.FREE,
                    created_at=datetime.now(),
                )
                account.api_key = api_key
                account.auth_token = api_key
                client = ApiClient.from_api_key(api_key)
                qr = client.get_user_resource()
                if not qr.get("success"):
                    errors.append(f"API Key verification failed for {item.nickname or 'unknown'}: {qr.get('error', 'unknown')}")
                    failed += 1
                    continue
                account.uid = api_key[:32]
                account.quota.credits_remaining = qr.get("remaining_credits", 0)
                account.quota.credits_total = qr.get("total_credits", 0)
                account.nickname = item.nickname or f"Key-{api_key[:8]}"

            elif item.method == "jwt":
                if not access_token:
                    errors.append(f"Access token required for {item.nickname or 'unknown'}")
                    failed += 1
                    continue
                if not item.uid:
                    errors.append(f"UID required for {item.nickname or 'unknown'}")
                    failed += 1
                    continue
                account = Account(
                    platform=Platform.CODEBUDDY,
                    status=AccountStatus.ACTIVE,
                    plan_type=PlanType.FREE,
                    created_at=datetime.now(),
                )
                account.auth_token = access_token
                account.uid = item.uid
                account.domain = item.domain or "www.codebuddy.cn"
                client = ApiClient(access_token=access_token, uid=item.uid, domain=account.domain)
                qr = client.get_user_resource()
                if not qr.get("success"):
                    errors.append(f"JWT verification failed for {item.nickname or 'unknown'}: {qr.get('error', 'unknown')}")
                    failed += 1
                    continue
                account.quota.credits_remaining = qr.get("remaining_credits", 0)
                account.quota.credits_total = qr.get("total_credits", 0)
                account.nickname = item.nickname or item.uid[:12]

            else:
                errors.append(f"Unknown method: {item.method}")
                failed += 1
                continue

            if account.uid in existing_uids:
                errors.append(f"Duplicate account skipped: {account.nickname}")
                failed += 1
                continue

            save_account(account)
            existing_uids.add(account.uid)
            added += 1
            logger.info(f"Imported account: {account.display_name}")
        except Exception as e:
            errors.append(f"Import error for {item.nickname or 'unknown'}: {str(e)}")
            failed += 1

    return {"success": True, "total": total, "added": added, "failed": failed, "errors": errors}


@router.post("/accounts/export")
def export_accounts(req: ExportRequest):
    """Export selected accounts with full credentials"""
    accounts = load_accounts()
    export_map = {a.uid: a for a in accounts}
    result = []
    not_found = []

    for uid in req.uids:
        a = export_map.get(uid)
        if not a:
            not_found.append(uid)
            continue
        result.append({
            "method": "apikey" if a.api_key and a.api_key.startswith("ck_") else "jwt",
            "uid": a.uid,
            "nickname": a.nickname or a.uid,
            "platform": a.platform.value,
            "status": a.status.value,
            "plan_type": a.plan_type.value,
            "domain": a.domain,
            "api_key": a.api_key,
            "access_token": a.auth_token,
            "auth_token": a.auth_token,
        })

    return {"success": True, "accounts": result, "not_found": not_found}
