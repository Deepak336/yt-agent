# yt-agent pipeline + Studio UI. CPU-only: Piper (TTS), faster-whisper (STT, CPU
# int8), matplotlib, Pillow, and a PyPI-bundled ffmpeg (libx264+aac). It reaches
# the GPU services (ollama, comfyui) over the network, so this image needs no CUDA.
# Build context = ../yt-agent (the repo). Portable: Piper binary is fetched for the
# build machine's architecture (aarch64 Jetson / x86_64 cloud) by setup_piper.sh.
FROM python:3.12-slim-bookworm

# fonts-dejavu-core: the bold font the assembler draws titles/captions with
# (assemble/build.py expects /usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf)
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl ca-certificates tar bash fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# deps first for layer caching
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# app code (.dockerignore excludes .venv/models/data/.git)
COPY . /app/

# fetch the Piper binary + default voice for THIS build arch into models/piper/
RUN bash scripts/setup_piper.sh

EXPOSE 7860
# studio.py binds 0.0.0.0:7860; it only CONNECTS to ollama/comfyui (never starts them)
CMD ["python", "studio.py"]
