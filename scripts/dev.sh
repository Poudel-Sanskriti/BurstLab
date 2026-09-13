#!/usr/bin/env bash
set -euo pipefail
PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_ROOT"
if [ ! -x .venv/bin/python ]; then
  python3 -m venv .venv
fi
if ! .venv/bin/python -c 'import fastapi, uvicorn, boto3, qrcode, httpx' 2>/dev/null; then
  if command -v uv >/dev/null 2>&1; then
    uv pip install --python .venv/bin/python -r requirements.txt
  else
    .venv/bin/python -m pip install -r requirements.txt
  fi
fi
if [ ! -d frontend/node_modules ]; then
  npm --prefix frontend ci --no-audit --no-fund
fi
npm --prefix frontend run build
echo "BurstLab is ready at http://127.0.0.1:8000 — AWS experiments"
exec .venv/bin/python -m uvicorn backend.app:app --host 127.0.0.1 --port 8000
