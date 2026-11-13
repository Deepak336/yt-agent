#!/usr/bin/env bash
# Mount the external USB-C NVMe SSD (SanDisk "Deepak_SSD") at /mnt/nvme by UUID.
#
#   sudo ./scripts/nvme_mount.sh
#
# Notes for future sessions / owner:
#  - This SSD is a USB-C enclosure; it enumerates as /dev/sdX1 (USB mass storage),
#    NOT as /dev/nvmeXn1. "lsblk shows no nvme" is normal and not the problem.
#  - exfat ownership is a MOUNT option (uid/gid/umask), not chown.
#  - exfat shared-superblock gotcha: a stale/second mount of the same device reuses
#    the first mount's options. This script clears any stale mount first.
#  - fstab already has a correct line (nofail), so `sudo mount -a` also works when the
#    device is present. This script just gives clearer errors when it is NOT present.
set -euo pipefail
UUID=65F6-8720
MP=/mnt/nvme

if [ "$(id -u)" -ne 0 ]; then
  echo "Run with sudo:  sudo $0"; exit 1
fi

mkdir -p "$MP"

if mountpoint -q "$MP"; then
  echo "Already mounted:"; findmnt "$MP"; df -h "$MP"; exit 0
fi

DEV="$(blkid -U "$UUID" 2>/dev/null || true)"
if [ -z "$DEV" ]; then
  echo "!! SSD with UUID $UUID is NOT present on the system."
  echo "   The USB-C enclosure is not enumerated by the kernel."
  echo "   -> Physically unplug and replug the USB-C SSD, then rerun this."
  echo
  echo "Current block devices:"; lsblk -o NAME,SIZE,TYPE,FSTYPE,LABEL,MOUNTPOINT
  echo "USB bus:"; lsusb
  exit 2
fi
echo "Found SSD at $DEV"

# Clear any stale mount of the same device (exfat shared-superblock gotcha).
while :; do
  m="$(findmnt -nro TARGET -S "$DEV" 2>/dev/null | head -1)"
  [ -z "$m" ] && break
  echo "Unmounting stale mount at $m"; umount "$m" 2>/dev/null || umount -l "$m"
done

mount -t exfat -o rw,uid=1000,gid=1000,umask=0022,nofail "$DEV" "$MP"
echo "Mounted:"; findmnt "$MP"; df -h "$MP"
