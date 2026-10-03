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

import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from textwrap import dedent

# --- Config ---

CREDS_DIR = Path.home() / ".google_credentials"
TOKEN_FILE = CREDS_DIR / "token_WorldwideWaves_yt.json"
CREDS_FILE = CREDS_DIR / "credentials.json"
SCOPES = ["https://www.googleapis.com/auth/youtube.readonly"]

CONTENT_DIR = Path(__file__).parent.parent / "content" / "clips"
CHANNEL_ID = "UCqDiN-l8JOa6xZA0NCTjffw"


# --- Auth ---

def get_youtube_client():
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build

    creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
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
            part="snippet,contentDetails,statistics",
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


def generate_page(video):
    """Generate a Hugo markdown page for a single YouTube video."""
    snippet = video["snippet"]
    video_id = video["id"]
    title = snippet["title"]
    description = snippet.get("description", "")
    published = snippet["publishedAt"]  # ISO 8601
    tags = snippet.get("tags", [])
    thumbnails = snippet.get("thumbnails", {})

    # Best thumbnail available
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

    # Build front matter + content
    content = f"""---
title: "{escape_yaml(title)}"
date: {published}
draft: false
video_id: "{video_id}"
thumbnail: "{thumb_url}"
tags: {json.dumps(safe_tags)}
type: "clips"
---

<div class="video-embed">
<iframe src="https://www.youtube.com/embed/{video_id}" title="{escape_yaml(title)}" allowfullscreen loading="lazy"></iframe>
</div>

{description}
"""

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
    new_ids = [vid for vid in video_ids if vid not in existing]
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
