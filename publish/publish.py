"""publish CLI — the human APPROVAL GATE in front of YouTube upload.

    python -m publish.publish data/output/short-<job>.mp4            # dry-run (prints plan)
    python -m publish.publish data/output/short-<job>.mp4 --yes      # upload (private)
    python -m publish.publish data/output/short-<job>.mp4 --yes --privacy unlisted

Rules (yt-agent-context.md §6/§7):
  - config publish.approval_gate=true  -> never uploads without --yes.
  - Default privacy is 'private' even after approval; promote to public deliberately.
  - Enforces publish.max_uploads_per_day (default 6) via a local day log so we never
    blow the 10,000-unit/day quota (videos.insert = 1,600 units).
"""
from __future__ import annotations
import argparse
import datetime as dt
import json
import sys
from pathlib import Path

from common import ROOT, load_config, get_logger

log = get_logger("publish")

DAY_LOG = ROOT / "data" / "secrets" / "publish_log.json"


def _sidecar_meta(video: Path) -> dict:
    """Finished videos are saved as short-<job>.mp4 beside short-<job>.metadata.json."""
    cand = video.with_suffix("").with_suffix(".metadata.json")
    if not cand.exists():
        cand = video.parent / (video.stem + ".metadata.json")
    if not cand.exists():
        raise FileNotFoundError(f"no metadata.json sidecar for {video.name} (looked for {cand.name})")
    return json.loads(cand.read_text(encoding="utf-8"))


def _today_count() -> int:
    if not DAY_LOG.exists():
        return 0
    data = json.loads(DAY_LOG.read_text(encoding="utf-8"))
    return len(data.get(dt.date.today().isoformat(), []))


def _record(video: Path, result: dict) -> None:
    DAY_LOG.parent.mkdir(parents=True, exist_ok=True)
    data = json.loads(DAY_LOG.read_text(encoding="utf-8")) if DAY_LOG.exists() else {}
    day = dt.date.today().isoformat()
    data.setdefault(day, []).append({"file": video.name, **result,
                                     "at": dt.datetime.now().isoformat(timespec="seconds")})
    DAY_LOG.write_text(json.dumps(data, indent=2), encoding="utf-8")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Upload a finished Short to YouTube (gated).")
    ap.add_argument("video", help="path to short-<job>.mp4")
    ap.add_argument("--yes", action="store_true", help="confirm upload (required when approval_gate is on)")
    ap.add_argument("--privacy", default="private", choices=["private", "unlisted", "public"])
    ap.add_argument("--made-for-kids", action="store_true")
    args = ap.parse_args(argv)

    cfg = load_config()
    video = Path(args.video).resolve()
    if not video.exists():
        log.error("no such file: %s", video); return 2
    meta = _sidecar_meta(video)

    tags = " ".join(meta.get("hashtags", []))
    print("\n=== UPLOAD PLAN (review before approving) ===")
    print(f"  file:        {video}")
    print(f"  title:       {meta.get('title')}")
    print(f"  category:    {meta.get('category')}")
    print(f"  hashtags:    {tags}")
    print(f"  description: {meta.get('description', '')[:280]}")
    print(f"  privacy:     {args.privacy}")
    print("=============================================\n")

    gate = cfg.get("publish", {}).get("approval_gate", True)
    cap = int(cfg.get("publish", {}).get("max_uploads_per_day", 6))
    used = _today_count()
    print(f"uploads today: {used}/{cap}")

    if used >= cap:
        log.error("daily upload cap reached (%d/%d) — try again tomorrow or raise the quota.", used, cap)
        return 3
    if gate and not args.yes:
        print("APPROVAL GATE is ON. This was a dry run — re-run with --yes to upload.")
        return 0

    from publish.youtube import upload_video  # lazy: avoids importing google libs on dry runs
    try:
        result = upload_video(video, meta, privacy=args.privacy, made_for_kids=args.made_for_kids)
    except Exception as e:
        log.error("upload failed: %s", e); return 1
    _record(video, result)
    print(f"\n✅ uploaded: {result['url']}  (privacy={result['privacy']})")
    print("   Review it in YouTube Studio; promote to public when you're happy.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
