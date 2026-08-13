# xiejiayu95.github.io

Personal site and writing journal of **Xie Jiayu Dias** — Data Engineer, AI Researcher, and STEM educator.

🔗 [xiejiayu95.github.io](https://xiejiayu95.github.io)

---

## Structure

```
.
├── index.html              # Home page (writing preview, projects, research, about)
├── writing.html            # All writing — Technical Articles + Book Reviews
├── personal.html           # Personal posts (hiking, travel, etc.)
├── cv.html                 # CV viewer with PDF embed
├── CV___XieJiayuDias.pdf   # Downloadable CV
├── posts/                  # Full article pages (auto-generated + manual)
├── scripts/
│   ├── sync_medium.py      # Syncs Medium + Substack RSS → posts/ + writing.html
│   └── templates/
│       └── post_template.html
├── .github/workflows/
│   └── sync-medium.yml     # GitHub Actions: daily sync at 8am UTC
└── sync.bat                # Local sync script (run this to pull Substack posts)
```

## Writing sync

**Medium** articles are synced automatically via GitHub Actions (runs daily). Each post gets a full HTML page under `posts/` and a card in `writing.html` and `index.html`.

**Substack** posts ([xiedias.substack.com](https://xiedias.substack.com)) are blocked by Substack's CDN on datacenter IPs, so the CI sync skips them gracefully. To sync Substack locally, run:

```bat
sync.bat
```

This installs dependencies, runs the sync script, and commits + pushes any changes.

## Local development

No build step — plain HTML/CSS. Open any `.html` file directly in a browser.

To run the sync script manually:

```bash
pip install feedparser jinja2 requests
python scripts/sync_medium.py
```

## Deployment

Hosted on **GitHub Pages** from the `main` branch root. Changes pushed to `main` go live automatically.
