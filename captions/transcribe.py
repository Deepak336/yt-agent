"""captions: voice.wav -> word-timed .srt via faster-whisper.

We transcribe our OWN narration (not someone else's audio). CPU in Phase 1 to
avoid ctranslate2/CUDA-on-Jetson setup; audio is short so it's fast enough.
Captions are grouped into short phrases for readable Shorts-style subtitles.
"""
from __future__ import annotations
import subprocess
import tempfile
import wave
from datetime import timedelta
from pathlib import Path

import numpy as np
import srt

from common import get_logger, ffmpeg_bin

log = get_logger("captions")

WHISPER_SR = 16000


def _ts(seconds: float) -> timedelta:
    return timedelta(seconds=max(0.0, float(seconds)))


def _decode_audio(wav: Path) -> np.ndarray:
    """Decode to 16kHz mono float32 via system ffmpeg, then load in Python.

    The Jetson ffmpeg is a stripped --disable-everything build with no raw PCM
    (f32le) muxer, so we resample to a 16kHz s16 WAV (wav muxer IS enabled) and
    convert int16 -> float32 ourselves. Avoids faster-whisper's PyAV decoder.
    """
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=True) as tmp:
        subprocess.run(
            [ffmpeg_bin(), "-y", "-nostdin", "-i", str(wav),
             "-ac", "1", "-ar", str(WHISPER_SR), "-c:a", "pcm_s16le", tmp.name],
            check=True, capture_output=True,
        )
        with wave.open(tmp.name, "rb") as w:
            frames = w.readframes(w.getnframes())
    return np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0


def _load_model(cfg: dict):
    from faster_whisper import WhisperModel
    model_name = cfg["models"]["whisper_model"]
    device = cfg["models"]["whisper_device"]
    compute = "int8" if device == "cpu" else "float16"
    log.info("loading faster-whisper %s (%s/%s)", model_name, device, compute)
    return WhisperModel(model_name, device=device, compute_type=compute)


def transcribe_text(cfg: dict, media: Path) -> str:
    """Full plain-text transcript of any audio/video file (ingest for video input)."""
    model = _load_model(cfg)
    audio = _decode_audio(Path(media))
    log.info("transcribing %s (%.1fs audio) ...", Path(media).name, len(audio) / WHISPER_SR)
    segments, _ = model.transcribe(audio, vad_filter=True)
    return " ".join(s.text.strip() for s in segments).strip()


def transcribe(cfg: dict, wav: Path, out_srt: Path, words_per_cue: int = 4) -> Path:
    model = _load_model(cfg)
    audio = _decode_audio(Path(wav))
    segments, _ = model.transcribe(audio, word_timestamps=True, vad_filter=True)

    cues, buf, start = [], [], None
    for seg in segments:
        for w in (seg.words or []):
            if start is None:
                start = w.start
            buf.append(w.word)
            if len(buf) >= words_per_cue:
                cues.append(srt.Subtitle(len(cues) + 1, _ts(start), _ts(w.end), "".join(buf).strip()))
                buf, start = [], None
    if buf:
        cues.append(srt.Subtitle(len(cues) + 1, _ts(start), _ts(w.end), "".join(buf).strip()))

    out_srt = Path(out_srt)
    out_srt.write_text(srt.compose(cues), encoding="utf-8")
    log.info("wrote %d caption cues -> %s", len(cues), out_srt.name)
    return out_srt
