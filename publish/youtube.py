"""publish: YouTube Data API v3 client — OAuth + resumable video upload.

NOTHING here uploads on import. Call upload_video() explicitly (the CLI in
publish/publish.py enforces the human APPROVAL GATE first).

Credentials (owner-provided, never commit):
  - client_secret.json : OAuth 2.0 *Desktop app* client from Google Cloud Console
      (enable "YouTube Data API v3"). Default path: data/secrets/client_secret.json
  - token.json         : cached user token, written after the first consent.
      Default path: data/secrets/token.json

Quota facts (see yt-agent-context.md §7): videos.insert costs 1,600 units; the
default daily quota is 10,000 units -> ~6 uploads/day. We never call search.list.

google client libs are imported lazily so the rest of the repo runs without them.
Install when ready:
  pip install google-api-python-client google-auth-oauthlib google-auth-httplib2
"""
from __future__ import annotations
from pathlib import Path

from common import ROOT, get_logger

log = get_logger("publish")

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
SECRETS_DIR = ROOT / "data" / "secrets"
CLIENT_SECRET = SECRETS_DIR / "client_secret.json"
TOKEN = SECRETS_DIR / "token.json"

# YouTube video category IDs (US). Education = 27, Science & Tech = 28.
CATEGORY_IDS = {"Education": "27", "Science & Technology": "28", "Entertainment": "24"}


def _require_libs():
    try:
        from googleapiclient.discovery import build  # noqa: F401
        from google_auth_oauthlib.flow import InstalledAppFlow  # noqa: F401
        from google.auth.transport.requests import Request  # noqa: F401
        from google.oauth2.credentials import Credentials  # noqa: F401
    except ImportError as e:
        raise RuntimeError(
            "YouTube upload needs Google client libs. Install with:\n"
            "  pip install google-api-python-client google-auth-oauthlib google-auth-httplib2"
        ) from e


def get_service():
    """Authenticated YouTube Data API service. Runs the OAuth consent flow on the
    first call (opens a local browser / prints a URL), then caches token.json."""
    _require_libs()
    from googleapiclient.discovery import build
    from google_auth_oauthlib.flow import InstalledAppFlow
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    if not CLIENT_SECRET.exists():
        raise FileNotFoundError(
            f"Missing OAuth client at {CLIENT_SECRET}.\n"
            "Create an OAuth 2.0 'Desktop app' client in Google Cloud Console "
            "(with YouTube Data API v3 enabled), download the JSON, and save it there."
        )

    creds = None
    if TOKEN.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN), SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_SECRET), SCOPES)
            # run_local_server works over SSH tunnels; falls back to console if needed.
            try:
                creds = flow.run_local_server(port=0)
            except Exception:
                creds = flow.run_console()
        SECRETS_DIR.mkdir(parents=True, exist_ok=True)
        TOKEN.write_text(creds.to_json(), encoding="utf-8")
        log.info("saved OAuth token -> %s", TOKEN)
    return build("youtube", "v3", credentials=creds)


def upload_video(video_path: Path, meta: dict, privacy: str = "private",
                 made_for_kids: bool = False) -> dict:
    """Resumable upload of one video. `meta` is the pipeline's metadata.json dict
    (title / description / hashtags / category). Returns {id, url, privacy}.

    privacy: 'private' (default, safest) | 'unlisted' | 'public'.
    """
    _require_libs()
    from googleapiclient.http import MediaFileUpload

    video_path = Path(video_path)
    if not video_path.exists():
        raise FileNotFoundError(video_path)
    if privacy not in ("private", "unlisted", "public"):
        raise ValueError(f"bad privacy: {privacy}")

    title = meta["title"][:100]  # YouTube hard limit
    tags = [t.lstrip("#") for t in meta.get("hashtags", [])]
    hashtag_line = " ".join(meta.get("hashtags", []))
    description = (meta.get("description", "").strip() + "\n\n" + hashtag_line).strip()[:5000]
    category_id = CATEGORY_IDS.get(meta.get("category", "Education"), "27")

    body = {
        "snippet": {
            "title": title,
            "description": description,
            "tags": tags,
            "categoryId": category_id,
        },
        "status": {
            "privacyStatus": privacy,
            "selfDeclaredMadeForKids": made_for_kids,
        },
    }

    youtube = get_service()
    media = MediaFileUpload(str(video_path), chunksize=-1, resumable=True, mimetype="video/*")
    req = youtube.videos().insert(part="snippet,status", body=body, media_body=media)

    log.info("uploading %s (%.1f MB) as '%s' [%s]...",
             video_path.name, video_path.stat().st_size / 1e6, title, privacy)
    resp = None
    while resp is None:
        status, resp = req.next_chunk()
        if status:
            log.info("  %d%%", int(status.progress() * 100))
    vid = resp["id"]
    url = f"https://youtu.be/{vid}"
    log.info("DONE -> %s (privacy=%s)", url, privacy)
    return {"id": vid, "url": url, "privacy": privacy}
