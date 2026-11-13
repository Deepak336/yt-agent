#!/usr/bin/env bash
# LAN preview server so you can watch outputs WITH SOUND in a browser.
# (VNC carries no audio; a browser plays H.264+AAC mp4 with sound.)
#   ./scripts/preview.sh [dir] [port]      # default dir=data/output, port=8000
# Then on Windows open:  http://<orin-ip>:<port>  and click a video.
set -euo pipefail
cd "$(dirname "$0")/.."
DIR="${1:-data/output}"
PORT="${2:-8000}"
IP=$(hostname -I | awk '{print $1}')
echo "Serving $DIR at http://${IP}:${PORT}   (Ctrl-C to stop)"
cd "$DIR"
exec python3 -m http.server "$PORT" --bind 0.0.0.0
