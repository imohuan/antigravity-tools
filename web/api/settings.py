"""Settings API routes"""

import json

from src.modules.proxy_server import DEFAULT_SYSTEM_PROMPT_COMPATIBILITY_REPLACEMENTS

from fastapi import APIRouter
from pydantic import BaseModel

from src.utils.store import save_setting, load_setting, load_all_settings

router = APIRouter(tags=["settings"])


class SettingsPayload(BaseModel):
    webPort: int = 8866
    proxyPort: int = 8867
    httpProxy: str = ""
    autoStartProxy: bool = True
    systemPromptSensitiveEnabled: bool = True
    systemPromptSensitiveConfig: str = ""


@router.get("/settings")
def get_settings():
    """读取所有 Web 设置"""
    all_settings = load_all_settings()
    return {
        "webPort": int(all_settings.get("webPort", "8866")),
        "proxyPort": int(all_settings.get("proxyPort", "8867")),
        "httpProxy": all_settings.get("httpProxy", ""),
        "autoStartProxy": all_settings.get("autoStartProxy", "True") == "True",
        "systemPromptSensitiveEnabled": all_settings.get("system_prompt_sensitive_enabled", "True") == "True",
        "systemPromptSensitiveDefault": DEFAULT_SYSTEM_PROMPT_COMPATIBILITY_REPLACEMENTS,
        "systemPromptSensitiveRules": _parse_rules(all_settings.get("system_prompt_sensitive_replacements", "")),
    }


@router.post("/settings")
def save_settings(payload: SettingsPayload):
    """保存 Web 设置"""
    save_setting("webPort", str(payload.webPort))
    save_setting("proxyPort", str(payload.proxyPort))
    save_setting("httpProxy", payload.httpProxy)
    save_setting("autoStartProxy", str(payload.autoStartProxy))
    save_setting("system_prompt_sensitive_enabled", str(payload.systemPromptSensitiveEnabled))
    if payload.systemPromptSensitiveConfig:
        try:
            cfg = json.loads(payload.systemPromptSensitiveConfig)
        except json.JSONDecodeError:
            cfg = []
        if isinstance(cfg, dict):
            rules = cfg.get("rules", [])
        elif isinstance(cfg, list):
            rules = cfg
        else:
            rules = []
        save_setting("system_prompt_sensitive_replacements", json.dumps(rules, ensure_ascii=False))
    return {"success": True, "message": "设置已保存"}

def _parse_rules(raw_value: str) -> list[dict]:
    "从 DB 配置中解析出规则列表 [{key, value}, ...]"
    try:
        parsed = json.loads(raw_value) if raw_value else {}
    except json.JSONDecodeError:
        return list(DEFAULT_SYSTEM_PROMPT_COMPATIBILITY_REPLACEMENTS)
    if isinstance(parsed, dict):
        rules = parsed.get("rules", [])
    elif isinstance(parsed, list):
        rules = parsed
    else:
        return list(DEFAULT_SYSTEM_PROMPT_COMPATIBILITY_REPLACEMENTS)
    out = []
    for r in rules:
        if not isinstance(r, dict):
            continue
        key = str(r.get("key", "")).strip()
        value = str(r.get("value", ""))
        if key:
            out.append({"key": key, "value": value})
    if not out:
        return list(DEFAULT_SYSTEM_PROMPT_COMPATIBILITY_REPLACEMENTS)
    return out
