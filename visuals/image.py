"""visuals: concept -> one SDXL background/B-roll image via ComfyUI (local GPU).

The LLM turns the concept into a visual SDXL prompt (NO text in image — SDXL
can't render words). Requires a ComfyUI server (see scripts/comfy.sh). Returns
the saved PNG path, or None on any failure so the pipeline falls back to
chart/gradient visuals.
"""
from __future__ import annotations
import json
import os
import time
import urllib.request
from pathlib import Path

from common import llm, get_logger, chan, english_only

log = get_logger("image")

# Overridable for Docker/remote (defaults preserve local single-host behavior).
SERVER = os.environ.get("COMFYUI_URL", "http://127.0.0.1:8188")
COMFY_OUT = Path(os.environ.get("COMFY_OUTPUT_DIR", "/mnt/nvme/yt-agent/output"))  # ComfyUI --output-directory

_STYLE = ("clean modern vector-style illustration, finance/economics theme, deep "
          "navy background, soft glowing blue and gold accents, minimal, no text, "
          "no words, no letters, high quality, vertical composition")
_NEG = "text, words, letters, numbers, watermark, logo, blurry, low quality, deformed, ugly"


def _prompt(cfg: dict, concept: dict) -> str:
    p = llm(
        cfg,
        "Describe a single symbolic IMAGE (no text/words in it) that represents this "
        f"concept, in 12-20 words, comma-separated visual phrases only. Write in ENGLISH ONLY:\n"
        f"TITLE: {concept['title']}\nNOTES: {concept['explanation']}",
        temperature=0.6, num_predict=80,
    ).replace("\n", " ").strip()
    p = english_only(p)
    style = chan(cfg, "image_style", _STYLE)
    return f"{p}, {style}"


def _workflow(pos: str, neg: str, prefix: str, w=832, h=1216, steps=22, seed=7) -> dict:
    return {
        "4": {"class_type": "CheckpointLoaderSimple",
              "inputs": {"ckpt_name": "sd_xl_base_1.0.safetensors"}},
        "5": {"class_type": "EmptyLatentImage", "inputs": {"width": w, "height": h, "batch_size": 1}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"text": pos, "clip": ["4", 1]}},
        "7": {"class_type": "CLIPTextEncode", "inputs": {"text": neg, "clip": ["4", 1]}},
        "3": {"class_type": "KSampler",
              "inputs": {"seed": seed, "steps": steps, "cfg": 7.0, "sampler_name": "dpmpp_2m",
                         "scheduler": "karras", "denoise": 1.0, "model": ["4", 0],
                         "positive": ["6", 0], "negative": ["7", 0], "latent_image": ["5", 0]}},
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["4", 2]}},
        "9": {"class_type": "SaveImage", "inputs": {"filename_prefix": prefix, "images": ["8", 0]}},
    }


def _api(path, data=None):
    if data is not None:
        req = urllib.request.Request(SERVER + path, data=json.dumps(data).encode(),
                                     headers={"Content-Type": "application/json"})
    else:
        req = urllib.request.Request(SERVER + path)
    return json.loads(urllib.request.urlopen(req, timeout=30).read())


def server_up() -> bool:
    try:
        urllib.request.urlopen(SERVER + "/system_stats", timeout=5)
        return True
    except Exception:
        return False


def generate_image(cfg: dict, concept: dict, out_png: Path, seed: int = 7,
                   w: int = 832, h: int = 1216) -> Path | None:
    if not server_up():
        log.info("ComfyUI not running; skipping image (fallback to chart/gradient)")
        return None
    try:
        prefix = f"job_{int(time.time())}"
        prompt = _prompt(cfg, concept)
        neg = chan(cfg, "image_negative", _NEG)
        log.info("SDXL prompt: %s (%dx%d)", prompt[:80], w, h)
        pid = _api("/prompt", {"prompt": _workflow(prompt, neg, prefix, w=w, h=h, seed=seed)})["prompt_id"]
        t0 = time.time()
        while True:
            hist = _api(f"/history/{pid}")
            if pid in hist:
                st = hist[pid].get("status", {})
                if st.get("completed") or st.get("status_str") == "success":
                    break
                if st.get("status_str") == "error":
                    log.warning("image gen error; falling back")
                    return None
            if time.time() - t0 > 300:
                log.warning("image gen timeout; falling back")
                return None
            time.sleep(2)
        fn = hist[pid]["outputs"]["9"]["images"][0]["filename"]
        src = COMFY_OUT / fn
        out_png = Path(out_png)
        out_png.write_bytes(src.read_bytes())
        log.info("image ready in %.1fs -> %s", time.time() - t0, out_png.name)
        return out_png
    except Exception as e:
        log.warning("image gen failed (%s); fallback", e)
        return None
