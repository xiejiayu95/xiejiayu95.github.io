"""
sync_medium.py
--------------
Fetches posts from Xie Jiayu's Medium RSS feed and:

  1. Renders a FULL standalone article page for each post into /posts/<slug>.html,
     using the site's own design (same nav, sidebar, fonts, colors).
  2. Updates the Writing section of index.html with cards that link to those
     local pages (not to Medium) — with a "Originally published on Medium"
     link kept inside each post page for attribution.

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
INDEX_FILE    = "index.html"
WRITING_FILE  = "writing.html"
POSTS_DIR     = "posts"
TEMPLATE_DIR  = "scripts/templates"
TEMPLATE_FILE = "post_template.html"
MAX_POSTS     = 12       # how many posts to fetch from Medium
INDEX_PREVIEW = 3        # how many posts to show on index.html
EXCERPT_LEN   = 160      # homepage card excerpt length
WORDS_PER_MIN = 220      # used to estimate read time

START_MARKER = "<!-- MEDIUM_POSTS_START -->"
END_MARKER   = "<!-- MEDIUM_POSTS_END -->"


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


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    os.makedirs(POSTS_DIR, exist_ok=True)

    print(f"Fetching {MEDIUM_RSS} …")
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (compatible; RSS-bot/1.0; "
            "+https://github.com/xiejiayu95/xiejiayu95.github.io)"
        )
    }
    response = requests.get(MEDIUM_RSS, headers=headers, timeout=30)
    if response.status_code != 200:
        raise RuntimeError(
            f"Failed to fetch Medium RSS feed: HTTP {response.status_code}"
        )
    feed = feedparser.parse(response.content)

    if feed.bozo:
        print(f"⚠️  Feed parse warning: {feed.bozo_exception}")

    entries = feed.entries[:MAX_POSTS]
    if not entries:
        print("No entries found — nothing to do.")
        return

    print(f"Found {len(entries)} post(s) on Medium.")

    env = Environment(
        loader=FileSystemLoader(TEMPLATE_DIR),
        autoescape=select_autoescape(disabled_extensions=("html",)),
    )
    template = env.get_template(TEMPLATE_FILE)

    cards = []

    for entry in entries:
        title = entry.get("title", "Untitled")
        slug = slugify(title)
        medium_url = entry.get("link", "#")

        dates = get_dates(entry)
        tags = make_tags(entry)
        category = tags[0] if tags else "Writing"

        raw_body = get_full_content_html(entry)
        body_html = clean_medium_html(raw_body)
        plain_text = strip_html(raw_body)
        read_time = estimate_read_time(plain_text)
        excerpt = make_excerpt(entry)

        # ── Render the full standalone post page ──
        rendered = template.render(
            title=title,
            subtitle=None,
            category=category,
            month_year=dates["month_year"],
            full_date=dates["full_date"],
            read_time=read_time,
            tags=tags,
            body_html=body_html,
            medium_url=medium_url,
        )

        out_path = os.path.join(POSTS_DIR, f"{slug}.html")
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(rendered)
        print(f"  wrote {out_path}")

        # ── Build the homepage card (links to the LOCAL page) ──
        cards.append(build_card_html(title, slug, dates["card_date"], excerpt, category))

    # ── Update writing.html with ALL posts ──
    _update_html_markers(
        WRITING_FILE, cards,
        label=f"all {len(cards)} post(s)"
    )

    # ── Update index.html with latest 3 posts only ──
    _update_html_markers(
        INDEX_FILE, cards[:INDEX_PREVIEW],
        label=f"latest {INDEX_PREVIEW} post(s)"
    )

    print(f"{len(entries)} full post page(s) written to /{POSTS_DIR}/")


def _update_html_markers(filepath, cards, label=""):
    posts_html = "\n".join(cards)
    replacement = f"{START_MARKER}\n{posts_html}\n          {END_MARKER}"

    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    if START_MARKER not in content or END_MARKER not in content:
        print(
            f"Markers not found in {filepath}.\n"
            f"Add these two comments inside your .post-list div:\n"
            f"  {START_MARKER}\n"
            f"  {END_MARKER}"
        )
        return

    pattern = re.escape(START_MARKER) + r".*?" + re.escape(END_MARKER)
    new_content, count = re.subn(pattern, replacement, content, flags=re.DOTALL)

    if count == 0:
        print(f"Regex replacement failed — {filepath} left unchanged.")
        return

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(new_content)

    print(f"  updated {filepath} with {label}.")


if __name__ == "__main__":
    main()
