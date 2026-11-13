#!/usr/bin/env bash
# One-shot recovery after a power cut / reboot. Checks the NVMe, mounts it if present,
# and resumes the LTX download detached. Safe to run repeatedly.
#
#   sudo ./scripts/powercut_recover.sh
#
# If the SSD is not detected it tells you to replug (no software can mount an absent
# USB device). Everything downstream is resumable, so just rerun after replugging.
set -euo pipefail
cd "$(dirname "$0")/.."

echo "== 1. NVMe =="
if ! mountpoint -q /mnt/nvme; then
  sudo ./scripts/nvme_mount.sh || {
    echo
    echo ">> SSD not mounted. Replug the USB-C SSD (unplug, wait 5s, replug), then rerun:"
    echo "   sudo ./scripts/powercut_recover.sh"
    exit 2; }
else
  echo "already mounted"; df -h /mnt/nvme | tail -1
fi

echo "== 2. Resume LTX download (detached) =="
./scripts/fetch_ltx.sh start

echo "== 3. Status =="
./scripts/fetch_ltx.sh status

echo
echo "Download runs in the background and survives this session closing."
echo "Re-check later with:  ./scripts/fetch_ltx.sh status"
echo "When it finishes:     ./scripts/comfy.sh start   then run a clip test via visuals/clip.py"
