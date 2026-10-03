#!/usr/bin/env python3
"""Backfill surfer_urls for existing Top 10 clips by looking up each surfer's
latest non-short video on YouTube."""

import json
import os
import re
import sys
import yaml
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from sync_youtube import get_youtube_client, find_surfer_source_video, parse_duration

CONTENT_DIR = Path(__file__).parent.parent / "content" / "clips"


def main():
    print("Connecting to YouTube API...")
    youtube = get_youtube_client()

    # Find all Top 10 files with surfers but no surfer_urls
    top10_files = sorted(CONTENT_DIR.glob("*top-10*.md"), reverse=True)

    # Optionally limit to specific file
    if len(sys.argv) > 1:
        pattern = sys.argv[1]
        top10_files = [f for f in top10_files if pattern in f.name]

    for filepath in top10_files:
        content = filepath.read_text()
        parts = content.split("---", 2)
        if len(parts) < 3:
            continue

        fm = yaml.safe_load(parts[1])
        if not fm or not fm.get("surfers"):
            continue

        # Skip if already has surfer_urls
        if fm.get("surfer_urls"):
            print(f"SKIP (already has urls): {filepath.name}")
            continue

        print(f"\n=== {filepath.name} ===")
        surfers = fm["surfers"]
        surfer_urls = {}

        for name in surfers:
            url = find_surfer_source_video(youtube, name)
            if url:
                surfer_urls[name] = url
                print(f"  {name} -> {url}")
            else:
                print(f"  {name} -> NOT FOUND")

        if surfer_urls:
            # Add surfer_urls to front matter
            urls_yaml = "surfer_urls:\n"
            for name, url in surfer_urls.items():
                safe_key = f'"{name}"' if any(c in name for c in ":'-@") else name
                urls_yaml += f'  {safe_key}: "{url}"\n'

            # Insert before closing ---
            front_matter = parts[1].rstrip() + "\n" + urls_yaml
            new_content = f"---{front_matter}---{parts[2]}"
            filepath.write_text(new_content)
            print(f"  -> Updated {filepath.name} with {len(surfer_urls)}/{len(surfers)} links")
        else:
            print(f"  -> No links found")


if __name__ == "__main__":
    main()
