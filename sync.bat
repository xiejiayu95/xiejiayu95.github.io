@echo off
:: ─────────────────────────────────────────────────────────────
::  sync.bat — run this locally to sync Medium + Substack posts
::  Usage: double-click sync.bat  OR  run it from a terminal
:: ─────────────────────────────────────────────────────────────

:: Move to the repo root (same folder this script lives in)
cd /d "%~dp0"

echo.
echo [1/3] Installing Python dependencies...
pip install requests feedparser jinja2 --quiet
if errorlevel 1 (
    echo ERROR: pip install failed. Is Python installed and on PATH?
    pause
    exit /b 1
)

echo.
echo [2/3] Running sync script...
python scripts/sync_medium.py
if errorlevel 1 (
    echo ERROR: sync script failed. Check output above.
    pause
    exit /b 1
)

echo.
echo [3/3] Committing and pushing changes...
git add index.html writing.html posts/
git diff --cached --quiet
if errorlevel 1 (
    git commit -m "chore: sync posts (Medium + Substack)"
    git pull --rebase origin main
    git push
    echo.
    echo Done! Posts synced and pushed to GitHub.
) else (
    echo No changes detected — everything is already up to date.
)

echo.
pause
