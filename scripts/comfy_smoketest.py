#!/usr/bin/env python3
"""Smoke-test SDXL on ComfyUI via its HTTP API — confirms the Orin GPU (sm_87)
handles real diffusion. Assumes a ComfyUI server is running on 127.0.0.1:8188
with output dir = /mnt/nvme/yt-agent/output.

Usage: python comfy_smoketest.py "a prompt"
"""
import json
import sys
import time
import urllib.request

SERVER = "http://127.0.0.1:8188"
OUT_DIR = "/mnt/nvme/yt-agent/output"


def workflow(pos: str, neg: str, w=832, h=1216, steps=20, seed=42) -> dict:
    return {
        "4": {"class_type": "CheckpointLoaderSimple",
              "inputs": {"ckpt_name": "sd_xl_base_1.0.safetensors"}},
        "5": {"class_type": "EmptyLatentImage",
              "inputs": {"width": w, "height": h, "batch_size": 1}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"text": pos, "clip": ["4", 1]}},
        "7": {"class_type": "CLIPTextEncode", "inputs": {"text": neg, "clip": ["4", 1]}},
        "3": {"class_type": "KSampler",
              "inputs": {"seed": seed, "steps": steps, "cfg": 7.0,
                         "sampler_name": "euler", "scheduler": "normal", "denoise": 1.0,
                         "model": ["4", 0], "positive": ["6", 0],
                         "negative": ["7", 0], "latent_image": ["5", 0]}},
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["4", 2]}},
        "9": {"class_type": "SaveImage",
              "inputs": {"filename_prefix": "smoketest", "images": ["8", 0]}},
    }


def _post(path, data):
    req = urllib.request.Request(SERVER + path, data=json.dumps(data).encode(),
                                 headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=30).read())


def _get(path):
    return json.loads(urllib.request.urlopen(SERVER + path, timeout=30).read())


def main():
    pos = sys.argv[1] if len(sys.argv) > 1 else (
        "a clean minimalist illustration of a rising stock market chart, "
        "financial theme, blue tones, high quality, vertical")
    neg = "blurry, watermark, text, low quality, deformed"
    t0 = time.time()
    pid = _post("/prompt", {"prompt": workflow(pos, neg)})["prompt_id"]
    print(f"queued prompt {pid}; generating (first run includes sm_87 JIT compile)...")
    while True:
        hist = _get(f"/history/{pid}")
        if pid in hist:
            status = hist[pid].get("status", {})
            if status.get("completed") or status.get("status_str") == "success":
                break
            if status.get("status_str") == "error":
                print("GENERATION ERROR:", json.dumps(hist[pid], indent=2)[:1500])
                sys.exit(1)
        time.sleep(2)
    outs = hist[pid]["outputs"]["9"]["images"][0]
    print(f"DONE in {time.time()-t0:.1f}s -> {OUT_DIR}/{outs['filename']}")


if __name__ == "__main__":
    main()
