"""Shared helpers: config loading, paths, logging, and the Ollama LLM call.

Methodology (yt-agent-context.md): staged models, ORIGINAL wording only,
human approval gate before publish.
"""
from __future__ import annotations
import logging
import re
import sys
from pathlib import Path

import yaml

# Keep ASCII + Latin-1/Extended (accents); drop CJK/other scripts that Qwen
# occasionally leaks into image/clip prompts (SDXL/LTX are English-only anyway).
_NON_LATIN = re.compile(r"[^\x00-ɏ]+")


def english_only(s: str) -> str:
    """Strip non-Latin characters (e.g. leaked Chinese) and collapse whitespace."""
    return re.sub(r"\s+", " ", _NON_LATIN.sub(" ", s)).strip()

ROOT = Path(__file__).resolve().parent


def load_channel(name: str) -> dict:
    """Load a channel profile (persona/voice/visual-style/metadata/aspect) from
    channels/<name>.yaml. Returns {} if the file is missing so every stage falls
    back to its built-in finance defaults."""
    if not name:
        return {}
    p = ROOT / "channels" / f"{name}.yaml"
    if not p.exists():
        logging.getLogger("common").warning(
            "channel profile %s not found at %s; using built-in defaults", name, p)
        return {}
    with open(p, "r", encoding="utf-8") as f:
        prof = yaml.safe_load(f) or {}
    prof.setdefault("name", name)
    return prof


def load_config(channel: str = "finance") -> dict:
    """Load the pipeline config and merge the chosen channel profile under
    cfg['channel']. Default channel is finance (backward compatible)."""
    with open(ROOT / "config.yaml", "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    cfg["channel"] = load_channel(channel)
    return cfg


def get_logger(name: str) -> logging.Logger:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-5s  %(name)s  %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stdout,
    )
    return logging.getLogger(name)


def chan(cfg: dict, key: str, default=None):
    """Read a field from the active channel profile, falling back to `default`
    (usually the stage's original hardcoded constant)."""
    return (cfg.get("channel") or {}).get(key, default)


def ffmpeg_bin() -> str:
    """Full-featured ffmpeg (libx264/aac/filters) bundled via imageio-ffmpeg.

    The system (NVIDIA Jetson) ffmpeg is a stripped transcode-only build whose
    NVENC path fails on this device, so we use the PyPI static build instead.
    """
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return "ffmpeg"


def path_in(cfg: dict, key: str) -> Path:
    """Resolve a configured relative path against the repo root, ensuring it exists."""
    p = ROOT / cfg["paths"][key]
    p.mkdir(parents=True, exist_ok=True)
    return p


def llm(cfg: dict, prompt: str, system: str | None = None,
        temperature: float = 0.7, num_predict: int = 700) -> str:
    """Single-turn generation via the local Ollama daemon. Model stays resident
    between calls, so we never hold two heavy models at once."""
    import ollama  # imported lazily so modules that don't need it still load
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    resp = ollama.chat(
        model=cfg["models"]["llm"],
        messages=messages,
        options={"temperature": temperature, "num_predict": num_predict},
    )
    return resp["message"]["content"].strip()
