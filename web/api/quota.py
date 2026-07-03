"""Quota query API routes"""

from fastapi import APIRouter
from src.utils.store import load_accounts, save_account
from src.modules.api_client import ApiClient

router = APIRouter(tags=["quota"])


@router.post("/quota/all")
def query_all_quotas():
    """Query quota for all accounts"""
    accounts = load_accounts()
    results = []
    total_remaining = 0.0
    total_credits = 0.0

    for account in accounts:
        if account.api_key and account.api_key.startswith("ck_"):
            client = ApiClient.from_api_key(account.api_key)
        elif account.auth_token:
            client = ApiClient(access_token=account.auth_token, uid=account.uid, domain=account.domain)
        else:
            results.append({
                "uid": account.uid, "nickname": account.display_name,
                "success": False, "error": "No credentials"
            })
            continue

        qr = client.get_user_resource()
        if qr.get("success"):
            account.quota.credits_remaining = qr.get("remaining_credits", 0)
            account.quota.credits_total = qr.get("total_credits", 0)
            total_remaining += qr.get("remaining_credits", 0)
            total_credits += qr.get("total_credits", 0)
            save_account(account)
            results.append({
                "uid": account.uid,
                "nickname": account.display_name,
                "success": True,
                "remaining_credits": qr.get("remaining_credits", 0),
                "total_credits": qr.get("total_credits", 0),
                "packages": [{
                    "name": p.package_name,
                    "type": p.type_label,
                    "remain": p.cycle_remain,
                    "total": p.cycle_size,
                    "cycle_start": p.cycle_start,
                    "cycle_end": p.cycle_end,
                } for p in qr.get("packages", [])],
            })
        else:
            results.append({
                "uid": account.uid, "nickname": account.display_name,
                "success": False, "error": qr.get("error", "Query failed")
            })

    return {
        "total_remaining": total_remaining,
        "total_credits": total_credits,
        "account_count": len(accounts),
        "details": results,
    }


@router.post("/quota/{uid}")
def query_one_quota(uid: str):
    """Query quota for a single account"""
    accounts = load_accounts()
    account = next((a for a in accounts if a.uid == uid), None)
    if not account:
        return {"success": False, "error": "Account not found"}

    if account.api_key and account.api_key.startswith("ck_"):
        client = ApiClient.from_api_key(account.api_key)
    elif account.auth_token:
        client = ApiClient(access_token=account.auth_token, uid=account.uid, domain=account.domain)
    else:
        return {"success": False, "error": "No credentials"}

    qr = client.get_user_resource()
    if qr.get("success"):
        account.quota.credits_remaining = qr.get("remaining_credits", 0)
        account.quota.credits_total = qr.get("total_credits", 0)
        save_account(account)
        return {
            "success": True,
            "uid": account.uid,
            "nickname": account.display_name,
            "remaining_credits": qr.get("remaining_credits", 0),
            "total_credits": qr.get("total_credits", 0),
            "packages": [{
                "name": p.package_name,
                "type": p.type_label,
                "remain": p.cycle_remain,
                "total": p.cycle_size,
                "cycle_start": p.cycle_start,
                "cycle_end": p.cycle_end,
            } for p in qr.get("packages", [])],
        }
    return {"success": False, "error": qr.get("error", "Query failed")}
