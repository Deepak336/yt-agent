#!/usr/bin/env bash
# Start/stop a LAN-only TigerVNC desktop on display :1 (TCP 5901).
# First time: run `vncpasswd` to set a password.
#   ./vnc.sh start | stop | status
set -euo pipefail
DISPLAY_NUM=":1"
GEOMETRY="1920x1080"

case "${1:-start}" in
  start)
    if [ ! -f "$HOME/.vnc/passwd" ]; then
      echo "No VNC password set. Run:  vncpasswd   (then re-run this)"; exit 1
    fi
    # -localhost no => reachable on the LAN. Keep this box's port off the internet.
    vncserver "$DISPLAY_NUM" -geometry "$GEOMETRY" -depth 24 -localhost no
    IP=$(hostname -I | awk '{print $1}')
    echo "VNC up. Connect your viewer to:  ${IP}:5901   (or ${IP}:1)"
    ;;
  stop)
    vncserver -kill "$DISPLAY_NUM" || true
    ;;
  status)
    vncserver -list || true
    ss -tlnp 2>/dev/null | grep 5901 || echo "(not listening)"
    ;;
  *) echo "usage: ./vnc.sh start|stop|status"; exit 1 ;;
esac
