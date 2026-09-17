#!/usr/bin/env bash
# NiveshRakshak — one-command start.
#   ./run.sh            → http://127.0.0.1:8300
#   PORT=9000 ./run.sh  → custom port
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -d .venv ]; then
  echo "→ creating venv…"
  python3 -m venv .venv
  .venv/bin/pip install --quiet --upgrade pip
fi
if ! .venv/bin/python -c "import fastapi, rapidfuzz, xlrd, PIL" 2>/dev/null; then
  echo "→ installing dependencies…"
  .venv/bin/pip install --quiet -r requirements.txt
fi

# system tools the pipeline shells out to (OCR + QR)
for tool in tesseract zbarimg; do
  command -v "$tool" >/dev/null || echo "! warning: $tool not found — screenshot/QR intake will degrade (text checks still work)"
done

PORT="${PORT:-8300}"
HOST="${HOST:-127.0.0.1}"
echo "→ NiveshRakshak starting on http://$HOST:$PORT  (registry mirror refreshes in background if stale)"
exec .venv/bin/python -m uvicorn server.app:app --host "$HOST" --port "$PORT"
