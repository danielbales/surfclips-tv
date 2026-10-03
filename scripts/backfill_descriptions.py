#!/usr/bin/env python3
"""
Backfill meta descriptions for existing clip pages.

Reads each .md file in content/clips/, and if it lacks a description field,
generates one from the page body or title and adds it to the front matter.
"""

import re
from pathlib import Path

CONTENT_DIR = Path(__file__).parent.parent / "content" / "clips"


def extract_description(body, title):
    """Extract a meta description from the page body or generate from title."""
    # Strip HTML tags and the video-embed div
    text = re.sub(r"<[^>]+>", "", body).strip()
    text = re.sub(r"\s+", " ", text)

    if text and len(text) > 20:
        if len(text) > 155:
            return text[:152].rsplit(" ", 1)[0] + "..."
        return text

    return f"Watch {title} on Surf Clips TV."


def escape_yaml(text):
    """Escape text for YAML double-quoted strings."""
    return text.replace("\\", "\\\\").replace('"', '\\"')


def process_file(filepath):
    """Add description field to a clip page if missing."""
    content = filepath.read_text()

    # Check if description already exists in front matter
    if re.search(r"^description:", content, re.MULTILINE):
        return False

    # Split front matter and body
    parts = content.split("---", 2)
    if len(parts) < 3:
        return False

    front_matter = parts[1]
    body = parts[2]

    # Get title from front matter
    title_match = re.search(r'^title:\s*"(.+)"', front_matter, re.MULTILINE)
    if not title_match:
        return False
    title = title_match.group(1).replace('\\"', '"').replace("\\\\", "\\")

    desc = extract_description(body, title)

    # Insert description after the date line
    new_fm = re.sub(
        r"(^date:.*$)",
        rf'\1\ndescription: "{escape_yaml(desc)}"',
        front_matter,
        count=1,
        flags=re.MULTILINE,
    )

    filepath.write_text(f"---{new_fm}---{body}")
    return True


def main():
    if not CONTENT_DIR.exists():
        print("Content directory not found.")
        return

    files = sorted(CONTENT_DIR.glob("*.md"))
    updated = 0

    for f in files:
        if process_file(f):
            updated += 1

    print(f"Updated {updated} of {len(files)} files.")


if __name__ == "__main__":
    main()
