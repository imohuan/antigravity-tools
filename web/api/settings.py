"""Settings API routes"""

from fastapi import APIRouter
from pydantic import BaseModel

from src.utils.store import save_setting, load_setting, load_all_settings

router = APIRouter(tags=["settings"])


class SettingsPayload(BaseModel):
    webPort: int = 8866
    proxyPort: int = 8867
    httpProxy: str = ""
    autoStartProxy: bool = True


@router.get("/settings")
def get_settings():
    """读取所有 Web 设置"""
    all_settings = load_all_settings()
    return {
        "webPort": int(all_settings.get("webPort", "8866")),
        "proxyPort": int(all_settings.get("proxyPort", "8867")),
        "httpProxy": all_settings.get("httpProxy", ""),
        "autoStartProxy": all_settings.get("autoStartProxy", "True") == "True",
    }


@router.post("/settings")
def save_settings(payload: SettingsPayload):
    """保存 Web 设置"""
    save_setting("webPort", str(payload.webPort))
    save_setting("proxyPort", str(payload.proxyPort))
    save_setting("httpProxy", payload.httpProxy)
    save_setting("autoStartProxy", str(payload.autoStartProxy))
    return {"success": True, "message": "设置已保存"}
