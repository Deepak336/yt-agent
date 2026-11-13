"""visuals: text prompt -> a short AI video clip via LTX-Video 2B on ComfyUI.

Uses ComfyUI's native LTXV nodes (verified schemas). Decodes to a frame batch
(SaveImage) and combines to mp4 with our bundled ffmpeg. Returns the mp4 path or
None on failure (pipeline falls back to image/chart). SLOW on Orin — minutes/clip.
"""
from __future__ import annotations
import json
import os
import time
import urllib.request
from pathlib import Path

from common import get_logger, ffmpeg_bin, llm, chan, english_only
import subprocess

log = get_logger("clip")

SERVER = os.environ.get("COMFYUI_URL", "http://127.0.0.1:8188")
COMFY_OUT = Path(os.environ.get("COMFY_OUTPUT_DIR", "/mnt/nvme/yt-agent/output"))
CKPT = "ltx-video-2b-v0.9.5.safetensors"
# The ltx-video-2b checkpoint ships the diffusion model + VAE but NOT a text
# encoder, so CheckpointLoaderSimple's CLIP output is None. LTX uses T5 (t5xxl),
# loaded separately via CLIPLoader(type="ltxv"). File lives in the text_encoders
# model dir (see extra_model_paths.yaml).
T5 = "t5xxl_fp16.safetensors"
_NEG = "worst quality, blurry, jittery, distorted, watermark, text"


def _prompt(cfg: dict, concept: dict) -> str:
    p = llm(cfg,
            "Describe ONE short cinematic video shot (no text/words on screen) that "
            f"illustrates this concept, 15-25 words, motion included. Write in ENGLISH ONLY:\n"
            f"TITLE: {concept['title']}\n"
            f"NOTES: {concept['explanation']}",
            temperature=0.6, num_predict=90).replace("\n", " ").strip()
    p = english_only(p)
    style = chan(cfg, "clip_style", "cinematic, smooth camera motion, high detail, finance/economics theme")
    return p + ", " + style


def _api(path, data=None):
    req = urllib.request.Request(SERVER + path,
                                 data=json.dumps(data).encode() if data else None,
                                 headers={"Content-Type": "application/json"} if data else {})
    return json.loads(urllib.request.urlopen(req, timeout=30).read())


def server_up() -> bool:
    try:
        urllib.request.urlopen(SERVER + "/system_stats", timeout=5); return True
    except Exception:
        return False


def _workflow(pos, neg, prefix, w, h, length, steps, fps, seed):
    return {
        "ckpt": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": CKPT}},
        "t5": {"class_type": "CLIPLoader", "inputs": {"clip_name": T5, "type": "ltxv"}},
        "pos": {"class_type": "CLIPTextEncode", "inputs": {"text": pos, "clip": ["t5", 0]}},
        "neg": {"class_type": "CLIPTextEncode", "inputs": {"text": neg, "clip": ["t5", 0]}},
        "latent": {"class_type": "EmptyLTXVLatentVideo",
                   "inputs": {"width": w, "height": h, "length": length, "batch_size": 1}},
        "cond": {"class_type": "LTXVConditioning",
                 "inputs": {"positive": ["pos", 0], "negative": ["neg", 0], "frame_rate": float(fps)}},
        "msamp": {"class_type": "ModelSamplingLTXV",
                  "inputs": {"model": ["ckpt", 0], "max_shift": 2.05, "base_shift": 0.95}},
        "sched": {"class_type": "LTXVScheduler",
                  "inputs": {"steps": steps, "max_shift": 2.05, "base_shift": 0.95,
                             "stretch": True, "terminal": 0.1}},
        "samp_sel": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "euler"}},
        "sampler": {"class_type": "SamplerCustom",
                    "inputs": {"model": ["msamp", 0], "add_noise": True, "noise_seed": seed,
                               "cfg": 3.0, "positive": ["cond", 0], "negative": ["cond", 1],
                               "sampler": ["samp_sel", 0], "sigmas": ["sched", 0],
                               "latent_image": ["latent", 0]}},
        "decode": {"class_type": "VAEDecode", "inputs": {"samples": ["sampler", 0], "vae": ["ckpt", 2]}},
        "save": {"class_type": "SaveImage", "inputs": {"filename_prefix": prefix, "images": ["decode", 0]}},
    }


def generate_clip(cfg: dict, concept: dict, out_mp4: Path,
                  w=768, h=512, length=49, steps=25, fps=24, seed=7) -> Path | None:
    if not server_up():
        log.info("ComfyUI down; skipping clip"); return None
    try:
        prefix = f"clip_{int(time.time())}"
        prompt = _prompt(cfg, concept)
        log.info("LTX prompt: %s", prompt[:90])
        pid = _api("/prompt", {"prompt": _workflow(prompt, _NEG, prefix, w, h, length, steps, fps, seed)})["prompt_id"]
        t0 = time.time()
        while True:
            hist = _api(f"/history/{pid}")
            if pid in hist:
                st = hist[pid].get("status", {})
                if st.get("completed") or st.get("status_str") == "success":
                    break
                if st.get("status_str") == "error":
                    log.warning("LTX gen error:\n%s", json.dumps(hist[pid].get("status", {}))[:800]); return None
            if time.time() - t0 > 1800:
                log.warning("LTX timeout"); return None
            time.sleep(3)
        imgs = hist[pid]["outputs"]["save"]["images"]
        log.info("LTX produced %d frames in %.1fs", len(imgs), time.time() - t0)
        # sequence the frames, then ffmpeg -> mp4
        seqdir = Path(out_mp4).parent / (prefix + "_frames"); seqdir.mkdir(parents=True, exist_ok=True)
        for i, im in enumerate(imgs):
            (seqdir / f"f_{i:04d}.png").write_bytes((COMFY_OUT / im["filename"]).read_bytes())
        out_mp4 = Path(out_mp4)
        subprocess.run([ffmpeg_bin(), "-y", "-framerate", str(fps), "-i", str(seqdir / "f_%04d.png"),
                        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "20", str(out_mp4)],
                       check=True, capture_output=True)
        log.info("clip -> %s", out_mp4)
        return out_mp4
    except Exception as e:
        log.warning("clip gen failed (%s)", e); return None
