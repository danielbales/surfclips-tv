#!/usr/bin/env python3
"""
Backfill view counts for Top 10 clip pages.

Reads video IDs from content/clips/, fetches current view counts
from the YouTube API, and updates the front matter.
"""

import re
from pathlib import Path
from sync_youtube import get_youtube_client, fetch_video_details

CONTENT_DIR = Path(__file__).parent.parent / "content" / "clips"


def main():
    # Find all Top 10 clips and their video IDs
    top10s = []
    for f in sorted(CONTENT_DIR.glob("*.md")):
        text = f.read_text()
        if 'clip_type: "top10"' not in text:
            continue
        vid_m = re.search(r'^video_id:\s*"(.+?)"', text, re.MULTILINE)
        if vid_m:
            top10s.append((f, vid_m.group(1)))

    print(f"Found {len(top10s)} Top 10 clips")

    # Fetch view counts from YouTube API
    print("Connecting to YouTube API...")
    youtube = get_youtube_client()

    video_ids = [vid for _, vid in top10s]
    print("Fetching video details...")
    videos = fetch_video_details(youtube, video_ids)

    # Build lookup
    views_by_id = {}
    for v in videos:
        views_by_id[v["id"]] = int(v.get("statistics", {}).get("viewCount", 0))

    # Update front matter
    updated = 0
    for filepath, vid in top10s:
        if vid not in views_by_id:
            continue
        views = views_by_id[vid]
        text = filepath.read_text()

        if re.search(r"^views:", text, re.MULTILINE):
            # Update existing views field
            new_text = re.sub(
                r"^views:\s*\d+",
                f"views: {views}",
                text,
                count=1,
                flags=re.MULTILINE,
            )
        else:
            # Add views after duration line (always present)
            new_text = re.sub(
                r"^(duration:\s*\d+)",
                rf"\1\nviews: {views}",
                text,
                count=1,
                flags=re.MULTILINE,
            )

        if new_text != text:
            filepath.write_text(new_text)
            updated += 1

    print(f"Updated {updated} of {len(top10s)} Top 10 clips with view counts")


if __name__ == "__main__":
    main()
