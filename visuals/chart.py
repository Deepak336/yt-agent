"""visuals: concept -> one dark-themed Matplotlib chart PNG.

The LLM proposes a small *illustrative* chart spec (not real statistics — we label
it as such to stay honest/educational). Robust: returns None on any failure so the
pipeline falls back to text-only.
"""
from __future__ import annotations
import json
import re
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from common import llm, get_logger

log = get_logger("visuals")

_BG = "#0B132B"
_ACCENT = "#5A82DC"
_FG = "#F0F0F5"


def _spec(cfg: dict, concept: dict) -> dict | None:
    out = llm(
        cfg,
        "Propose a simple ILLUSTRATIVE chart that visually supports this concept "
        f"(not real data):\nTITLE: {concept['title']}\nNOTES: {concept['explanation']}\n\n"
        'Return ONLY JSON: {"type":"line|bar","title":"<=40 chars",'
        '"xlabel":"","ylabel":"","x":["a","b","c"],"y":[1,2,3]}. '
        "3-6 points, y are plain numbers.",
        temperature=0.4, num_predict=250,
    )
    m = re.search(r"\{.*\}", out, re.DOTALL)
    if not m:
        return None
    try:
        spec = json.loads(m.group(0))
        if spec.get("type") not in ("line", "bar"):
            return None
        x = [str(v) for v in spec["x"]]
        y = [float(v) for v in spec["y"]]
        if len(x) != len(y) or len(y) < 2:
            return None
        spec["x"], spec["y"] = x, y
        return spec
    except Exception as e:
        log.warning("chart spec parse failed: %s", e)
        return None


def make_chart(cfg: dict, concept: dict, out_png: Path) -> Path | None:
    spec = _spec(cfg, concept)
    if not spec:
        log.info("no valid chart spec; text-only")
        return None
    out_png = Path(out_png)
    try:
        fig, ax = plt.subplots(figsize=(9, 6.5), dpi=120)
        fig.patch.set_facecolor(_BG)
        ax.set_facecolor(_BG)
        x, y = spec["x"], spec["y"]
        if spec["type"] == "bar":
            ax.bar(x, y, color=_ACCENT)
        else:
            ax.plot(x, y, color=_ACCENT, linewidth=4, marker="o", markersize=9)
            ax.fill_between(range(len(x)), y, color=_ACCENT, alpha=0.18)
        ax.set_title(spec.get("title", concept["title"])[:40], color=_FG, fontsize=22, pad=16, weight="bold")
        ax.set_xlabel(spec.get("xlabel", ""), color=_FG, fontsize=15)
        ax.set_ylabel(spec.get("ylabel", ""), color=_FG, fontsize=15)
        ax.tick_params(colors=_FG, labelsize=13)
        for s in ax.spines.values():
            s.set_color("#33406080")
        ax.grid(True, color="#33406055", linewidth=0.8)
        fig.text(0.99, 0.01, "illustrative", color="#7788AA", fontsize=10, ha="right", va="bottom")
        fig.tight_layout()
        fig.savefig(out_png, facecolor=_BG, bbox_inches="tight")
        plt.close(fig)
        log.info("chart: %s (%s, %d pts)", out_png.name, spec["type"], len(y))
        return out_png
    except Exception as e:
        log.warning("chart render failed: %s", e)
        plt.close("all")
        return None
