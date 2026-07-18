"""Playground API — model testing with image support

POST /api/playground/chat
    Send a chat request with optional image through the proxy.

GET /api/playground/models
    Return supported model list.
"""

import logging
import secrets

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

import requests

from src.utils.store import load_setting

logger = logging.getLogger(__name__)
router = APIRouter(tags=["playground"])


class ChatRequest(BaseModel):
    model: str = "auto"
    prompt: str = "Hello"
    image_base64: Optional[str] = None


def _get_proxy_port() -> int:
    return int(load_setting("proxyPort", "8867"))


@router.get("/playground/models")
def playground_models():
    from src.modules.proxy_server import SUPPORTED_MODELS
    return {"success": True, "models": SUPPORTED_MODELS}


@router.post("/playground/chat")
def playground_chat(req: ChatRequest):
    from src.modules.proxy_server import ProxyDatabase
    db = ProxyDatabase.get_instance()

    sub_keys = db.get_sub_api_keys()
    sub_key = None
    auto_created = False
    if sub_keys:
        sub_key = sub_keys[0]
    if not sub_key:
        key_id = f"playground_{secrets.token_hex(8)}"
        api_key = f"sk-playground-{secrets.token_hex(16)}"
        sub_key = {
            "key_id": key_id,
            "api_key": api_key,
            "label": "Playground (auto)",
            "is_active": True,
            "max_usage": 0,
            "used_count": 0,
            "allowed_models": [],
            "allowed_key_ids": [],
            "key_mode": 1,
        }
        db.add_sub_api_key(sub_key)
        auto_created = True
        logger.info(f"[playground] auto-created sub-key: {key_id}")

    messages = [{"role": "user", "content": []}]
    content = messages[0]["content"]

    if req.image_base64:
        data_uri = req.image_base64
        if not data_uri.startswith("data:"):
            data_uri = f"data:image/png;base64,{data_uri}"
        content.append({"type": "input_image", "url": data_uri})

    content.append({"type": "text", "text": req.prompt})

    body = {"model": req.model, "messages": messages, "stream": False}

    port = _get_proxy_port()
    url = f"http://127.0.0.1:{port}/v1/chat/completions"

    try:
        resp = requests.post(
            url, json=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {sub_key['api_key']}",
            },
            timeout=120,
        )
    except requests.ConnectionError:
        raise HTTPException(status_code=503, detail=f"Proxy not running on port {port}. Start it first.")
    except requests.Timeout:
        raise HTTPException(status_code=504, detail="Request timeout (120s)")

    if resp.status_code != 200:
        logger.warning(f"[playground] proxy returned {resp.status_code}: {resp.text[:300]}")
        raise HTTPException(status_code=resp.status_code, detail=f"Proxy error {resp.status_code}: {resp.text[:300]}")

    data = resp.json()
    choices = data.get("choices", [])
    msg = choices[0].get("message", {}) if choices else {}
    usage = data.get("usage", {})

    return {
        "success": True,
        "model": data.get("model", req.model),
        "content": msg.get("content", ""),
        "reasoning_content": msg.get("reasoning_content", ""),
        "usage": {
            "prompt_tokens": usage.get("prompt_tokens", 0),
            "completion_tokens": usage.get("completion_tokens", 0),
            "total_tokens": usage.get("total_tokens", 0),
        },
        "auto_created_key": auto_created,
    }
