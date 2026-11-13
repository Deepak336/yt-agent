"""assemble: voice.wav + captions.srt (+ visuals) -> WxH mp4.

Visuals are a TIMELINE of segments (one per script beat). Each segment is an
SDXL image (Ken Burns), an illustrative chart (inset, Ken Burns), an LTX clip
(ping-pong loop), or a plain gradient. A short video is just a 1-segment timeline
(back-compat). Segments crossfade into each other. Title (top) + word-timed
captions (lower third) are drawn on every frame.

Layout adapts to orientation (portrait 9:16 vs landscape 16:9). Frames are rendered
with Pillow (RGB->yuv420p in NumPy) and piped to the PyPI-bundled ffmpeg (libx264+
aac), because the Jetson system ffmpeg is a stripped build with no filters.
"""
from __future__ import annotations
import math
import subprocess
import wave
from pathlib import Path

import numpy as np
import srt
from PIL import Image, ImageDraw, ImageFont

from common import get_logger, ffmpeg_bin

log = get_logger("assemble")

_FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
ZOOM_STEPS = 48
XFADE = 0.4   # seconds of crossfade between consecutive segments


def _hex_rgb(h: str) -> tuple[int, int, int]:
    h = h.lower().replace("0x", "").replace("#", "")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _rgb_to_i420(img: Image.Image) -> bytes:
    a = np.asarray(img, dtype=np.float32)
    R, G, B = a[..., 0], a[..., 1], a[..., 2]
    Y = 0.299 * R + 0.587 * G + 0.114 * B
    U = -0.168736 * R - 0.331264 * G + 0.5 * B + 128.0
    V = 0.5 * R - 0.418688 * G - 0.081312 * B + 128.0
    H, W = Y.shape
    Yb = np.clip(Y, 0, 255).astype(np.uint8)
    Ub = np.clip(U.reshape(H // 2, 2, W // 2, 2).mean((1, 3)), 0, 255).astype(np.uint8)
    Vb = np.clip(V.reshape(H // 2, 2, W // 2, 2).mean((1, 3)), 0, 255).astype(np.uint8)
    return Yb.tobytes() + Ub.tobytes() + Vb.tobytes()


def _wav_duration(wav: Path) -> float:
    with wave.open(str(wav), "rb") as w:
        return w.getnframes() / float(w.getframerate())


def _wrap(draw, text, font, max_w):
    lines, cur = [], ""
    for word in text.split():
        trial = (cur + " " + word).strip()
        if draw.textlength(trial, font=font) <= max_w or not cur:
            cur = trial
        else:
            lines.append(cur); cur = word
    if cur:
        lines.append(cur)
    return lines


def _draw_center(draw, lines, font, y, w, fill, stroke=0, stroke_fill=(0, 0, 0)):
    for line in lines:
        tw = draw.textlength(line, font=font)
        draw.text(((w - tw) / 2, y), line, font=font, fill=fill,
                  stroke_width=stroke, stroke_fill=stroke_fill)
        y += int(sum(font.getmetrics()) * 1.15)
    return y


def _gradient_bg(W, H, base):
    top = np.array(base, dtype=np.float32)
    bot = np.clip(top * 0.55, 0, 255)
    t = np.linspace(0, 1, H, dtype=np.float32)[:, None]
    arr = np.repeat((top[None, :] * (1 - t) + bot[None, :] * t)[:, None, :], W, axis=1)
    return Image.fromarray(arr.astype(np.uint8), "RGB")


def _cover_fit(img, W, H):
    """Resize to cover WxH (preserve aspect, center-crop)."""
    s = max(W / img.width, H / img.height)
    img = img.resize((int(img.width * s) + 1, int(img.height * s) + 1), Image.LANCZOS)
    l, t = (img.width - W) // 2, (img.height - H) // 2
    return img.crop((l, t, l + W, t + H))


def _legibility_overlay(W, H):
    """Dark-at-top-and-bottom RGBA gradient so text stays readable over an image."""
    y = np.linspace(0, 1, H, dtype=np.float32)
    a = (np.clip(1 - y / 0.33, 0, 1) * 0.72 + np.clip((y - 0.6) / 0.4, 0, 1) * 0.80)
    alpha = np.clip(a, 0, 0.88)
    rgba = np.zeros((H, W, 4), dtype=np.uint8)
    rgba[..., 3] = np.repeat((alpha * 255)[:, None], W, axis=1).astype(np.uint8)
    return Image.fromarray(rgba, "RGBA")


def _decode_clip_frames(clip_mp4: Path, W: int, H: int) -> list[Image.Image]:
    """Decode a video clip to RGB frames, cover-fit to WxH + legibility overlay.
    Title is added later per-frame (so it matches the current segment)."""
    tmp = Path(clip_mp4).parent / (Path(clip_mp4).stem + "_decoded")
    tmp.mkdir(parents=True, exist_ok=True)
    subprocess.run([ffmpeg_bin(), "-y", "-nostdin", "-i", str(clip_mp4),
                    str(tmp / "d_%04d.png")], check=True, capture_output=True)
    overlay = _legibility_overlay(W, H)
    frames = []
    for p in sorted(tmp.glob("d_*.png")):
        img = _cover_fit(Image.open(p).convert("RGB"), W, H).convert("RGBA")
        img.alpha_composite(overlay)
        frames.append(img.convert("RGB"))
    log.info("clip: decoded %d bg frames", len(frames))
    return frames


class _Segment:
    """Produces the background frame (visual + title, NO captions) for a beat,
    given local time within the segment. Cached by zoom-step / clip-frame."""

    def __init__(self, cfg, seg, W, H, title, title_font, title_y, grad):
        self.W, self.H = W, H
        self.title, self.title_font, self.title_y = title, title_font, title_y
        self.dur = max(seg["end"] - seg["start"], 1e-3)
        self.kind = seg.get("kind", "gradient")
        path = seg.get("path")
        self._cache: dict = {}
        self.grad = grad

        if self.kind == "image" and path and Path(path).exists():
            self.img_fit = _cover_fit(Image.open(path).convert("RGB"), W, H)
            self.overlay = _legibility_overlay(W, H)
        elif self.kind == "chart" and path and Path(path).exists():
            self._prep_chart(path)
        elif self.kind == "clip" and path and Path(path).exists():
            self.frames = _decode_clip_frames(Path(path), W, H)
            if not self.frames:
                self.kind = "gradient"
        else:
            self.kind = "gradient"

        # gradient/chart share a title-baked gradient base
        if self.kind in ("gradient", "chart"):
            self.base_grad = self._bake_title(grad.copy())

    def _prep_chart(self, path):
        ch = Image.open(path).convert("RGB")
        box_h = int(self.H * 0.34)
        box_w = min(int(self.W * 0.86), int(box_h * ch.width / ch.height))
        self.chart_fit = ch.resize((box_w, box_h), Image.LANCZOS)
        self.box_w, self.box_h = box_w, box_h
        self.box_x = (self.W - box_w) // 2
        self.box_y = int(self.H * (0.12 if self.H >= self.W else 0.18))

    def _bake_title(self, img):
        bd = ImageDraw.Draw(img)
        tl = _wrap(bd, self.title, self.title_font, int(self.W * 0.84))
        ty = _draw_center(bd, tl, self.title_font, self.title_y, self.W, fill=(240, 240, 245))
        bd.rectangle([self.W * 0.30, ty + 18, self.W * 0.70, ty + 24], fill=(90, 130, 220))
        return img

    def _draw_title_over(self, img):
        dd = ImageDraw.Draw(img)
        _draw_center(dd, _wrap(dd, self.title, self.title_font, int(self.W * 0.84)),
                     self.title_font, self.title_y, self.W,
                     fill=(245, 245, 250), stroke=3, stroke_fill=(0, 0, 0))

    def base(self, local_t: float) -> Image.Image:
        """Return a fresh RGB background frame (title baked, no captions)."""
        W, H = self.W, self.H
        if self.kind == "clip":
            n = len(self.frames)
            fi = int(round(local_t * 30))  # clip frames indexed at ~30fps of timeline
            if n > 1:
                period = 2 * (n - 1)
                p = fi % period
                fi = p if p < n else period - p
            else:
                fi = 0
            key = ("f", fi)
            if key not in self._cache:
                img = self.frames[fi].copy()
                self._draw_title_over(img)
                self._cache[key] = img
            return self._cache[key].copy()

        z = min(max(local_t / self.dur, 0.0), 1.0)
        zstep = int(z * ZOOM_STEPS)
        if zstep in self._cache:
            return self._cache[zstep].copy()
        s = 1.0 + 0.08 * (zstep / ZOOM_STEPS)
        if self.kind == "image":
            nw, nh = int(W * s), int(H * s)
            zim = self.img_fit.resize((nw, nh), Image.BILINEAR)
            l, t = (nw - W) // 2, (nh - H) // 2
            img = zim.crop((l, t, l + W, t + H)).convert("RGBA")
            img.alpha_composite(self.overlay)
            img = img.convert("RGB")
            self._draw_title_over(img)
        elif self.kind == "chart":
            img = self.base_grad.copy()
            nw, nh = int(self.box_w * s), int(self.box_h * s)
            z2 = self.chart_fit.resize((nw, nh), Image.BILINEAR)
            l, t = (nw - self.box_w) // 2, (nh - self.box_h) // 2
            img.paste(z2.crop((l, t, l + self.box_w, t + self.box_h)), (self.box_x, self.box_y))
        else:  # gradient
            img = self.base_grad.copy()
        self._cache[zstep] = img
        return img.copy()


def _normalize_segments(segments, duration):
    segs = sorted(segments, key=lambda s: s["start"])
    segs[0]["start"] = 0.0
    for i in range(len(segs) - 1):
        segs[i]["end"] = segs[i + 1]["start"]
    segs[-1]["end"] = duration
    return [s for s in segs if s["end"] - s["start"] > 1e-3]


def build_short(cfg: dict, wav: Path, srt_path: Path, out_mp4: Path,
                title: str = "", chart_png: Path | None = None,
                bg_image: Path | None = None, clip_mp4: Path | None = None,
                segments: list[dict] | None = None) -> Path:
    v = cfg["video"]
    W, H, fps = v["width"], v["height"], v["fps"]
    out = Path(out_mp4).with_suffix(".mp4")
    out.parent.mkdir(parents=True, exist_ok=True)
    duration = _wav_duration(Path(wav))

    # Back-compat: a single visual becomes one full-length segment.
    if not segments:
        kind = "clip" if (clip_mp4 and Path(clip_mp4).exists()) else \
               "image" if (bg_image and Path(bg_image).exists()) else \
               "chart" if (chart_png and Path(chart_png).exists()) else "gradient"
        path = clip_mp4 if kind == "clip" else bg_image if kind == "image" else \
               chart_png if kind == "chart" else None
        segments = [{"start": 0.0, "end": duration, "kind": kind, "path": path}]
    segments = _normalize_segments(segments, duration)

    portrait = H >= W
    base_dim = min(W, H)
    title_font = ImageFont.truetype(_FONT_BOLD, max(28, round(base_dim * 0.052)))
    cap_font = ImageFont.truetype(_FONT_BOLD, max(30, round(base_dim * 0.057)))
    title_y = int(H * (0.08 if portrait else 0.06))
    cap_y = int(H * (0.72 if portrait else 0.80))
    grad = _gradient_bg(W, H, _hex_rgb(v["bg_color"]))

    renderers = [_Segment(cfg, s, W, H, title, title_font, title_y, grad) for s in segments]
    log.info("timeline: %d segment(s), kinds=%s, %.1fs @ %dfps %dx%d",
             len(segments), [s["kind"] for s in segments], duration, fps, W, H)

    cues = list(srt.parse(Path(srt_path).read_text(encoding="utf-8")))

    def caption_at(t):
        for c in cues:
            if c.start.total_seconds() <= t < c.end.total_seconds():
                return c.content.replace("\n", " ").strip()
        return ""

    def seg_index(t):
        for i, s in enumerate(segments):
            if s["start"] <= t < s["end"]:
                return i
        return len(segments) - 1

    def draw_caption(img, text):
        if not text:
            return
        dd = ImageDraw.Draw(img)
        lines = _wrap(dd, text, cap_font, int(W * 0.86))
        block_h = len(lines) * int(sum(cap_font.getmetrics()) * 1.15)
        _draw_center(dd, lines, cap_font, cap_y - block_h // 2, W,
                     fill=(255, 255, 255), stroke=6, stroke_fill=(0, 0, 0))

    total = math.ceil(duration * fps)
    fcache: dict[tuple, bytes] = {}

    def render(i):
        t = i / fps
        k = seg_index(t)
        seg = segments[k]
        text = caption_at(t)
        local_t = t - seg["start"]
        # crossfade into the next segment during the last XFADE seconds
        in_xfade = (k < len(segments) - 1) and (t > seg["end"] - XFADE)
        if not in_xfade:
            zstep = int(min(local_t / max(seg["end"] - seg["start"], 1e-3), 1.0) * ZOOM_STEPS) \
                if renderers[k].kind != "clip" else int(round(local_t * 30))
            key = (k, zstep, text)
            if key in fcache:
                return fcache[key]
            img = renderers[k].base(local_t)
            draw_caption(img, text)
            buf = _rgb_to_i420(img)
            fcache[key] = buf
            return buf
        # crossfade: blend current seg frame with next seg's first frame
        alpha = (t - (seg["end"] - XFADE)) / XFADE
        a = np.asarray(renderers[k].base(local_t), dtype=np.float32)
        b = np.asarray(renderers[k + 1].base(0.0), dtype=np.float32)
        img = Image.fromarray(np.clip(a * (1 - alpha) + b * alpha, 0, 255).astype(np.uint8), "RGB")
        draw_caption(img, text)
        return _rgb_to_i420(img)

    log.info("rendering %d frames", total)
    enc = v["encoder"]
    venc = (["-preset", "veryfast", "-crf", "20"] if enc.startswith("libx264") else ["-b:v", v["bitrate"]])
    cmd = [ffmpeg_bin(), "-y", "-nostdin",
           "-f", "rawvideo", "-pix_fmt", "yuv420p", "-s", f"{W}x{H}", "-r", str(fps), "-i", "pipe:0",
           "-i", str(Path(wav).resolve()),
           "-c:v", enc, *venc, "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart",
           "-shortest", str(out.resolve())]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        for i in range(total):
            proc.stdin.write(render(i))
        proc.stdin.close()
    except BrokenPipeError:
        pass
    err = proc.stderr.read().decode(errors="ignore")
    if proc.wait() != 0:
        log.error("ffmpeg failed:\n%s", err[-2000:])
        raise RuntimeError("ffmpeg assembly failed")
    log.info("done: %s (%.1f MB)", out, out.stat().st_size / 1e6)
    return out
