"""
update_cv.py - Download latest CV PDFs from Overleaf into assets/

Uses Playwright with a visible browser window (no login needed —
it reuses your saved session). Re-run --login if the session expires.

Usage:
    py update_cv.py           # download both CVs
    py update_cv.py --login   # re-authenticate (opens browser for Google login)

Requirements (run once):
    py -m pip install playwright
    py -m playwright install chromium
"""

import sys, time, shutil
from pathlib import Path

EN_PROJECT_ID = "677868437340b90bf9d7020a"
ES_PROJECT_ID = "67786d3df2f3eb3499624999"

ASSETS_DIR  = Path(__file__).parent / "assets"
SESSION_DIR = Path(__file__).parent / ".overleaf-session"
EN_OUT      = ASSETS_DIR / "CV Jose Gelves (EN).pdf"
ES_OUT      = ASSETS_DIR / "CV Jose Gelves (ES).pdf"

def ensure_playwright():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        import subprocess
        subprocess.check_call([sys.executable, "-m", "pip", "install", "playwright", "-q"])
        subprocess.check_call([sys.executable, "-m", "playwright", "install", "chromium"])
        from playwright.sync_api import sync_playwright
    return sync_playwright

def download_project(ctx, project_id: str, out_path: Path, label: str):
    page = ctx.new_page()
    print(f"  Loading {label} project...")
    page.goto(f"https://www.overleaf.com/project/{project_id}", wait_until="networkidle", timeout=30000)

    if "login" in page.url:
        page.close()
        print("Session expired. Run 'py update_cv.py --login' to log in again.")
        sys.exit(1)

    # wait for the Download PDF link to appear
    link = page.locator('a[download][href*="output.pdf"], a[aria-label="Download PDF"][href*="output.pdf"]')
    try:
        link.wait_for(timeout=15000)
    except Exception:
        # fallback: any link with output.pdf
        link = page.locator('a[href*="output.pdf"]').first

    href = link.get_attribute("href")
    if not href:
        print(f"  Could not find PDF link for {label}. Is the project compiled?")
        page.close()
        return

    if href.startswith("/"):
        href = "https://www.overleaf.com" + href

    print(f"  Downloading {label} PDF...")
    with page.expect_download(timeout=30000) as dl:
        page.goto(href)
    download = dl.value

    out_path.parent.mkdir(parents=True, exist_ok=True)
    download.save_as(str(out_path))
    print(f"  Saved: {out_path.name} ({out_path.stat().st_size // 1024} KB)")
    page.close()

def do_login(sync_playwright):
    print("Opening browser — log in with Google, then close the window.\n")
    SESSION_DIR.mkdir(exist_ok=True)
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=str(SESSION_DIR),
            headless=False,
            args=["--window-size=1280,800"],
        )
        page = ctx.new_page()
        page.goto("https://www.overleaf.com/login")
        try:
            page.wait_for_url("**/project**", timeout=120000)
            print("Logged in. Session saved.")
        except Exception:
            print("Timed out. Re-run --login to try again.")
        ctx.close()

def do_download(sync_playwright):
    if not SESSION_DIR.exists():
        print("No session found. Run 'py update_cv.py --login' first.")
        sys.exit(1)
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=str(SESSION_DIR),
            headless=False,   # visible avoids Google's headless detection
            args=["--window-size=1280,800"],
        )
        download_project(ctx, EN_PROJECT_ID, EN_OUT, "EN")
        download_project(ctx, ES_PROJECT_ID, ES_OUT, "ES")
        ctx.close()
    print("\nDone. Both CVs updated in assets/")

if __name__ == "__main__":
    sp = ensure_playwright()
    if "--login" in sys.argv:
        do_login(sp)
    else:
        do_download(sp)
