# yt-agent — Standalone install (no Docker)

Bare-metal setup on a single machine. For the containerized setup instead, see
[`docker/README.md`](docker/README.md). For day-to-day operation after install, see
[`README.md`](README.md).

## Tested environment
- **NVIDIA Jetson AGX Orin 64GB**, JetPack 7 / L4T r39.2, **Ubuntu 24.04**, **Python 3.12**.
- Works on other CUDA machines too; adjust the PyTorch wheel index to your CUDA version.

## What needs to be installed (overview)
| Component | Purpose | Required? |
|---|---|---|
| Python 3.12 + venv | the pipeline app | yes |
| Ollama + `qwen2.5:14b` | LLM (concepts, scripts, metadata) | yes |
| App deps (`requirements.txt`) | Whisper, Piper client, matplotlib, Pillow, ffmpeg, gradio | yes |
| Piper TTS (binary + voice) | narration | yes |
| ComfyUI + PyTorch + models | SDXL images / LTX video visuals | optional (falls back to charts) |
| Google API libs + OAuth creds | YouTube upload (Phase 3) | optional |

> ffmpeg: the app does **not** use the system ffmpeg (on Jetson it's a stripped build).
> A full static ffmpeg ships via the `imageio-ffmpeg` pip package — nothing to install.
> Fonts: title/captions use DejaVu Sans Bold (`fonts-dejavu-core`, usually preinstalled).

---

## 1. System packages
```bash
sudo apt update && sudo apt install -y python3-venv python3-pip git curl fonts-dejavu-core
```

## 2. Ollama + the LLM
```bash
curl -fsSL https://ollama.com/install.sh | sh
ollama pull qwen2.5:14b          # ~9GB (4-bit); the pipeline's default model
# optional faster fallback: ollama pull llama3.1:8b
```

## 3. The app (venv + Python deps)
```bash
cd ~/yt-agent
python3 -m venv .venv
.venv/bin/pip install -U pip
.venv/bin/pip install -r requirements.txt
```

## 4. Piper TTS (narration voice)
```bash
./scripts/setup_piper.sh         # fetches the Piper binary for your arch + en_US-lessac-medium
```

## 5. (Optional) GPU visuals — ComfyUI for SDXL images + LTX video
Skip this and the pipeline still works: it falls back to illustrative charts / gradients.
This is a **separate** venv so PyTorch never mixes with the app venv.
```bash
# PyTorch (CUDA 13 wheel; change cu130 to match your CUDA):
python3 -m venv ~/comfyui-venv
~/comfyui-venv/bin/pip install -U pip
~/comfyui-venv/bin/pip install --pre torch torchvision --index-url https://download.pytorch.org/whl/cu130

# ComfyUI:
git clone https://github.com/comfyanonymous/ComfyUI.git ~/comfyui-app
~/comfyui-venv/bin/pip install -r ~/comfyui-app/requirements.txt
```
Point ComfyUI at a models dir (edit `~/comfyui-app/extra_model_paths.yaml`; a template is
in [`docker/extra_model_paths.yaml`](docker/extra_model_paths.yaml)), then download models
into it:
- **SDXL base** `sd_xl_base_1.0.safetensors` → `checkpoints/`
- **LTX video** `ltx-video-2b-v0.9.5.safetensors` → `checkpoints/`  (`./scripts/fetch_ltx.sh start`)
- **T5 encoder** `t5xxl_fp16.safetensors` → `text_encoders/`  (from `comfyanonymous/flux_text_encoders`)

Start/stop it with `./scripts/comfy.sh start|status|stop`.

## 6. (Optional, Jetson) storage + performance
- Large models belong on fast storage (an NVMe), not the small eMMC. Mount it and put
  `comfyui-models/` + `output/` there; `./scripts/nvme_mount.sh` helps on this board.
- Full performance: `sudo nvpmodel -m 0 && sudo jetson_clocks` (MAXN; ~2x faster gen).

## 7. (Optional) YouTube upload — Phase 3
```bash
.venv/bin/pip install -r publish/requirements.txt
# put your OAuth Desktop client at data/secrets/client_secret.json (never commit it)
```

---

## Verify it works
```bash
# quick finance Short from the sample (charts if ComfyUI isn't running):
./run.sh data/pdfs/wealth_of_nations.txt short --channel finance
# or the interactive UI (also starts ollama + comfyui if present):
./scripts/studio.sh          # -> http://<host>:7860
```
A finished `.mp4` + `.metadata.json` appears in the output dir, behind the approval gate.
Preview with sound: `./scripts/preview.sh <output-dir>` → `http://<host>:8000`.
