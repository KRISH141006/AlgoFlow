#!/bin/sh
set -eu
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ]; then
  python3 -m venv .venv
fi
if ! .venv/bin/python -c 'import fastapi,uvicorn,multipart,bleach' >/dev/null 2>&1; then
  .venv/bin/python -m pip install -r requirements.txt
fi
if [ ! -d frontend/node_modules ]; then
  (cd frontend && npm ci)
fi
(cd frontend && npm run build)
.venv/bin/python scripts/prepare_data.py
export ALGOFLOW_DB="${ALGOFLOW_DB:-$PWD/data/demo.db}"
printf '\nAlgoFlow: http://127.0.0.1:%s\nDatabase: %s\n\n' "${PORT:-3000}" "$ALGOFLOW_DB"
exec .venv/bin/python -m uvicorn backend.main:app --host 127.0.0.1 --port "${PORT:-3000}"
