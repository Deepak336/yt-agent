"""ingest: source file -> raw text -> ONE teachable concept (in the LLM's own words).

Accepts .pdf (via pypdf) or .txt. The LLM re-expresses ideas; it never quotes
source sentences (copyright rule: ideas/facts are free, expression is not).
"""
from __future__ import annotations
import re
from pathlib import Path

from common import llm, get_logger, chan

log = get_logger("ingest")

MEDIA_EXT = {".mp4", ".mkv", ".mov", ".webm", ".m4v", ".avi",
             ".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".opus"}

_CONCEPT_SYSTEM = (
    "You are a finance/economics educator. You read source material only to LEARN "
    "the idea, then explain it entirely in your OWN words. You NEVER quote, copy, or "
    "closely paraphrase sentences from the source. Output only facts and concepts, "
    "which are not copyrightable."
)


def read_text(path: str | Path) -> str:
    path = Path(path)
    if path.suffix.lower() == ".pdf":
        from pypdf import PdfReader
        reader = PdfReader(str(path))
        text = "\n".join((page.extract_text() or "") for page in reader.pages)
    else:  # .txt and friends
        text = path.read_text(encoding="utf-8", errors="ignore")
    return text


def _strip_gutenberg(text: str) -> str:
    """Drop Project Gutenberg license headers/footers if present."""
    start = re.search(r"\*\*\* START OF.*?\*\*\*", text, re.DOTALL)
    if start:
        text = text[start.end():]
    end = re.search(r"\*\*\* END OF.*?\*\*\*", text, re.DOTALL)
    if end:
        text = text[:end.start()]
    return text


def pick_chunk(text: str, max_chars: int = 12000) -> str:
    """Take a substantive mid-document slice (skips front-matter/TOC)."""
    return _windows(text, 1, max_chars)[0]


def _windows(text: str, count: int, max_chars: int = 12000) -> list[str]:
    """Return `count` substantive text windows spread across the document, so
    successive lessons come from different parts of a book (not all one chapter)."""
    text = _strip_gutenberg(text)
    text = re.sub(r"\s+\n", "\n", text)
    start = min(len(text) // 20, 20000)         # skip ~5% front-matter/TOC
    span = max(len(text) - start, 0)
    if count <= 1 or span <= max_chars:
        return [text[start:start + max_chars]]
    step = max(span // count, 1)
    return [text[start + i * step: start + i * step + max_chars] for i in range(count)]


def _concept_from_chunk(cfg: dict, chunk: str, avoid: list[str] | None = None) -> dict:
    """LLM turns one text window into an original {title, explanation} concept note."""
    system = chan(cfg, "concept_system", _CONCEPT_SYSTEM)
    avoid_line = ""
    if avoid:
        avoid_line = ("Do NOT pick any of these already-covered concepts: "
                      + "; ".join(avoid) + ".\n")
    prompt = (
        "Below is source material. Identify ONE clear, self-contained concept a general "
        "audience would find interesting. Explain it in your OWN words — do not reuse the "
        "source's phrasing.\n" + avoid_line + "\n"
        "Return exactly this format:\n"
        "TITLE: <a short punchy concept name>\n"
        "EXPLANATION: <3-5 sentences, plain modern English, concrete example, original wording>\n\n"
        f"SOURCE MATERIAL:\n{chunk}"
    )
    out = llm(cfg, prompt, system=system, temperature=0.6, num_predict=500)

    title, explanation = "Untitled concept", out
    m = re.search(r"TITLE:\s*(.+)", out)
    if m:
        title = m.group(1).strip()
    m = re.search(r"EXPLANATION:\s*(.+)", out, re.DOTALL)
    if m:
        explanation = m.group(1).strip()
    log.info("concept: %s", title)
    return {"title": title, "explanation": explanation}


def _read_source(cfg: dict, source_path: str | Path) -> tuple[str, Path]:
    """Return (raw_text, path). Media files are transcribed first."""
    sp = Path(source_path)
    if sp.suffix.lower() in MEDIA_EXT:
        from captions.transcribe import transcribe_text
        raw = transcribe_text(cfg, sp)
    else:
        raw = read_text(sp)
    log.info("read %s (%d chars raw)", sp.name, len(raw))
    return raw, sp


def extract_concepts(cfg: dict, source_path: str | Path, count: int = 1) -> list[dict]:
    """Return up to `count` original concept notes from different parts of the source.

    Source may be a .pdf/.txt OR an audio/video file (transcribed first, then
    re-expressed in the LLM's own words — original content, not a copy).
    """
    raw, sp = _read_source(cfg, source_path)
    is_media = sp.suffix.lower() in MEDIA_EXT
    windows = ([raw[i:i + 16000] for i in
                range(0, min(len(raw), 16000 * max(count, 1)), 16000)][:count]
               if is_media else _windows(raw, count))
    if not windows:
        windows = [raw[:16000]]

    concepts: list[dict] = []
    for w in windows:
        c = _concept_from_chunk(cfg, w, avoid=[x["title"] for x in concepts])
        concepts.append(c)
    return concepts


def extract_concept(cfg: dict, source_path: str | Path) -> dict:
    """Single original concept note (back-compat wrapper over extract_concepts)."""
    return extract_concepts(cfg, source_path, 1)[0]
