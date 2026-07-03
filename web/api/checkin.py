"""Checkin API routes"""

from fastapi import APIRouter
from src.modules.checkin import CheckinManager
from src.utils.store import load_accounts

router = APIRouter(tags=["checkin"])
_manager = CheckinManager()


@router.post("/checkin/all")
def checkin_all():
    """Batch checkin all accounts"""
    accounts = load_accounts()
    result = _manager.checkin_all(accounts)
    return result


@router.post("/checkin/{uid}")
def checkin_one(uid: str):
    """Checkin a single account"""
    accounts = load_accounts()
    account = next((a for a in accounts if a.uid == uid), None)
    if not account:
        return {"success": False, "error": "Account not found"}
    result = _manager.checkin_account(account)
    return result
