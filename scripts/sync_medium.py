"""
sync_medium.py
--------------
Fetches posts from Xie Jiayu's Medium and Substack RSS feeds and:

  1. Renders a FULL standalone article page for each post into /posts/<slug>.html,
     using the site's own design (same nav, sidebar, fonts, colors).
  2. Updates writing.html with all posts (per source, between their own markers).
  3. Updates index.html with only the latest 3 Medium posts.

Run locally:  python scripts/sync_medium.py
Run via CI:   triggered automatically by .github/workflows/sync-medium.yml

Requires: feedparser, jinja2, requests  (pip install feedparser jinja2 requests)
"""

import os
import re
import html as html_lib
import textwrap
from datetime import datetime

import feedparser
import requests
from jinja2 import Environment, FileSystemLoader, select_autoescape

# ── Config ────────────────────────────────────────────────────────────────────
MEDIUM_RSS    = "https://medium.com/feed/@jiayuxie95"
SUBSTACK_RSS  = "https://xiedias.substack.com/feed"
INDEX_FILE    = "index.html"
WRITING_FILE  = "writing.html"
POSTS_DIR     = "posts"
TEMPLATE_DIR  = "scripts/templates"
TEMPLATE_FILE = "post_template.html"
MAX_POSTS     = 12       # how many posts to fetch per source
INDEX_PREVIEW = 3        # how many Medium posts to show on index.html
EXCERPT_LEN   = 160      # card excerpt length
WORDS_PER_MIN = 220      # used to estimate read time

MEDIUM_START    = "<!-- MEDIUM_POSTS_START -->"
MEDIUM_END      = "<!-- MEDIUM_POSTS_END -->"
SUBSTACK_START  = "<!-- SUBSTACK_POSTS_START -->"
SUBSTACK_END    = "<!-- SUBSTACK_POSTS_END -->"

# keep old names as aliases so _update_html_markers still works for index.html
START_MARKER = MEDIUM_START
END_MARKER   = MEDIUM_END


# ── Helpers ───────────────────────────────────────────────────────────────────

def slugify(title: str) -> str:
    slug = title.lower().strip()
    slug = re.sub(r"[^a-z0-9\s-]", "", slug)
    slug = re.sub(r"\s+", "-", slug)
    slug = re.sub(r"-{2,}", "-", slug)
    return slug[:80].strip("-") or "post"


def strip_html(raw: str) -> str:
    clean = re.sub(r"<[^>]+>", " ", raw)
    clean = html_lib.unescape(clean)
    clean = re.sub(r"\s+", " ", clean).strip()
    return clean


def get_full_content_html(entry) -> str:
    """Medium RSS includes the FULL article body in content:encoded."""
    if hasattr(entry, "content") and entry.content:
        return entry.content[0].get("value", "")
    return entry.get("summary", "")


def clean_medium_html(raw_html: str) -> str:
    """
    Light cleanup of Medium's article HTML so it inherits our site's
    typography instead of fighting it with inline styles.
    """
    cleaned = raw_html

    # Strip Medium's inline styles/classes/ids — let our CSS take over
    cleaned = re.sub(r'\sstyle="[^"]*"', "", cleaned)
    cleaned = re.sub(r'\sclass="[^"]*"', "", cleaned)
    cleaned = re.sub(r'\sid="[^"]*"', "", cleaned)

    # Remove Medium's trailing "Originally published" boilerplate paragraph if present
    cleaned = re.sub(
        r"<p[^>]*>\s*Originally published.*?</p>",
        "",
        cleaned,
        flags=re.IGNORECASE | re.DOTALL,
    )

    # Remove tracking pixels / 1x1 images Medium sometimes appends
    cleaned = re.sub(r'<img[^>]*width="1"[^>]*>', "", cleaned)

    # Strip fixed width/height attrs left on images so they scale responsively
    cleaned = re.sub(r'\swidth="\d+"', "", cleaned)
    cleaned = re.sub(r'\sheight="\d+"', "", cleaned)

    # Wrap bare <img> tags in <figure> for consistent spacing if not already wrapped
    def wrap_img(match):
        return f"<figure>{match.group(0)}</figure>"

    # Only wrap images that aren't already inside a figure tag (simple heuristic)
    parts = re.split(r"(<figure.*?</figure>)", cleaned, flags=re.DOTALL)
    rebuilt = []
    for part in parts:
        if part.startswith("<figure"):
            rebuilt.append(part)
        else:
            rebuilt.append(re.sub(r"<img[^>]*>", wrap_img, part))
    cleaned = "".join(rebuilt)

    return cleaned.strip()


def make_excerpt(entry) -> str:
    raw = entry.get("summary", "") or get_full_content_html(entry)
    text = strip_html(raw)
    if len(text) > EXCERPT_LEN:
        text = text[:EXCERPT_LEN].rsplit(" ", 1)[0] + "…"
    return text


def make_tags(entry) -> list:
    tags = getattr(entry, "tags", [])
    names = [t.get("term", "").strip() for t in tags if t.get("term")]
    return names[:5] if names else ["Writing"]


def estimate_read_time(plain_text: str) -> int:
    words = len(plain_text.split())
    return max(1, round(words / WORDS_PER_MIN))


def get_dates(entry):
    try:
        dt = datetime(*entry.published_parsed[:6])
    except Exception:
        dt = datetime.now()
    try:
        full_date = dt.strftime("%B %-d, %Y")
    except ValueError:
        full_date = dt.strftime("%B %d, %Y")
    return {
        "month_year": dt.strftime("%b %Y"),
        "full_date": full_date,
        "card_date": dt.strftime("%b %Y"),
    }


def build_card_html(title, slug, date_str, excerpt, tag) -> str:
    return textwrap.dedent(f"""\
          <a href="posts/{slug}.html" class="post-item">
            <span class="post-date">{date_str}</span>
            <div>
              <p class="post-title">{html_lib.escape(title)}</p>
              <p class="post-excerpt">{html_lib.escape(excerpt)}</p>
              <span class="post-tag">{html_lib.escape(tag.lower())}</span>
            </div>
          </a>""")


# ── Feed fetcher ──────────────────────────────────────────────────────────────

_HTTP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; RSS-bot/1.0; "
        "+https://github.com/xiejiayu95/xiejiayu95.github.io)"
    )
}


def fetch_feed(url: str):
    print(f"Fetching {url} …")
    response = requests.get(url, headers=_HTTP_HEADERS, timeout=30)
    if response.status_code != 200:
        print(f"⚠️  Skipping {url} — HTTP {response.status_code} (feed may block CI IPs)")
        return None
    feed = feedparser.parse(response.content)
    if feed.bozo:
        print(f"⚠️  Feed parse warning: {feed.bozo_exception}")
    return feed


def sync_feed(rss_url, source_label, template, env):
    """Fetch one RSS feed, render post pages, return list of card HTML strings."""
    feed = fetch_feed(rss_url)
    if feed is None:
        return []
    entries = feed.entries[:MAX_POSTS]
    if not entries:
        print(f"  No entries found for {source_label}.")
        return []

    print(f"  Found {len(entries)} post(s) from {source_label}.")
    cards = []

    for entry in entries:
        title = entry.get("title", "Untitled")
        slug = slugify(title)
        source_url = entry.get("link", "#")

        dates = get_dates(entry)
        tags = make_tags(entry)
        category = tags[0] if tags else "Writing"

        raw_body = get_full_content_html(entry)
        body_html = clean_medium_html(raw_body)
        plain_text = strip_html(raw_body)
        read_time = estimate_read_time(plain_text)
        excerpt = make_excerpt(entry)

        rendered = template.render(
            title=title,
            subtitle=None,
            category=category,
            month_year=dates["month_year"],
            full_date=dates["full_date"],
            read_time=read_time,
            tags=tags,
            body_html=body_html,
            medium_url=source_url,
        )

        out_path = os.path.join(POSTS_DIR, f"{slug}.html")
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(rendered)
        print(f"    wrote {out_path}")

        cards.append(build_card_html(title, slug, dates["card_date"], excerpt, category))

    return cards


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    os.makedirs(POSTS_DIR, exist_ok=True)

    env = Environment(
        loader=FileSystemLoader(TEMPLATE_DIR),
        autoescape=select_autoescape(disabled_extensions=("html",)),
    )
    template = env.get_template(TEMPLATE_FILE)

    # ── Medium ──
    medium_cards = sync_feed(MEDIUM_RSS, "Medium", template, env)

    if medium_cards:
        _update_html_markers(
            WRITING_FILE, medium_cards,
            start=MEDIUM_START, end=MEDIUM_END,
            label=f"all {len(medium_cards)} Medium post(s)"
        )
        _update_html_markers(
            INDEX_FILE, medium_cards[:INDEX_PREVIEW],
            start=MEDIUM_START, end=MEDIUM_END,
            label=f"latest {INDEX_PREVIEW} Medium post(s)"
        )

    # ── Substack ──
    substack_cards = sync_feed(SUBSTACK_RSS, "Substack", template, env)

    if substack_cards:
        _update_html_markers(
            WRITING_FILE, substack_cards,
            start=SUBSTACK_START, end=SUBSTACK_END,
            label=f"all {len(substack_cards)} Substack post(s)"
        )

    print("Sync complete.")


def _update_html_markers(filepath, cards, start=MEDIUM_START, end=MEDIUM_END, label=""):
    posts_html = "\n".join(cards)
    replacement = f"{start}\n{posts_html}\n        {end}"

    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    if start not in content or end not in content:
        print(
            f"Markers not found in {filepath}.\n"
            f"Add these two comments inside your .post-list div:\n"
            f"  {start}\n"
            f"  {end}"
        )
        return

    pattern = re.escape(start) + r".*?" + re.escape(end)
    new_content, count = re.subn(pattern, replacement, content, flags=re.DOTALL)

    if count == 0:
        print(f"Regex replacement failed — {filepath} left unchanged.")
        return

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(new_content)

    print(f"  updated {filepath} with {label}.")


if __name__ == "__main__":
    main()
