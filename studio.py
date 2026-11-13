#!/usr/bin/env python3
"""yt-agent Studio — a local web UI (Gradio) for interactive content creation.

Flow:  pick channel + source -> Draft (concept + script) -> refine the script by
prompting Qwen (or hand-edit) -> Generate -> preview WITH SOUND inline -> approve.
Long durations (>2min) automatically use a per-beat visual timeline (a fresh
visual every ~15-20s) and 16:9. Everything local; nothing is published.
LAN-accessible at http://<orin-ip>:7860.

Batch (N videos from one book) is a CLI feature: use ./run.sh --count N.
"""
from __future__ import annotations
import json
import re
import time
from pathlib import Path

import gradio as gr

from common import load_config
from ingest.extract import extract_concept
from script.write import write_script, parse_duration, _split_into_beats
from script.refine import refine_script
from voice.synthesize import synthesize, synthesize_beats
from captions.transcribe import transcribe
from assemble.build import build_short
from metadata.generate import generate as gen_metadata
from orchestrator import _apply_aspect, _make_visual, _clip_indices

CHANNELS = ["finance", "education", "spirituality"]
DEF_OUT = "/mnt/nvme/yt-agent/output"
DEF_WORK = "/mnt/nvme/yt-agent/work"


def _safe_stem(name: str, fallback: str) -> str:
    """Turn a user-typed output name into a safe filename stem (no dir, no .mp4,
    only [A-Za-z0-9._-]). Empty -> fallback (short-<timestamp>)."""
    name = (name or "").strip()
    if not name:
        return fallback
    name = Path(name).name                       # drop any directory part
    name = re.sub(r"\.mp4$", "", name, flags=re.I)
    name = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-._")
    return name[:80] or fallback


def _source(upload, path):
    p = (path or "").strip()
    if p:
        return p
    if upload:
        return upload if isinstance(upload, str) else upload.name
    return ""


def do_draft(upload, path, duration, channel):
    src = _source(upload, path)
    if not src or not Path(src).exists():
        return "", "", "", gr.update(value="⚠️ Provide a valid source file or path."), None
    cfg = load_config(channel=channel)
    concept = extract_concept(cfg, src)
    scr = write_script(cfg, concept, duration=duration)
    cdisp = f"**{concept['title']}**\n\n{concept['explanation']}"
    status = f"✅ Draft ready [{channel}] — {scr['word_count']} words (~{scr['est_seconds']}s). Refine or generate."
    return cdisp, scr["title"], scr["narration"], status, concept


def do_refine(narration, instruction, channel):
    if not narration.strip():
        return narration, "⚠️ Draft a script first."
    cfg = load_config(channel=channel)
    out = refine_script(cfg, narration, instruction)
    return out, "✅ Refined. Review, refine again, or generate."


def do_generate(title, narration, duration, visual_mode, clip_beats, output_name, output_dir, work_dir, concept, channel):
    if not narration.strip():
        yield None, "⚠️ Nothing to generate — draft a script first."
        return
    cfg = load_config(channel=channel)
    lo_s, hi_s = parse_duration(duration, cfg)
    longform = hi_s > 120
    gw, gh = _apply_aspect(cfg, longform=longform)

    out_dir = Path(output_dir or DEF_OUT); out_dir.mkdir(parents=True, exist_ok=True)
    wroot = Path(work_dir or DEF_WORK); wroot.mkdir(parents=True, exist_ok=True)
    job = time.strftime("%Y%m%d-%H%M%S")
    jdir = wroot / job; jdir.mkdir(parents=True, exist_ok=True)
    stem = _safe_stem(output_name, f"short-{job}")
    concept = concept or {"title": title, "explanation": narration}

    if longform:
        beats = _split_into_beats(narration, max(3, round(hi_s / 18)))
        yield None, f"🎙️ Synthesizing {len(beats)} beats (Piper)…"
        wav, bounds = synthesize_beats(cfg, beats, jdir)
        yield None, "💬 Transcribing word-timed captions (Whisper)…"
        srt_path = transcribe(cfg, wav, jdir / "captions.srt")
        clip_idxs = _clip_indices(len(beats), int(clip_beats)) if visual_mode == "mixed" else set()
        segments = []
        for bi, b in enumerate(beats):
            yield None, f"🎨 Visual {bi + 1}/{len(beats)}…"
            mini = {"title": title, "explanation": b["visual_cue"]}
            vmode = ("clip" if bi in clip_idxs else "image") if visual_mode == "mixed" else visual_mode
            kind, path = _make_visual(cfg, mini, jdir, f"_{bi:02d}", vmode, gw, gh)
            segments.append({"start": bounds[bi][0], "end": bounds[bi][1],
                             "kind": kind, "path": str(path) if path else None})
        yield None, "🎬 Assembling 16:9 video (per-beat timeline)…"
        mp4 = build_short(cfg, wav, srt_path, out_dir / f"{stem}.mp4",
                          title=title, segments=segments)
        vis = f"per-beat ({len(segments)} segs)"
    else:
        yield None, "🎙️ Synthesizing voice (Piper)…"
        wav = synthesize(cfg, narration, jdir / "voice.wav")
        yield None, "💬 Transcribing word-timed captions (Whisper)…"
        srt_path = transcribe(cfg, wav, jdir / "captions.srt")
        yield None, "🎨 Generating visual…"
        vmode = "clip" if visual_mode == "mixed" else visual_mode
        kind, path = _make_visual(cfg, concept, jdir, "", vmode, gw, gh)
        seg = [{"start": 0.0, "end": 0.0, "kind": kind, "path": str(path) if path else None}]
        yield None, "🎬 Assembling video (ffmpeg)…"
        mp4 = build_short(cfg, wav, srt_path, out_dir / f"{stem}.mp4",
                          title=title, segments=seg)
        vis = kind

    meta = gen_metadata(cfg, title, narration, concept.get("title", title))
    meta.update({"job": job, "channel": channel, "video_file": mp4.name})
    (out_dir / f"{stem}.metadata.json").write_text(json.dumps(meta, indent=2))
    yield str(mp4), f"✅ Done — saved to {mp4} ({vis}). Review below. Nothing published."


with gr.Blocks(title="yt-agent Studio") as demo:
    gr.Markdown("# 🎬 yt-agent Studio\nLocal, private. Pick a channel → draft → refine → generate → preview. Nothing is uploaded.")
    concept_state = gr.State(None)

    with gr.Row():
        with gr.Column(scale=1):
            gr.Markdown("### 1. Source")
            channel = gr.Dropdown(CHANNELS, value="finance", label="Channel (persona / voice / style)")
            path = gr.Textbox(label="File path (PDF / txt / audio / video) — best for big files",
                              placeholder="/mnt/nvme/… or data/pdfs/book.pdf")
            upload = gr.File(label="…or upload a file", type="filepath")
            duration = gr.Dropdown(["short", "90s", "1min", "3min", "5min"], value="short",
                                   label="Length (>2min = 16:9 + per-beat visuals)")
            draft_btn = gr.Button("① Draft", variant="primary")
            concept_md = gr.Markdown(label="Concept")
        with gr.Column(scale=2):
            gr.Markdown("### 2. Script (edit freely, or refine with AI)")
            title_box = gr.Textbox(label="Title")
            script_box = gr.Textbox(label="Narration", lines=10)
            with gr.Row():
                instruction = gr.Textbox(label="Refine instruction (prompt Qwen)",
                                         placeholder="e.g. make the hook punchier; use a real-estate example; shorten", scale=3)
                refine_btn = gr.Button("② Refine with AI", scale=1)

    gr.Markdown("### 3. Generate")
    with gr.Row():
        visual_mode = gr.Dropdown(["auto", "image", "chart", "clip", "mixed", "none"], value="auto",
                                  label="Visual (auto=SDXL stills; clip=LTX every beat SLOW; mixed=stills + LTX on key beats)")
        clip_beats = gr.Slider(1, 6, value=3, step=1, label="Mixed: # of LTX clip beats (~2min each @30W)")
    with gr.Row():
        output_name = gr.Textbox(label="Output filename (optional)",
                                 placeholder="e.g. simple-interest  → saves simple-interest.mp4 (blank = short-<timestamp>)")
        output_dir = gr.Textbox(label="Output dir", value=DEF_OUT)
        work_dir = gr.Textbox(label="Work dir (intermediates)", value=DEF_WORK)
    gen_btn = gr.Button("③ Generate video", variant="primary")
    status = gr.Markdown("Ready.")
    video = gr.Video(label="Preview (plays with sound)")

    draft_btn.click(do_draft, [upload, path, duration, channel],
                    [concept_md, title_box, script_box, status, concept_state])
    refine_btn.click(do_refine, [script_box, instruction, channel], [script_box, status])
    gen_btn.click(do_generate,
                  [title_box, script_box, duration, visual_mode, clip_beats, output_name, output_dir, work_dir, concept_state, channel],
                  [video, status])

if __name__ == "__main__":
    demo.queue().launch(server_name="0.0.0.0", server_port=7860, show_error=True,
                        allowed_paths=["/mnt/nvme/yt-agent", DEF_OUT, DEF_WORK, "/tmp"])
