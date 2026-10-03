#!/usr/bin/env python3
"""Add video titles to existing surfer_urls by fetching from YouTube API.
Uses the cheap videos.list endpoint (1 quota unit each), not search."""

import os
import re
import sys
import yaml
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from sync_youtube import get_youtube_client

CONTENT_DIR = Path(__file__).parent.parent / "content" / "clips"


def extract_video_id(url):
    m = re.search(r"[?&]v=([a-zA-Z0-9_-]{11})", url)
    return m.group(1) if m else None


def main():
    print("Connecting to YouTube API...")
    youtube = get_youtube_client()

    top10_files = sorted(CONTENT_DIR.glob("*top-10*.md"), reverse=True)

    for filepath in top10_files:
        content = filepath.read_text()
        parts = content.split("---", 2)
        if len(parts) < 3:
            continue

        fm = yaml.safe_load(parts[1])
        if not fm or not fm.get("surfer_urls"):
            continue

        # Skip if already has titles
        if fm.get("surfer_video_titles"):
            print(f"SKIP: {filepath.name}")
            continue

        surfer_urls = fm["surfer_urls"]
        # Collect all video IDs
        vid_ids = {}
        for name, url in surfer_urls.items():
            vid_id = extract_video_id(url)
            if vid_id:
                vid_ids[name] = vid_id

        if not vid_ids:
            continue

        # Batch fetch video titles (up to 50 per call)
        all_ids = list(vid_ids.values())
        try:
            resp = youtube.videos().list(
                id=",".join(all_ids), part="snippet"
            ).execute()
        except Exception as e:
            print(f"ERROR: {filepath.name}: {e}")
            continue

        # Map video ID -> title
        id_to_title = {}
        for item in resp.get("items", []):
            id_to_title[item["id"]] = item["snippet"]["title"]

        # Build titles map
        titles = {}
        for name, vid_id in vid_ids.items():
            title = id_to_title.get(vid_id)
            if title:
                titles[name] = title

        if not titles:
            continue

        # Add surfer_video_titles to front matter
        titles_yaml = "surfer_video_titles:\n"
        for name, title in titles.items():
            safe_key = f'"{name}"' if any(c in name for c in ":'-@") else name
            safe_title = title.replace('"', '\\"')
            titles_yaml += f'  {safe_key}: "{safe_title}"\n'

        front_matter = parts[1].rstrip() + "\n" + titles_yaml
        new_content = f"---{front_matter}---{parts[2]}"
        filepath.write_text(new_content)
        print(f"Updated: {filepath.name} ({len(titles)} titles)")

    print("Done.")


if __name__ == "__main__":
    main()
