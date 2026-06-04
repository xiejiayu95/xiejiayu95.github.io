"""
sync_medium.py
--------------
Fetches the latest posts from Xie Jiayu's Medium RSS feed and
updates the Writing section of index.html with real titles,
excerpts and links.

Run locally:  python scripts/sync_medium.py
Run via CI:   triggered automatically by .github/workflows/sync-medium.yml
"""

import re
import textwrap
import html as html_lib
import feedparser
import requests
from datetime import datetime

# ── Config ────────────────────────────────────────────────────────────────────
MEDIUM_RSS   = "https://medium.com/feed/@jiayuxie95"
INDEX_FILE   = "index.html"
MAX_POSTS    = 6      # how many posts to show in the Writing section
EXCERPT_LEN  = 160    # max characters for the excerpt snippet

# Marker comments that wrap the auto-generated block inside index.html
START_MARKER = "<!-- MEDIUM_POSTS_START -->"
END_MARKER   = "<!-- MEDIUM_POSTS_END -->"

# ── Helpers ───────────────────────────────────────────────────────────────────

def strip_html(raw: str) -> str:
    """Remove HTML tags and decode entities."""
    clean = re.sub(r"<[^>]+>", " ", raw)
    clean = html_lib.unescape(clean)
    clean = re.sub(r"\s+", " ", clean).strip()
    return clean


def make_excerpt(entry) -> str:
    """Pull the best available plain-text excerpt from a feed entry."""
    # Try summary first, then content
    raw = ""
    if hasattr(entry, "summary"):
        raw = entry.summary
    elif hasattr(entry, "content") and entry.content:
        raw = entry.content[0].get("value", "")
    text = strip_html(raw)
    if len(text) > EXCERPT_LEN:
        text = text[:EXCERPT_LEN].rsplit(" ", 1)[0] + "…"
    return text


def make_tag(entry) -> str:
    """Use the first Medium tag as the post-tag pill, or fall back to 'writing'."""
    tags = getattr(entry, "tags", [])
    if tags:
        return tags[0].get("term", "writing").lower()
    return "writing"


def format_date(entry) -> str:
    """Return a human-readable month + year string."""
    try:
        dt = datetime(*entry.published_parsed[:3])
        return dt.strftime("%b %Y")
    except Exception:
        return ""


def build_post_html(entry) -> str:
    """Render one <a class='post-item'> block."""
    title   = html_lib.escape(entry.get("title", "Untitled"))
    url     = entry.get("link", "#")
    date    = format_date(entry)
    excerpt = html_lib.escape(make_excerpt(entry))
    tag     = html_lib.escape(make_tag(entry))

    return textwrap.dedent(f"""\
          <a href="{url}" target="_blank" rel="noopener" class="post-item">
            <span class="post-date">{date}</span>
            <div>
              <p class="post-title">{title}</p>
              <p class="post-excerpt">{excerpt}</p>
              <span class="post-tag">{tag}</span>
            </div>
          </a>""")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print(f"Fetching {MEDIUM_RSS} …")
    feed = feedparser.parse(MEDIUM_RSS)

    if feed.bozo:
        print(f"⚠️  Feed parse warning: {feed.bozo_exception}")

    entries = feed.entries[:MAX_POSTS]
    if not entries:
        print("No entries found — index.html left unchanged.")
        return

    print(f"Found {len(entries)} post(s).")

    # Build the replacement block
    posts_html = "\n".join(build_post_html(e) for e in entries)
    replacement = (
        f"{START_MARKER}\n"
        f"{posts_html}\n"
        f"          {END_MARKER}"
    )

    # Read current index.html
    with open(INDEX_FILE, "r", encoding="utf-8") as f:
        content = f.read()

    # Check markers exist
    if START_MARKER not in content or END_MARKER not in content:
        print(
            f"❌  Markers not found in {INDEX_FILE}.\n"
            f"    Add these two comments inside your .post-list div:\n"
            f"      {START_MARKER}\n"
            f"      {END_MARKER}"
        )
        return

    # Replace everything between (and including) the markers
    pattern = re.escape(START_MARKER) + r".*?" + re.escape(END_MARKER)
    new_content, count = re.subn(pattern, replacement, content, flags=re.DOTALL)

    if count == 0:
        print("❌  Regex replacement failed — index.html left unchanged.")
        return

    with open(INDEX_FILE, "w", encoding="utf-8") as f:
        f.write(new_content)

    print(f"✅  {INDEX_FILE} updated with {len(entries)} Medium post(s).")


if __name__ == "__main__":
    main()
