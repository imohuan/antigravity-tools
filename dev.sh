#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$SCRIPT_DIR/.venv"

if [ ! -d "$VENV_DIR" ]; then
    echo "Virtual environment not found. Run ./install.sh first."
    exit 1
fi

source "$VENV_DIR/bin/activate"
cd "$SCRIPT_DIR"
echo "==> Starting Antigravity Tools Web Server..."
python -m web.server