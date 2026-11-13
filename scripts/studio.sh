#!/usr/bin/env bash
# Launch the yt-agent Studio web UI (LAN-accessible on :7860).
# Open http://<orin-ip>:7860 in your browser.
set -euo pipefail
cd "$(dirname "$0")/.."

# ensure ollama (LLM) is up
if ! curl -fsS http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
  echo "starting ollama..."; (ollama serve >/tmp/ollama.log 2>&1 &) ; sleep 3
fi
# optional: start ComfyUI so "auto"/"image" visuals work (comment out to skip)
./scripts/comfy.sh start || echo "(ComfyUI not started — studio will fall back to charts)"

source .venv/bin/activate
echo "Studio at: http://$(hostname -I | awk '{print $1}'):7860"
exec python studio.py
