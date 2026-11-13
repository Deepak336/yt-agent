#!/usr/bin/env bash
# Resilient, RESUMABLE download of LTX-Video 2B (v0.9.5) to the NVMe.
# Survives SSH / Claude-session drops: `start` detaches the download with setsid,
# so it keeps running even if the controlling session dies.
#
#   ./scripts/fetch_ltx.sh start     # detach + begin/resume the download
#   ./scripts/fetch_ltx.sh status    # show progress (safe anytime)
#   ./scripts/fetch_ltx.sh t5        # (optional) also fetch the T5 text-encoder fallback
#   ./scripts/fetch_ltx.sh run       # foreground run (used internally by `start`)
#
# Model lands at: /mnt/nvme/yt-agent/comfyui-models/checkpoints/ltx-video-2b-v0.9.5.safetensors
# (matches visuals/clip.py CKPT + extra_model_paths.yaml). HF resume metadata and the
# model file both live on the NVMe so the 11GB-free eMMC is never filled. Logs/status
# live on eMMC (~/yt-agent) so they stay readable even if the NVMe drops mid-download.
set -euo pipefail

HF=/home/orinx/comfyui-venv/bin/hf
REPO=Lightricks/LTX-Video
FILE=ltx-video-2b-v0.9.5.safetensors
T5_REPO=Lightricks/LTX-Video
T5_FILE=text_encoder/model.safetensors   # bundled encoder; checkpoint is all-in-one so this is optional
CKPT_DIR=/mnt/nvme/yt-agent/comfyui-models/checkpoints
T5_DIR=/mnt/nvme/yt-agent/comfyui-models/text_encoders
LOG="$HOME/yt-agent/ltx-download.log"
STATUS="$HOME/yt-agent/ltx-download.status"

require_nvme() {
  mountpoint -q /mnt/nvme || {
    echo "!! NVMe not mounted at /mnt/nvme."
    echo "   Run:  sudo ./scripts/nvme_mount.sh   (replug the USB-C SSD first if lsblk doesn't show it)"
    exit 1; }
}

case "${1:-status}" in
  start)
    require_nvme
    mkdir -p "$CKPT_DIR"
    echo "started $(date -Is)" > "$STATUS"
    setsid nohup "$0" run >"$LOG" 2>&1 < /dev/null &
    echo "LTX download detached (pid $!)."
    echo "  log:    $LOG"
    echo "  status: $STATUS"
    echo "Check progress any time:  ./scripts/fetch_ltx.sh status"
    ;;
  run)
    require_nvme
    mkdir -p "$CKPT_DIR"
    # Force classic HTTP transfer: the xet backend stalls badly on unauthenticated
    # downloads (many connections, ~0 throughput). Plain HTTP is slower-peak but
    # reliable and cleanly resumable to the .incomplete file on the NVMe.
    export HF_HUB_DISABLE_XET=1 HF_XET_DISABLE=1
    echo "=== LTX checkpoint download run $(date -Is) (xet disabled) ==="
    if "$HF" download "$REPO" "$FILE" --local-dir "$CKPT_DIR"; then
      echo "done $(date -Is) :: $FILE" > "$STATUS"
      echo "OK -> $CKPT_DIR/$FILE"
    else
      echo "FAILED $(date -Is) (network? rerun 'start' to resume)" > "$STATUS"
      exit 1
    fi
    ls -la "$CKPT_DIR/$FILE" 2>/dev/null || true
    ;;
  t5)
    require_nvme
    mkdir -p "$T5_DIR"
    echo "=== T5 text-encoder fallback download $(date -Is) ==="
    "$HF" download "$T5_REPO" "$T5_FILE" --local-dir "$T5_DIR"
    ls -la "$T5_DIR" 2>/dev/null || true
    ;;
  status)
    if [ -f "$STATUS" ]; then echo "--- status ---"; cat "$STATUS"; else echo "(no status file yet)"; fi
    if mountpoint -q /mnt/nvme; then
      echo "--- checkpoint on disk ---"
      ls -la "$CKPT_DIR/$FILE" 2>/dev/null || echo "(not downloaded yet)"
      du -sh "$CKPT_DIR/.cache" 2>/dev/null | sed 's/^/resume-cache: /' || true
      df -h /mnt/nvme | tail -1
    else
      echo "(NVMe not mounted — nothing to measure)"
    fi
    echo "--- last log lines ---"; tail -n 6 "$LOG" 2>/dev/null || echo "(no log yet)"
    echo "--- download process ---"; pgrep -af "hf download $REPO" || echo "(not running)"
    ;;
  *) echo "usage: $0 start|status|t5|run"; exit 1 ;;
esac
