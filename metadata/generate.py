"""metadata: concept + script -> YouTube title/description/hashtags (original).

Educational framing; no financial advice. Returns a dict saved as metadata.json.
"""
from __future__ import annotations
import re

from common import llm, get_logger, chan

log = get_logger("metadata")


def generate(cfg: dict, title: str, narration: str, concept_title: str) -> dict:
    framing = chan(cfg, "metadata_framing", "educational, no financial advice, your own words")
    out = llm(
        cfg,
        f"Write a YouTube description for a short video ({framing}) "
        f"titled '{title}' about {concept_title}.\n"
        "Output exactly two lines:\n"
        "DESC: <2-3 sentences, no hashtags>\n"
        "TAGS: <5 lowercase hashtags separated by spaces, each starting with #>",
        temperature=0.7, num_predict=200,
    )
    m = re.search(r"DESC:\s*(.+?)(?:\n|TAGS:|$)", out, re.DOTALL)
    description = (m.group(1).strip() if m else out).strip()
    m = re.search(r"TAGS:\s*(.+)", out, re.DOTALL)
    tag_line = m.group(1) if m else ""
    # accept hashtags with or without leading '#'
    tags = ["#" + t.lstrip("#") for t in re.findall(r"#?\w{2,}", tag_line)]
    if not tags:
        tags = chan(cfg, "default_hashtags",
                    ["#finance", "#economics", "#explainer", "#money", "#learn"])
    meta = {
        "title": title,
        "description": description,
        "hashtags": tags[:5],
        "concept": concept_title,
        "category": chan(cfg, "category", "Education"),
    }
    log.info("metadata: %d-char description, %d tags", len(description), len(meta["hashtags"]))
    return meta
