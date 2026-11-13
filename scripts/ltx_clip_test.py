#!/usr/bin/env python3
"""First LTX-Video clip test — fixed prompt to isolate pure gen time (no LLM).

Reuses visuals/clip.py's workflow + API. Submits one clip, polls, assembles the
frame batch to mp4 with the bundled ffmpeg, and prints per-clip timing.

    cd ~/yt-agent && python3 scripts/ltx_clip_test.py
"""
from __future__ import annotations
import json, time, subprocess, urllib.request
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common import ffmpeg_bin  # noqa: E402
from visuals.clip import _workflow, _api, SERVER, COMFY_OUT, _NEG  # noqa: E402

FPS = 24
LENGTH = 49          # ~2.0s at 24fps
W, H, STEPS, SEED = 768, 512, 25, 7
PROMPT = ("a slow cinematic dolly over a modern city financial district at golden "
          "hour, glass towers, smooth camera motion, high detail, finance theme")
OUT = Path("/mnt/nvme/yt-agent/output/ltx_test.mp4")


def main():
    prefix = f"clip_test_{int(time.time())}"
    print(f"[ltx-test] prompt: {PROMPT}")
    print(f"[ltx-test] {W}x{H}, {LENGTH} frames @ {FPS}fps, {STEPS} steps")
    wf = _workflow(PROMPT, _NEG, prefix, W, H, LENGTH, STEPS, FPS, SEED)
    t0 = time.time()
    pid = _api("/prompt", {"prompt": wf})["prompt_id"]
    print(f"[ltx-test] submitted prompt_id={pid}; polling...")
    while True:
        hist = _api(f"/history/{pid}")
        if pid in hist:
            st = hist[pid].get("status", {})
            if st.get("completed") or st.get("status_str") == "success":
                break
            if st.get("status_str") == "error":
                print("[ltx-test] ERROR:\n" + json.dumps(hist[pid].get("status", {}), indent=2)[:2000])
                return 1
        if time.time() - t0 > 1800:
            print("[ltx-test] TIMEOUT after 1800s"); return 1
        time.sleep(3)
    gen_s = time.time() - t0
    imgs = hist[pid]["outputs"]["save"]["images"]
    print(f"[ltx-test] GEN DONE: {len(imgs)} frames in {gen_s:.1f}s "
          f"({gen_s / max(len(imgs),1):.2f}s/frame, clip ~{LENGTH/FPS:.1f}s)")

    seqdir = OUT.parent / (prefix + "_frames"); seqdir.mkdir(parents=True, exist_ok=True)
    for i, im in enumerate(imgs):
        (seqdir / f"f_{i:04d}.png").write_bytes((COMFY_OUT / im["filename"]).read_bytes())
    subprocess.run([ffmpeg_bin(), "-y", "-framerate", str(FPS), "-i", str(seqdir / "f_%04d.png"),
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "20", str(OUT)],
                   check=True, capture_output=True)
    print(f"[ltx-test] mp4 -> {OUT}  ({OUT.stat().st_size/1e6:.1f} MB)")
    print(f"[ltx-test] TOTAL {time.time()-t0:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
