#!/usr/bin/env bash
# Manage the local ComfyUI server used for SDXL image (and later LTX video) gen.
#   ./scripts/comfy.sh start | stop | status
# Models live on the NVMe (see ~/comfyui-app/extra_model_paths.yaml); outputs go
# to /mnt/nvme/yt-agent/output. The pipeline auto-uses images only if this is up.
set -euo pipefail
VENV=/home/orinx/comfyui-venv
APP=/home/orinx/comfyui-app
OUT=/mnt/nvme/yt-agent/output
LOG=/tmp/comfyui.log

case "${1:-status}" in
  start)
    if curl -fsS http://127.0.0.1:8188/system_stats >/dev/null 2>&1; then
      echo "ComfyUI already running on :8188"; exit 0
    fi
    echo "starting ComfyUI (log: $LOG)..."
    nohup "$VENV/bin/python" "$APP/main.py" --listen 127.0.0.1 --port 8188 \
      --output-directory "$OUT" >"$LOG" 2>&1 &
    for i in $(seq 1 60); do
      curl -fsS http://127.0.0.1:8188/system_stats >/dev/null 2>&1 && { echo "ready on http://127.0.0.1:8188"; exit 0; }
      sleep 1
    done
    echo "timed out waiting for ComfyUI; see $LOG"; exit 1 ;;
  stop)
    pkill -f "comfyui-app/main.py" && echo "stopped" || echo "not running" ;;
  status)
    curl -fsS http://127.0.0.1:8188/system_stats >/dev/null 2>&1 && echo "running on :8188" || echo "not running" ;;
  *) echo "usage: ./scripts/comfy.sh start|stop|status"; exit 1 ;;
esac
