# yt-agent — Docker stack

Containerizes the whole pipeline so you can `docker compose up` here on the Jetson
Orin and later rebuild the same thing on another NVIDIA box or a GPU cloud VM.

Three services (see `docker-compose.yml`):

| Service   | Image                          | GPU | Role |
|-----------|--------------------------------|-----|------|
| `ollama`  | `ollama/ollama`                | yes | LLM (qwen2.5:14b) |
| `comfyui` | built from `Dockerfile.comfyui`| yes | SDXL images + LTX video |
| `app`     | built from `Dockerfile.app`    | no  | pipeline + Studio UI (Piper/Whisper/ffmpeg) |

Design choices that make it portable:
- **Models are NOT baked into images.** They live on the host NVMe and are mounted
  (`NVME_ROOT`). Images stay small; you move the big files once.
- The **app is CPU-only** and reaches the GPU services by name
  (`ollama:11434`, `comfyui:8188`) via env vars — no CUDA in the app image.
- CUDA/cuDNN ship inside the **torch wheels**; only the GPU **driver** is injected by
  the NVIDIA Container Toolkit. So the GPU images build on a plain `python:3.12-slim`
  base and work on any arch you build them on (aarch64 Jetson / x86_64 cloud).

---

## 1. Host prerequisites (one-time, need sudo — not done automatically)

**a) NVIDIA Container Toolkit** (so containers can use the GPU). On JetPack 7:
```bash
sudo apt-get install -y nvidia-container-toolkit
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker
# verify:
docker info | grep -i runtimes      # should now list 'nvidia'
```
(On a cloud VM, install the toolkit per NVIDIA's distro instructions instead.)

**b) Move Docker's data-root to the NVMe.** The eMMC root has only ~11 GB free and
the torch/ComfyUI image is several GB. Point Docker at the NVMe:
```bash
sudo mkdir -p /mnt/nvme/docker
echo '{ "data-root": "/mnt/nvme/docker" }' | sudo tee /etc/docker/daemon.json
sudo systemctl restart docker
docker info | grep "Docker Root Dir"   # -> /mnt/nvme/docker
```
> The NVMe is exfat, which can't hold Docker's overlay2 layers (needs POSIX perms).
> If `data-root` on exfat errors, create a small **ext4** partition/image on the NVMe
> for `/mnt/nvme/docker`, or keep data-root on eMMC and prune aggressively.

---

## 2. Configure + build
```bash
cd ~/yt-agent/docker          # this folder lives inside the repo
cp env.example .env           # then edit NVME_ROOT / OLLAMA_MODELS if needed
docker compose build          # builds app + comfyui (torch download is large/slow)
```

## 3. First-run model setup
```bash
docker compose up -d ollama
docker compose exec ollama ollama pull qwen2.5:14b
# SDXL / LTX / T5 checkpoints already live under $NVME_ROOT/comfyui-models/ and are
# mounted in — nothing to copy. (To avoid re-pulling the 9GB LLM, set OLLAMA_MODELS
# in .env to the host's existing ollama dir instead.)
```

## 4. Run
```bash
docker compose up -d
# Studio UI:   http://<host>:7860   (or http://orinx.local:7860)
# ComfyUI GUI: http://<host>:8188   (optional)
docker compose logs -f app
```

Finished videos land in `$NVME_ROOT/output/` on the host (the app writes there and
ComfyUI writes its gens there too — same mounted dir, so the app reads them back).

> **Do NOT run `scripts/studio.sh` here.** That's the bare-metal launcher (it starts
> ollama + comfyui + studio.py on one host). In Docker those are separate services:
> `docker compose up -d` is the equivalent — it starts ollama + comfyui, and the `app`
> container runs `python studio.py` itself. `docker compose build` only builds images;
> it starts nothing. `depends_on` sets start order, not readiness — ComfyUI needs ~a
> minute to load, so an immediate Generate falls back to a chart until it's up (watch
> `docker compose logs -f comfyui`).

---

## Portability to another NVIDIA box / cloud
1. Clone/copy the `yt-agent/` repo to the target (this `docker/` folder is inside it).
2. Do the two host prerequisites above on the target.
3. Put the model files under the target's `NVME_ROOT/comfyui-models/` (or re-download).
4. If the target isn't CUDA 13, set `TORCH_INDEX` in `.env` to the matching wheel
   index (e.g. `cu124`).
5. `docker compose build && docker compose up -d`. Build on the target so pip selects
   the correct-arch torch and Piper binary.

## Notes / limits
- Still **30W** on this Orin until MAXN; gen times match the non-Docker runs.
- faster-whisper downloads its model on first use (needs network); mount a cache volume
  at `/root/.cache` in the `app` service if you want to persist it across rebuilds.
- GPU-in-Docker on brand-new JetPack 7 may need iteration (toolkit/driver versions).
  If a GPU service fails to see the device, re-check step 1a and `docker info`.
- The app also runs one-offs without the UI, e.g.:
  `docker compose exec app python orchestrator.py --source data/pdfs/book.pdf --channel finance --duration 3min --visual mixed`
