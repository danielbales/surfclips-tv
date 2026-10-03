#!/usr/bin/env python3
"""
YouTube mirror for surfclips.tv

Pulls all uploads from Surf Clips TV and generates a Hugo page per video:
title, embed, thumbnail, and description. Skips videos that already have pages.

Uses the YouTube Data API with existing WorldwideWaves OAuth credentials.

Usage:
    python3 sync_youtube.py           # Sync latest uploads
    python3 sync_youtube.py --all     # Sync all uploads (first run)
"""

import html
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

# --- Config ---

CREDS_DIR = Path.home() / ".google_credentials"
TOKEN_FILE = CREDS_DIR / "token_WorldwideWaves_yt.json"
SCOPES = ["https://www.googleapis.com/auth/youtube.readonly"]

CONTENT_DIR = Path(__file__).parent.parent / "content" / "clips"
CHANNEL_ID = "UCqDiN-l8JOa6xZA0NCTjffw"

# Videos that were deleted/privated and should not be re-synced
EXCLUDED_VIDEO_IDS = {"oPrfq7FUxzM", "4yFum6Q0sBo"}


# --- Auth ---

def get_youtube_client():
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build

    # Support credentials from env var (for GitHub Actions) or local file
    token_json = os.environ.get("YOUTUBE_TOKEN_JSON")
    if token_json:
        creds = Credentials.from_authorized_user_info(json.loads(token_json), SCOPES)
    else:
        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)

    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        # Update local file if using file-based auth
        if not token_json and TOKEN_FILE.exists():
            TOKEN_FILE.write_text(creds.to_json())

    return build("youtube", "v3", credentials=creds)


def get_uploads_playlist_id(youtube):
    resp = youtube.channels().list(
        part="contentDetails", id=CHANNEL_ID
    ).execute()
    return resp["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]


# --- Fetch Videos ---

def fetch_uploads(youtube, playlist_id, max_results=None):
    """Fetch videos from the uploads playlist. Returns list of video IDs."""
    video_ids = []
    next_page = None

    while True:
        resp = youtube.playlistItems().list(
            part="contentDetails",
            playlistId=playlist_id,
            maxResults=50,
            pageToken=next_page,
        ).execute()

        for item in resp.get("items", []):
            video_ids.append(item["contentDetails"]["videoId"])

        if max_results and len(video_ids) >= max_results:
            video_ids = video_ids[:max_results]
            break

        next_page = resp.get("nextPageToken")
        if not next_page:
            break

    return video_ids


def fetch_video_details(youtube, video_ids):
    """Fetch full details for a batch of video IDs."""
    videos = []
    # API allows max 50 IDs per request
    for i in range(0, len(video_ids), 50):
        batch = video_ids[i:i + 50]
        resp = youtube.videos().list(
            part="snippet,contentDetails,statistics,status",
            id=",".join(batch),
        ).execute()
        videos.extend(resp.get("items", []))
    return videos


# --- Generate Hugo Pages ---

def slugify(text):
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_]+", "-", text)
    text = re.sub(r"-+", "-", text)
    return text[:80].strip("-")


def escape_yaml(text):
    """Escape text for YAML double-quoted strings."""
    return text.replace("\\", "\\\\").replace('"', '\\"')


def existing_video_ids():
    """Scan content dir for already-generated pages, return set of video IDs."""
    ids = set()
    if not CONTENT_DIR.exists():
        return ids
    for f in CONTENT_DIR.glob("*.md"):
        text = f.read_text()
        match = re.search(r'^video_id:\s*"?(\S+)"?', text, re.MULTILINE)
        if match:
            ids.add(match.group(1))
    return ids


def parse_duration(iso):
    """Parse ISO 8601 duration (PT1H2M3S) to seconds."""
    m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso)
    if not m:
        return 0
    h, mn, s = (int(x) if x else 0 for x in m.groups())
    return h * 3600 + mn * 60 + s


def classify_video(title, duration_secs):
    """Classify video as 'short', 'top10', or 'clip'."""
    if re.search(r"top\s*10", title, re.IGNORECASE):
        return "top10"
    if duration_secs <= 60:
        return "short"
    return "clip"


def clean_description(description, clip_type):
    """Strip YouTube boilerplate from description. For top10s, extract surfer names."""
    boilerplate_patterns = [
        r"^Wilbur\s*(Kookmeyer)?\s*[Mm]erch[:\!]?\s*$",
        r"^https?://surf-clips-tv-shop\.fourthwall\.com/?$",
        r"^And support the channel by subscribing!?\s*$",
        r"^[╔║╠╚╗╣╝═╦╩╬─│┌┐└┘├┤┬┴┼].*$",
        r"^SUBSCRIBE\s+FOR\s+VIDEOS.*$",
        r"^Thank you for supporting Surf Clips TV.*$",
        r"^Love the ocean\?.*surfrider\.org.*$",
        r"^Music:\s*.*$",
        r"^#\w+",
        r"^Subscribe.*$",
        r"^https?://www\.youtube\.com/@.*$",
        r"^https?://www\.instagram\.com/.*$",
        r"^https?://www\.tiktok\.com/.*$",
    ]
    compiled = [re.compile(p, re.IGNORECASE) for p in boilerplate_patterns]
    lines = description.split("\n")

    surfers = []
    location_line = ""

    if clip_type == "top10":
        # Extract surfer names from "From:" line
        for line in lines:
            m = re.match(r"^From:\s*(.+)$", line.strip(), re.IGNORECASE)
            if m:
                for name in m.group(1).split(","):
                    name = name.strip().lstrip("@").rstrip(".")
                    if name and name.lower() not in ("", "more"):
                        surfers.append(name)

        # Extract location summary line
        for line in lines:
            if re.match(r"^Surfing from .+", line.strip(), re.IGNORECASE):
                location_line = re.sub(
                    r"\s*in this week'?s Top 10\.?\s*$", ".", line.strip()
                )
                break

        clean = f"\n{location_line}\n" if location_line else ""
        return clean, surfers
    else:
        # Strip boilerplate, keep meaningful lines
        clean_lines = []
        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue
            if re.match(r"^From:\s", stripped):
                continue
            is_junk = False
            for pattern in compiled:
                if pattern.match(stripped):
                    is_junk = True
                    break
            if not is_junk:
                clean_lines.append(line)

        remaining = "\n".join(clean_lines).strip()
        clean = f"\n{remaining}\n" if remaining else ""
        return clean, []


def generate_page(video):
    """Generate a Hugo markdown page for a single YouTube video."""
    snippet = video["snippet"]
    video_id = video["id"]
    title = snippet["title"]
    description = snippet.get("description", "")
    published = snippet["publishedAt"]  # ISO 8601
    tags = snippet.get("tags", [])
    thumbnails = snippet.get("thumbnails", {})
    duration_secs = parse_duration(video["contentDetails"]["duration"])
    visibility = video.get("status", {}).get("privacyStatus", "public")
    view_count = int(video.get("statistics", {}).get("viewCount", 0))

    # Classify
    kind = classify_video(title, duration_secs)

    # Best thumbnail available (prefer maxres when API confirms it exists)
    thumb_url = ""
    for quality in ["maxres", "standard", "high", "medium", "default"]:
        if quality in thumbnails:
            thumb_url = thumbnails[quality]["url"]
            break

    # Parse date for slug
    pub_date = datetime.fromisoformat(published.replace("Z", "+00:00"))
    date_str = pub_date.strftime("%Y-%m-%d")
    slug = slugify(title)
    filename = CONTENT_DIR / f"{date_str}-{slug}.md"

    # Limit tags to 10 most relevant
    safe_tags = [t for t in tags[:10] if len(t) < 50]

    # Clean description
    clean_desc, surfers = clean_description(description, kind)

    # Generate meta description (first ~155 chars of meaningful text)
    meta_desc = re.sub(r"<[^>]+>", "", clean_desc).strip()
    meta_desc = re.sub(r"\s+", " ", meta_desc)
    if not meta_desc:
        meta_desc = f"Watch {title} on Surf Clips TV."
    if len(meta_desc) > 155:
        meta_desc = meta_desc[:152].rsplit(" ", 1)[0] + "..."

    # Build front matter + content
    surfer_yaml = ""
    if surfers:
        surfer_yaml = "surfers:\n" + "".join(f'  - "{s}"\n' for s in surfers)

    content = f"""---
title: "{escape_yaml(title)}"
date: {published}
draft: false
description: "{escape_yaml(meta_desc)}"
video_id: "{video_id}"
thumbnail: "{thumb_url}"
tags: {json.dumps(safe_tags)}
type: "clips"
clip_type: "{kind}"
duration: {duration_secs}
visibility: "{visibility}"
views: {view_count}
{surfer_yaml}---

<div class="video-embed">
<iframe src="https://www.youtube.com/embed/{video_id}" title="{html.escape(title, quote=True)}" allowfullscreen loading="lazy"></iframe>
</div>
{clean_desc}"""

    CONTENT_DIR.mkdir(parents=True, exist_ok=True)
    filename.write_text(content)
    return filename


# --- Main ---

def main():
    sync_all = "--all" in sys.argv

    print("Connecting to YouTube API...")
    youtube = get_youtube_client()

    print("Getting uploads playlist...")
    playlist_id = get_uploads_playlist_id(youtube)

    # Check what we already have
    existing = existing_video_ids()
    print(f"Existing pages: {len(existing)}")

    print("Fetching upload list...")
    max_results = None if sync_all else 25  # Recent 25 on incremental runs
    video_ids = fetch_uploads(youtube, playlist_id, max_results=max_results)
    print(f"Found {len(video_ids)} uploads")

    # Filter out already-generated
    new_ids = [vid for vid in video_ids if vid not in existing and vid not in EXCLUDED_VIDEO_IDS]
    if not new_ids:
        print("No new videos to sync.")
        return

    print(f"New videos to generate: {len(new_ids)}")

    # Fetch details and generate pages
    print("Fetching video details...")
    videos = fetch_video_details(youtube, new_ids)

    created = 0
    for video in videos:
        try:
            path = generate_page(video)
            print(f"  Created: {path.name}")
            created += 1
        except Exception as e:
            print(f"  Error on {video['id']}: {e}", file=sys.stderr)

    print(f"\nDone. Created {created} new pages.")


if __name__ == "__main__":
    main()
