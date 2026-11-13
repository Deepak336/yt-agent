#!/usr/bin/env bash
# Generate a video from a source (PDF / text / audio / video), behind the approval gate.
#
# Usage:
#   ./run.sh <source> [duration] [--channel NAME] [--count N] [--output DIR] [--work DIR] [--visual MODE]
#     <source>   path to .pdf/.txt, or an audio/video file (.mp4/.mkv/.mov/.mp3/...)
#     [duration] short (default) | 60s | 90 | 3min | 5min  (long-form => 16:9 + per-beat visuals)
#     --channel  finance (default) | education | spirituality   (profiles in channels/)
#     --count    how many lesson videos to make from the source (default 1)
#     --output   where the finished video + metadata go (e.g. /mnt/nvme/yt-agent/output)
#     --work     where intermediates go (default: data/work; put on NVMe to spare eMMC)
#     --visual   auto (default) | image | chart | clip | mixed | none
#                clip  = LTX AI video bg on EVERY beat (SLOW: ~2min/beat at 30W)
#                mixed = SDXL stills + LTX on a few key beats (--clip-beats, default 3)
#     --clip-beats N  mixed mode: how many beats get an LTX clip (default 3)
#
# Examples:
#   ./run.sh data/pdfs/book.pdf 3min --channel education --output /mnt/nvme/yt-agent/output
#   ./run.sh data/pdfs/book.pdf short --count 3 --channel finance
#
# Preview WITH SOUND:  ./scripts/preview.sh <output-dir>   then open http://<orin-ip>:8000
set -euo pipefail
cd "$(dirname "$0")"

SRC="${1:-}"
if [ -z "$SRC" ] || [[ "$SRC" == --* ]]; then
  echo "usage: ./run.sh <source .pdf/.txt/.mp4/...> [short|60s|3min|5min] [--output DIR] [--work DIR]"
  echo "sources in data/pdfs/:"; ls -1 data/pdfs/ 2>/dev/null | grep -vE '^\.gitkeep$' || echo "  (none)"
  exit 1
fi
shift
DURATION="short"; OUTPUT=""; WORK=""; VISUAL=""; CHANNEL=""; COUNT=""; CLIPBEATS=""
while [ $# -gt 0 ]; do
  case "$1" in
    --output)     OUTPUT="$2"; shift 2 ;;
    --work)       WORK="$2"; shift 2 ;;
    --visual)     VISUAL="$2"; shift 2 ;;
    --channel)    CHANNEL="$2"; shift 2 ;;
    --count)      COUNT="$2"; shift 2 ;;
    --clip-beats) CLIPBEATS="$2"; shift 2 ;;
    *)            DURATION="$1"; shift ;;
  esac
done
[ -f "$SRC" ] || { echo "error: source not found: $SRC"; exit 1; }

# start ollama if needed
if ! curl -fsS http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
  echo "starting ollama..."; (ollama serve >/tmp/ollama.log 2>&1 &) ; sleep 3
fi

source .venv/bin/activate
ARGS=(--source "$SRC" --duration "$DURATION")
[ -n "$OUTPUT" ] && ARGS+=(--output "$OUTPUT")
[ -n "$WORK" ] && ARGS+=(--work "$WORK")
[ -n "$VISUAL" ] && ARGS+=(--visual "$VISUAL")
[ -n "$CHANNEL" ] && ARGS+=(--channel "$CHANNEL")
[ -n "$COUNT" ] && ARGS+=(--count "$COUNT")
[ -n "$CLIPBEATS" ] && ARGS+=(--clip-beats "$CLIPBEATS")
python orchestrator.py "${ARGS[@]}"

OUTDIR="${OUTPUT:-data/output}"
echo
echo "Latest output: $(ls -t "$OUTDIR"/short-*.mp4 2>/dev/null | head -1)"
echo "Preview with sound:  ./scripts/preview.sh \"$OUTDIR\"  ->  http://$(hostname -I | awk '{print $1}'):8000"
