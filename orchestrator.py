#!/usr/bin/env python3
"""yt-agent orchestrator: source file -> finished video(s) behind the APPROVAL GATE.

Fully local. Nothing is uploaded. Handles multiple channels (--channel), multiple
lesson videos from one source (--count N), short (9:16) and long-form (16:9) output,
and a per-beat visual timeline for long videos (a fresh visual every ~15-20s).

Usage:
    python orchestrator.py --source data/pdfs/book.pdf --channel education --duration 3min
    python orchestrator.py --source book.pdf --count 3 --channel finance
"""
from __future__ import annotations
import argparse
import json
import time
from pathlib import Path

from common import load_config, get_logger, path_in, chan
from ingest.extract import extract_concepts
from script.write import write_script, parse_duration
from voice.synthesize import synthesize, synthesize_beats
from captions.transcribe import transcribe
from visuals.chart import make_chart
from visuals.image import generate_image, server_up
from visuals.clip import generate_clip
from assemble.build import build_short
from metadata.generate import generate as gen_metadata

log = get_logger("orchestrator")


def _dir(cfg, key, override):
    if override:
        p = Path(override).expanduser()
        p.mkdir(parents=True, exist_ok=True)
        return p
    return path_in(cfg, key)


def _apply_aspect(cfg: dict, longform: bool) -> tuple[int, int]:
    """Set cfg video W/H from the channel's aspect for this length; return SDXL gen
    (w,h) matched to orientation."""
    aspect = chan(cfg, "long_aspect", "16:9") if longform else chan(cfg, "shorts_aspect", "9:16")
    presets = cfg["video"].get("aspects", {})
    W, H = presets.get(aspect, [cfg["video"]["width"], cfg["video"]["height"]])
    cfg["video"]["width"], cfg["video"]["height"] = W, H
    gen = (1216, 832) if W > H else (832, 1216)   # landscape vs portrait SDXL dims
    log.info("aspect=%s -> %dx%d (SDXL gen %dx%d)", aspect, W, H, *gen)
    return gen


def _clip_indices(n: int, k: int) -> set[int]:
    """Pick k beat indices spread evenly across n beats (always includes the first
    beat / hook). Used by 'mixed' mode to place LTX clips on a few key beats."""
    k = max(1, min(k, n))
    if k == 1:
        return {0}
    return {round(i * (n - 1) / (k - 1)) for i in range(k)}


def _make_visual(cfg, concept, jdir, tag, visual, gw, gh):
    """Produce one visual for a beat/short. Returns (kind, path_or_None).
    Falls back image->chart->gradient so a missing GPU never breaks the run."""
    if visual == "none":
        return "gradient", None
    if visual == "chart":
        p = make_chart(cfg, concept, jdir / f"chart{tag}.png")
        return ("chart", p) if p else ("gradient", None)
    up = server_up()
    if visual == "clip" and up:
        p = generate_clip(cfg, concept, jdir / f"clip{tag}.mp4")
        if p:
            return "clip", p
    if visual in ("auto", "image", "clip") and up:
        p = generate_image(cfg, concept, jdir / f"bg{tag}.png", w=gw, h=gh)
        if p:
            return "image", p
    p = make_chart(cfg, concept, jdir / f"chart{tag}.png")
    return ("chart", p) if p else ("gradient", None)


def _produce(cfg, concept, duration, visual, out_dir, jdir, gen_wh, idx, total, clip_beats=3) -> tuple[Path, dict]:
    gw, gh = gen_wh
    job = jdir.name
    stem = f"short-{job}" if total == 1 else f"short-{job}-{idx:02d}"

    scr = write_script(cfg, concept, duration=duration)
    (jdir / f"script{idx:02d}.txt").write_text(scr["narration"], encoding="utf-8")
    beats = scr.get("beats")

    if beats and len(beats) > 1:
        # long-form: per-beat voice + a visual timeline
        wav, bounds = synthesize_beats(cfg, beats, jdir)
        srt_path = transcribe(cfg, wav, jdir / "captions.srt")
        # mixed mode: LTX clips only on a few key beats, SDXL stills on the rest.
        clip_idxs = _clip_indices(len(beats), clip_beats) if visual == "mixed" else set()
        if visual == "mixed":
            log.info("mixed: LTX clip on beats %s, stills on the rest", sorted(clip_idxs))
        segments = []
        for bi, b in enumerate(beats):
            mini = {"title": scr["title"], "explanation": b["visual_cue"]}
            vmode = ("clip" if bi in clip_idxs else "image") if visual == "mixed" else visual
            kind, path = _make_visual(cfg, mini, jdir, f"_{idx:02d}_{bi:02d}", vmode, gw, gh)
            segments.append({"start": bounds[bi][0], "end": bounds[bi][1],
                             "kind": kind, "path": str(path) if path else None})
        final = build_short(cfg, wav, srt_path, out_dir / f"{stem}.mp4",
                            title=scr["title"], segments=segments)
    else:
        # short: single visual (mixed -> one LTX clip for the whole short)
        wav = synthesize(cfg, scr["narration"], jdir / f"voice{idx:02d}.wav")
        srt_path = transcribe(cfg, wav, jdir / "captions.srt")
        vmode = "clip" if visual == "mixed" else visual
        kind, path = _make_visual(cfg, concept, jdir, f"_{idx:02d}", vmode, gw, gh)
        seg = [{"start": 0.0, "end": 0.0, "kind": kind, "path": str(path) if path else None}]
        final = build_short(cfg, wav, srt_path, out_dir / f"{stem}.mp4",
                            title=scr["title"], segments=seg)

    meta = gen_metadata(cfg, scr["title"], scr["narration"], concept["title"])
    meta.update({"job": job, "channel": chan(cfg, "name", "finance"), "video_file": final.name,
                 "est_seconds": scr["est_seconds"], "word_count": scr["word_count"]})
    meta_path = out_dir / f"{stem}.metadata.json"
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return final, meta


def run(source: str, duration: str | None = None,
        output_dir: str | None = None, work_dir: str | None = None,
        visual: str = "auto", channel: str = "finance", count: int = 1,
        clip_beats: int = 3) -> list[Path]:
    cfg = load_config(channel=channel)
    work = _dir(cfg, "work", work_dir)
    out_dir = _dir(cfg, "output", output_dir)
    job = time.strftime("%Y%m%d-%H%M%S")
    jdir = work / job
    jdir.mkdir(parents=True, exist_ok=True)
    log.info("=== job %s | channel=%s | source=%s | count=%d ===", job, channel, source, count)

    lo_s, hi_s = parse_duration(duration, cfg)
    gen_wh = _apply_aspect(cfg, longform=hi_s > 120)

    concepts = extract_concepts(cfg, source, count)
    outputs = []
    for idx, concept in enumerate(concepts, 1):
        log.info("--- video %d/%d: %s ---", idx, len(concepts), concept["title"])
        final, meta = _produce(cfg, concept, duration, visual, out_dir, jdir, gen_wh,
                               idx, len(concepts), clip_beats=clip_beats)
        outputs.append(final)
        print("\n" + "=" * 60)
        print(f"  APPROVAL GATE — review before upload ({idx}/{len(concepts)}, nothing published)")
        print("=" * 60)
        print(f"  Channel  : {channel}")
        print(f"  Title    : {meta['title']}")
        print(f"  Concept  : {concept['title']}")
        print(f"  Video    : {final}")
        print("=" * 60)
    return outputs


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", required=True, help="path to .pdf/.txt OR an audio/video file")
    ap.add_argument("--channel", default="finance", help="channel profile in channels/ (finance|education|spirituality)")
    ap.add_argument("--count", type=int, default=1, help="how many lesson videos to make from the source")
    ap.add_argument("--duration", default="short",
                    help="short|shorts, or e.g. 60s, 90, 3min, 5min (default: short)")
    ap.add_argument("--output", default=None, help="output dir for finished video+metadata")
    ap.add_argument("--work", default=None, help="dir for intermediates (voice/captions/images)")
    ap.add_argument("--visual", default="auto", choices=["auto", "image", "chart", "clip", "mixed", "none"],
                    help="per-beat visual: auto=SDXL image if ComfyUI up else chart; "
                         "clip=LTX AI B-roll every beat (SLOW); mixed=SDXL stills + LTX on a few "
                         "key beats (--clip-beats); none=gradient")
    ap.add_argument("--clip-beats", type=int, default=3,
                    help="mixed mode: how many beats get an LTX clip (spread evenly, incl. the hook)")
    args = ap.parse_args()
    run(args.source, duration=args.duration, output_dir=args.output, work_dir=args.work,
        visual=args.visual, channel=args.channel, count=args.count, clip_beats=args.clip_beats)
