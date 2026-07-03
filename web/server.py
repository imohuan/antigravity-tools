"""Antigravity Tools Web Server

FastAPI + static SPA frontend.
Start with: python -m web.server
"""

import os
import sys
import webbrowser
import threading
from pathlib import Path

# Ensure project root in sys.path so `from src.xxx` works
_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from fastapi import FastAPI
from fastapi.responses import FileResponse
import uvicorn

from src.utils.store import init_db

app = FastAPI(title="Antigravity Tools", version="1.0.0")

# --- Mount API routes (registered in each module) ---
from web.api.accounts import router as accounts_router
from web.api.checkin import router as checkin_router
from web.api.quota import router as quota_router
from web.api.proxy import router as proxy_router

app.include_router(accounts_router, prefix="/api")
app.include_router(checkin_router, prefix="/api")
app.include_router(quota_router, prefix="/api")
app.include_router(proxy_router, prefix="/api")

# --- Static files (SPA) ---
_static_dir = Path(__file__).parent / "static"
_static_dir.mkdir(exist_ok=True)


@app.get("/")
async def index():
    return FileResponse(_static_dir / "index.html")


def main():
    """Entry point for `python -m web.server`"""
    init_db()
    port = int(os.environ.get("PORT", 8866))
    host = os.environ.get("HOST", "0.0.0.0")

    print(f"  Antigravity Tools Web UI")
    print(f"  http://{host}:{port}")
    print(f"  Press Ctrl+C to stop")

    def _open_browser():
        import time
        time.sleep(1)
        url = f"http://127.0.0.1:{port}"
        try:
            webbrowser.open(url)
        except Exception:
            pass

    threading.Thread(target=_open_browser, daemon=True).start()

    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
