"""script refinement: take the current narration + a natural-language instruction,
return a revised narration (Qwen). Powers the studio's interactive edit loop.
"""
from __future__ import annotations

from common import llm, get_logger, chan
from script.write import _SCRIPT_SYSTEM

log = get_logger("refine")


def refine_script(cfg: dict, current: str, instruction: str) -> str:
    if not instruction.strip():
        return current
    system = chan(cfg, "script_system", _SCRIPT_SYSTEM)
    prompt = (
        "Here is a short-video narration script:\n\n"
        f"\"\"\"\n{current}\n\"\"\"\n\n"
        f"Revise it according to this instruction: {instruction}\n\n"
        "Keep it spoken-style and in your OWN words. No labels, headings, stage "
        "directions, or hashtags. Output ONLY the revised narration text."
    )
    n = max(200, int(len(current.split()) * 1.8) + 80)
    out = llm(cfg, prompt, system=system, temperature=0.7, num_predict=n).strip()
    log.info("refined: %d -> %d words", len(current.split()), len(out.split()))
    return out
