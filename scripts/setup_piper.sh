#!/usr/bin/env bash
# Set up Piper TTS (standalone aarch64 binary + a voice) under models/piper/.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DEST="$ROOT/models/piper"
mkdir -p "$DEST"

PIPER_VER="2023.11.14-2"
# pick the Piper binary for this machine's architecture (aarch64 Jetson / x86_64 cloud)
case "$(uname -m)" in
  aarch64|arm64) PIPER_ARCH="aarch64" ;;
  x86_64|amd64)  PIPER_ARCH="x86_64" ;;
  *) echo "unsupported arch $(uname -m)"; exit 1 ;;
esac
PIPER_URL="https://github.com/rhasspy/piper/releases/download/${PIPER_VER}/piper_linux_${PIPER_ARCH}.tar.gz"
VOICE="en_US-lessac-medium"
VOICE_BASE="https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium"

cd "$ROOT/models"
if [ ! -x "$DEST/piper" ]; then
  echo "Downloading Piper binary ($PIPER_VER, $PIPER_ARCH)..."
  curl -fsSL -o piper_${PIPER_ARCH}.tar.gz "$PIPER_URL"
  tar -xzf piper_${PIPER_ARCH}.tar.gz          # extracts ./piper/...
  rm -f piper_${PIPER_ARCH}.tar.gz
fi

if [ ! -f "$DEST/${VOICE}.onnx" ]; then
  echo "Downloading voice ${VOICE}..."
  curl -fsSL -o "$DEST/${VOICE}.onnx"      "${VOICE_BASE}/${VOICE}.onnx"
  curl -fsSL -o "$DEST/${VOICE}.onnx.json" "${VOICE_BASE}/${VOICE}.onnx.json"
fi

echo "Piper ready: $DEST/piper + ${VOICE}"
"$DEST/piper" --help >/dev/null 2>&1 && echo "binary runs OK" || echo "WARN: binary did not run"
