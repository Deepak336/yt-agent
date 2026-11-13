"""script: concept note -> narration (original wording) + a title.

Short videos (<=120s) stay single-beat. Long videos return a list of BEATS —
each a short narration chunk plus a VISUAL cue — so the assembler can show a
fresh visual every ~15-20s instead of one static background.

Persona/tone come from the active channel profile (cfg['channel']); the finance
constants below are the fallback.
"""
from __future__ import annotations
import re

from common import llm, get_logger, chan

log = get_logger("script")

_SCRIPT_SYSTEM = (
    "You write punchy, accurate short-form narration for a finance/economics explainer "
    "channel. Conversational, concrete, zero fluff. You use ONLY your own words. You never "
    "give regulated financial advice — you educate. No emojis, no stage directions, no "
    "hashtags: output is spoken aloud verbatim."
)

_BEAT_SECONDS = 18   # target spoken seconds per beat (drives how many beats)


def parse_duration(spec: str | None, cfg: dict) -> tuple[int, int]:
    """Return a (lo, hi) seconds window from a duration spec.

    Accepts: None/"short"/"shorts" -> config default window; "90s"/"90";
    "3min"/"3m"; or a bare integer number of seconds. Window is +-15% of target
    (shorts clamped to the configured short window).
    """
    if not spec or spec.lower() in ("short", "shorts"):
        lo, hi = cfg["script"]["target_seconds"]
        return int(lo), int(hi)
    s = spec.strip().lower()
    if s.endswith(("min", "m")):
        secs = float(s.rstrip("min").rstrip("m")) * 60
    else:
        secs = float(s.rstrip("s"))
    return int(secs * 0.85), int(secs * 1.15)


def _words(seconds: int, cfg: dict) -> int:
    return int(seconds * cfg["script"]["words_per_minute"] / 60)


def _catchy_title(cfg: dict, topic: str) -> str:
    raw_title = llm(
        cfg,
        "Write ONE catchy YouTube title: 4-8 words, Title Case, no quotes, "
        "no hashtags, no colons, and do NOT append phrases like 'explained in 60 "
        f"seconds'. Topic: {topic}",
        temperature=0.7, num_predict=40,
    )
    line = next((l for l in raw_title.splitlines() if l.strip()), topic)
    return " ".join(line.split()).strip().strip('"').strip("*")[:70]


def _split_into_beats(narration: str, n: int) -> list[dict]:
    """Fallback: group sentences of a plain narration into n beats; the beat text
    doubles as its own visual cue."""
    sents = re.split(r"(?<=[.!?])\s+", narration.strip())
    sents = [s for s in sents if s.strip()]
    n = max(1, min(n, len(sents)))
    per = max(1, len(sents) // n)
    beats = []
    for i in range(0, len(sents), per):
        chunk = " ".join(sents[i:i + per]).strip()
        if chunk:
            beats.append({"narration": chunk, "visual_cue": chunk})
    return beats


def _parse_beats(out: str) -> list[dict]:
    beats = []
    for block in re.split(r"\[BEAT\]", out):
        if not block.strip():
            continue
        nm = re.search(r"NARRATION:\s*(.+?)(?:\nVISUAL:|$)", block, re.DOTALL)
        vm = re.search(r"VISUAL:\s*(.+)", block, re.DOTALL)
        narr = (nm.group(1).strip() if nm else "").strip()
        if not narr:
            continue
        vis = (vm.group(1).strip() if vm else narr).strip()
        beats.append({"narration": narr, "visual_cue": vis})
    return beats


def _write_longform(cfg: dict, concept: dict, lo_s: int, hi_s: int,
                    lo: int, hi: int, system: str, mode: str) -> list[dict]:
    n = max(3, min(12, round(hi_s / _BEAT_SECONDS)))
    mins = max(1, round(hi_s / 60))
    min_wpb = int(cfg["script"].get("min_words_per_beat", 35))
    # aim each beat at the average needed to hit the word window, but never below the floor
    per_beat = max(min_wpb, round(((lo + hi) / 2) / n))
    if mode == "story":
        arc = ("forming a narrative arc: a relatable opening moment, a rising insight "
               "developed with a concrete example, a turning point, and a calm actionable takeaway")
    else:
        arc = ("beat 1 is a strong hook; each middle beat develops ONE point with a concrete "
               "everyday example; the final beat recaps with a one-line takeaway")
    prompt = (
        f"Concept to explain:\nTITLE: {concept['title']}\nNOTES: {concept['explanation']}\n\n"
        f"Write a ~{mins}-minute spoken narration as EXACTLY {n} beats, {arc}. "
        f"Total {lo}-{hi} words across all beats — this length matters, do not come in short. "
        f"Each beat MUST be at least {min_wpb} words (aim for about {per_beat}), roughly 3-5 full "
        "sentences that flow into the next.\n"
        "For each beat also give a short VISUAL cue: one concrete scene or object to show on "
        "screen (6-12 words), no text/words/letters in the image.\n\n"
        "Output ONLY this repeated block, nothing else:\n"
        "[BEAT]\nNARRATION: <spoken sentences, your own words>\nVISUAL: <concrete visual scene>\n"
    )
    out = llm(cfg, prompt, system=system, temperature=0.8,
              num_predict=min(3000, int(hi * 2.4) + 300))
    beats = _parse_beats(out)
    if len(beats) < 2:
        log.warning("structured beats parse weak (%d); falling back to plain+split", len(beats))
        body = (
            f"Write a flowing {lo}-{hi} word spoken narration for a ~{mins}-minute video: "
            "a strong hook, 3-5 developed points each with a concrete example, and a short "
            "recap. No headings or bullets. Your own words only. Output ONLY the narration."
        )
        plain = llm(cfg, f"Concept:\nTITLE: {concept['title']}\nNOTES: {concept['explanation']}\n\n"
                    + body, system=system, temperature=0.8, num_predict=min(3000, int(hi * 2.0) + 200))
        plain = re.sub(r"\n{3,}", "\n\n", plain).strip()
        beats = _split_into_beats(plain, n)
    return beats


def write_script(cfg: dict, concept: dict, duration: str | None = None) -> dict:
    lo_s, hi_s = parse_duration(duration, cfg)
    lo, hi = _words(lo_s, cfg), _words(hi_s, cfg)
    longform = hi_s > 120
    system = chan(cfg, "script_system", _SCRIPT_SYSTEM)
    mode = chan(cfg, "script_mode", "explainer")

    beats = None
    if longform:
        beats = _write_longform(cfg, concept, lo_s, hi_s, lo, hi, system, mode)
        narration = "\n\n".join(b["narration"] for b in beats)
    else:
        if mode == "story":
            body = (
                f"Write a vertical-video narration of {lo}-{hi} words:\n"
                "1. A relatable opening line.\n"
                "2. One insight shown through a simple everyday example.\n"
                "3. A calm one-line takeaway."
            )
        else:
            body = (
                f"Write a vertical-video narration of {lo}-{hi} words:\n"
                "1. A hook in the first line that creates curiosity.\n"
                "2. A clear explanation with one concrete everyday example.\n"
                "3. A one-line takeaway."
            )
        prompt = (
            f"Concept to explain:\nTITLE: {concept['title']}\n"
            f"NOTES: {concept['explanation']}\n\n" + body + "\n"
            "Rules: your own words only, spoken style, no labels/headers, no hashtags. "
            "Output ONLY the narration text."
        )
        narration = llm(cfg, prompt, system=system, temperature=0.8,
                        num_predict=min(2200, int(hi * 1.8) + 100))
        narration = re.sub(r"\n{3,}", "\n\n", narration).strip()

    wc = len(narration.split())
    est = round(wc / cfg["script"]["words_per_minute"] * 60)
    log.info("script: %d words (~%ds)%s", wc, est,
             f", {len(beats)} beats" if beats else "")
    if wc > hi * 1.3:
        log.warning("script longer than target window (%d > %d words)", wc, hi)
    elif beats and wc < lo * 0.8:
        log.warning("script shorter than target (%d < %d words); video will run short", wc, lo)

    title = _catchy_title(cfg, concept["title"])
    return {"title": title, "narration": narration, "beats": beats,
            "word_count": wc, "est_seconds": est}
