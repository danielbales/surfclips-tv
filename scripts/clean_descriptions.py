#!/usr/bin/env python3
"""One-time cleanup of clip descriptions.

- Strips YouTube boilerplate (merch links, ASCII subscribe art, support text)
- For Top 10s: extracts surfer names from "From:" line into front matter
- For Top 10s: keeps only the location/summary line
- For shorts/clips: strips boilerplate, keeps meaningful description lines
"""

import re
import os
import glob

CONTENT_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "content", "clips")

# Lines/patterns to strip from all descriptions
BOILERPLATE_PATTERNS = [
    r"^Wilbur\s*(Kookmeyer)?\s*[Mm]erch[:\!]?\s*$",
    r"^https?://surf-clips-tv-shop\.fourthwall\.com/?$",
    r"^And support the channel by subscribing!?\s*$",
    r"^[╔║╠╚╗╣╝═╦╩╬─│┌┐└┘├┤┬┴┼].*$",
    r"^SUBSCRIBE\s+FOR\s+VIDEOS.*$",
    r"^Thank you for supporting Surf Clips TV.*$",
    r"^Love the ocean\?.*surfrider\.org.*$",
    r"^Music:\s*.*$",
    r"^#\w+",  # hashtags
    r"^Subscribe.*$",
    r"^https?://www\.youtube\.com/@.*$",
    r"^https?://www\.instagram\.com/.*$",
    r"^https?://www\.tiktok\.com/.*$",
]

BOILERPLATE_RE = [re.compile(p, re.IGNORECASE) for p in BOILERPLATE_PATTERNS]


def is_boilerplate(line):
    stripped = line.strip()
    if not stripped:
        return False  # blank lines handled separately
    for pattern in BOILERPLATE_RE:
        if pattern.match(stripped):
            return True
    return False


def extract_surfers(lines):
    """Extract surfer names from 'From:' line in Top 10 descriptions."""
    for line in lines:
        m = re.match(r"^From:\s*(.+)$", line.strip(), re.IGNORECASE)
        if m:
            raw = m.group(1)
            # Split on commas, clean up @mentions and extra whitespace
            names = []
            for name in raw.split(","):
                name = name.strip().lstrip("@").rstrip(".")
                if name and name.lower() not in ("", "more"):
                    names.append(name)
            return names
    return []


def extract_location_line(lines):
    """Extract the 'Surfing from X, Y, Z...' summary line."""
    for line in lines:
        if re.match(r"^Surfing from .+", line.strip(), re.IGNORECASE):
            return line.strip()
    return ""


def clean_file(filepath):
    with open(filepath, "r") as f:
        content = f.read()

    # Split front matter and body
    parts = content.split("---", 2)
    if len(parts) < 3:
        return False

    front_matter = parts[1]
    body = parts[2]

    # Check if it's a top10
    is_top10 = "clip_type: \"top10\"" in front_matter

    # Split body into embed and description
    embed_match = re.search(r'(<div class="video-embed">.*?</div>)', body, re.DOTALL)
    if not embed_match:
        return False

    embed_html = embed_match.group(1)
    description_text = body[embed_match.end():]
    desc_lines = description_text.split("\n")

    if is_top10:
        surfers = extract_surfers(desc_lines)
        location = extract_location_line(desc_lines)

        # Add/update surfers in front matter
        if surfers:
            # Remove existing surfers block if present
            front_matter = re.sub(r'surfers:\n(?:\s+-\s+"[^"]*"\n)*', '', front_matter)
            surfer_yaml = "surfers:\n" + "".join(f'  - "{s}"\n' for s in surfers)
            front_matter = front_matter.rstrip() + "\n" + surfer_yaml

        # Build clean body
        new_body = f"\n{embed_html}\n"
        if location:
            # Remove trailing "in this week's Top 10." for cleaner copy
            location = re.sub(r"\s*in this week'?s Top 10\.?\s*$", ".", location)
            new_body += f"\n{location}\n"

    else:
        # For shorts/clips: keep non-boilerplate lines
        clean_lines = []
        for line in desc_lines:
            if not is_boilerplate(line):
                clean_lines.append(line)

        # Strip "From:" line from non-top10s too
        clean_lines = [l for l in clean_lines if not re.match(r"^From:\s", l.strip())]

        # Remove trailing blank lines
        while clean_lines and not clean_lines[-1].strip():
            clean_lines.pop()

        # Remove leading blank lines
        while clean_lines and not clean_lines[0].strip():
            clean_lines.pop(0)

        new_body = f"\n{embed_html}\n"
        if clean_lines:
            remaining = "\n".join(clean_lines).strip()
            if remaining:
                new_body += f"\n{remaining}\n"

    new_content = f"---{front_matter}---{new_body}"

    if new_content != content:
        with open(filepath, "w") as f:
            f.write(new_content)
        return True
    return False


def main():
    files = glob.glob(os.path.join(CONTENT_DIR, "*.md"))
    changed = 0
    for filepath in sorted(files):
        if clean_file(filepath):
            changed += 1
            print(f"Cleaned: {os.path.basename(filepath)}")

    print(f"\nDone. {changed} files updated out of {len(files)} total.")


if __name__ == "__main__":
    main()
