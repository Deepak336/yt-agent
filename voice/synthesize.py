"""voice: narration text -> voice.wav via Piper (standalone aarch64 binary).

Piper binary + voice model live under models/piper/ (set up by scripts/setup_piper.sh).
Using the prebuilt binary avoids onnxruntime/piper-phonemize wheel issues on ARM/py3.12.
"""
from __future__ import annotations
import subprocess
import wave
from pathlib import Path

from common import ROOT, get_logger

log = get_logger("voice")

PIPER_DIR = ROOT / "models" / "piper"
PIPER_BIN = PIPER_DIR / "piper"


def _voice_model(cfg: dict) -> Path:
    # channel profile may override the default voice; fall back to models.tts_voice
    name = (cfg.get("channel") or {}).get("tts_voice") or cfg["models"]["tts_voice"]
    model = PIPER_DIR / f"{name}.onnx"
    if not model.exists():
        raise FileNotFoundError(
            f"Piper voice {name} not found at {model}. Run scripts/setup_piper.sh first."
        )
    return model


def synthesize(cfg: dict, narration: str, out_wav: Path) -> Path:
    if not PIPER_BIN.exists():
        raise FileNotFoundError(
            f"Piper binary not found at {PIPER_BIN}. Run scripts/setup_piper.sh first."
        )
    model = _voice_model(cfg)
    out_wav = Path(out_wav)
    out_wav.parent.mkdir(parents=True, exist_ok=True)

    cmd = [str(PIPER_BIN), "--model", str(model), "--output_file", str(out_wav)]
    log.info("piper -> %s", out_wav.name)
    subprocess.run(
        cmd, input=narration.encode("utf-8"),
        check=True, capture_output=True,
        cwd=str(PIPER_DIR),  # so it finds bundled espeak-ng-data
    )
    if not out_wav.exists():
        raise RuntimeError("Piper produced no output")
    return out_wav


def wav_seconds(wav: Path) -> float:
    with wave.open(str(wav), "rb") as w:
        return w.getnframes() / float(w.getframerate())


def concat_wavs(wavs: list[Path], out_wav: Path) -> Path:
    """Concatenate same-format PCM wavs (Piper beats share voice/sample-rate) into
    one file. Returns the combined path."""
    out_wav = Path(out_wav)
    with wave.open(str(wavs[0]), "rb") as w0:
        params = w0.getparams()
    with wave.open(str(out_wav), "wb") as out:
        out.setparams(params)
        for w in wavs:
            with wave.open(str(w), "rb") as wi:
                out.writeframes(wi.readframes(wi.getnframes()))
    return out_wav


def synthesize_beats(cfg: dict, beats: list[dict], jdir: Path) -> tuple[Path, list[tuple[float, float]]]:
    """Synthesize one wav per beat, concatenate to voice.wav, and return
    (voice_wav, [(start,end) per beat]) using exact per-beat durations."""
    jdir = Path(jdir)
    wavs, bounds, acc = [], [], 0.0
    for i, b in enumerate(beats):
        w = synthesize(cfg, b["narration"], jdir / f"beat{i:02d}.wav")
        wavs.append(w)
        d = wav_seconds(w)
        bounds.append((acc, acc + d))
        acc += d
    voice = concat_wavs(wavs, jdir / "voice.wav")
    log.info("beats: %d wavs -> %.1fs voice.wav", len(wavs), acc)
    return voice, bounds
