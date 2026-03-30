"""
download_overleaf.py — Headless CV download from Overleaf using session cookie.

Used by GitHub Actions. Requires OVERLEAF_SESSION env var (the value of the
`overleaf_session2` cookie from your logged-in Overleaf browser session).

The cookie value may be URL-encoded (s%3A...) — the script handles both forms.

Usage:
    OVERLEAF_SESSION=<cookie> python download_overleaf.py
    OVERLEAF_SESSION=<cookie> python download_overleaf.py --test
"""

import os
import sys
import time
import json
import urllib.parse
import requests
from pathlib import Path
from bs4 import BeautifulSoup

EN_ID  = "677868437340b90bf9d7020a"
ES_ID  = "67786d3df2f3eb3499624999"
ASSETS = Path(__file__).parent / "assets"
BASE   = "https://www.overleaf.com"


def normalize_cookie(raw: str) -> str:
    """URL-decode the cookie value if it looks encoded (e.g. starts with s%3A)."""
    decoded = urllib.parse.unquote(raw)
    return decoded


def make_session(session_cookie: str) -> requests.Session:
    """Build a requests.Session with the Overleaf session cookie set correctly."""
    s = requests.Session()
    # Overleaf expects the cookie on domain .overleaf.com (dot-prefixed)
    cookie = requests.cookies.create_cookie(
        name="overleaf_session2",
        value=session_cookie,
        domain=".overleaf.com",
        path="/",
        secure=True,
    )
    s.cookies.set_cookie(cookie)
    s.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9",
    })
    return s


def get_csrf_token(session: requests.Session, project_id: str) -> str:
    """
    Fetch the project page and extract the CSRF token from the
    <meta name="ol-csrfToken"> tag.
    """
    url = f"{BASE}/project/{project_id}"
    r = session.get(url, timeout=30)
    if r.status_code != 200:
        raise RuntimeError(
            f"Could not load project page (status {r.status_code}). "
            "Session cookie may be expired or invalid."
        )
    soup = BeautifulSoup(r.content, "html.parser")
    meta = soup.find("meta", {"name": "ol-csrfToken"})
    if meta is None:
        # Dump first 500 chars to help diagnose redirect-to-login
        snippet = r.text[:500].replace("\n", " ")
        raise RuntimeError(
            f"CSRF token meta tag not found. Page snippet: {snippet!r}"
        )
    return meta.get("content", "")


def compile_project(
    session: requests.Session,
    project_id: str,
    csrf_token: str,
) -> dict | None:
    """
    POST to the compile endpoint and return the parsed JSON response,
    or None on failure.
    """
    url = f"{BASE}/project/{project_id}/compile"
    payload = {
        "check": "silent",
        "draft": False,
        "incremental": True,
        "stopOnFirstError": False,
    }
    headers = {
        "Referer": f"{BASE}/project/{project_id}",
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Cache-Control": "no-cache",
        "x-csrf-token": csrf_token,
    }
    try:
        r = session.post(
            url,
            json=payload,
            headers=headers,
            timeout=120,
        )
    except requests.RequestException as e:
        print(f"    compile HTTP error: {e}")
        return None

    if r.status_code != 200:
        print(f"    compile returned HTTP {r.status_code}")
        print(f"    response body (first 300 chars): {r.text[:300]!r}")
        return None

    content_type = r.headers.get("content-type", "")
    if "json" not in content_type:
        print(
            f"    compile response is not JSON (content-type: {content_type!r}). "
            "Session cookie may be expired."
        )
        print(f"    response body (first 300 chars): {r.text[:300]!r}")
        return None

    try:
        return r.json()
    except json.JSONDecodeError as e:
        print(f"    compile JSON parse failed: {e}")
        print(f"    raw body (first 300 chars): {r.text[:300]!r}")
        return None


def pdf_url_from_compile_response(data: dict, project_id: str) -> str | None:
    """
    Extract the PDF download URL from the compile API response.
    The response has the shape:
        {"status": "success", "outputFiles": [{"type": "pdf", "url": "..."}, ...]}
    The embedded URL is a CLSI-internal URL; we replace its host with the
    Overleaf web app proxy path instead.
    """
    output_files = data.get("outputFiles", [])
    for f in output_files:
        if f.get("type") == "pdf":
            clsi_url = f.get("url", "")
            # clsi_url looks like:
            #   /project/{id}/output/output.pdf?build=...&...
            # or an absolute http://clsi-... URL.
            # In both cases, grab the path+query and prepend BASE.
            parsed = urllib.parse.urlparse(clsi_url)
            if parsed.scheme:
                # Absolute URL from internal CLSI — rewrite to Overleaf proxy
                path_qs = parsed.path
                if parsed.query:
                    path_qs += "?" + parsed.query
                return BASE + path_qs
            else:
                # Already a relative path
                return BASE + clsi_url
    return None


def download_pdf(
    project_id: str,
    out_path: Path,
    label: str,
    session_cookie: str,
) -> bool:
    session = make_session(session_cookie)

    # --- Step 1: get CSRF token ---
    print(f"  {label}: fetching project page for CSRF token...")
    try:
        csrf_token = get_csrf_token(session, project_id)
    except RuntimeError as e:
        print(f"  {label}: {e}")
        return False
    print(f"  {label}: got CSRF token ({csrf_token[:8]}...)")

    # --- Step 2: try direct PDF download (works if recently compiled) ---
    direct_url = f"{BASE}/project/{project_id}/output/output.pdf"
    r = session.get(
        direct_url,
        headers={"Referer": f"{BASE}/project/{project_id}", "Accept": "application/pdf,*/*"},
        allow_redirects=True,
        timeout=30,
    )
    if r.status_code == 200 and "pdf" in r.headers.get("content-type", ""):
        out_path.write_bytes(r.content)
        print(f"  {label}: {len(r.content) // 1024} KB (from cache)")
        return True

    print(f"  {label}: direct download returned {r.status_code}, triggering compile...")

    # --- Step 3: compile ---
    data = compile_project(session, project_id, csrf_token)
    if data is None:
        print(f"  {label}: compile failed.")
        return False

    status = data.get("status", "unknown")
    print(f"  {label}: compile status = {status!r}")

    if status not in ("success", "clsi-maintenance"):
        print(f"  {label}: compile did not succeed (status={status!r}).")
        # Log any compiler errors present
        for entry in data.get("outputFiles", []):
            if entry.get("type") == "log":
                print(f"  {label}: log available at {entry.get('url')}")
        return False

    # --- Step 4: download compiled PDF ---
    # Try URL from compile response first (has build ID, most reliable)
    pdf_url = pdf_url_from_compile_response(data, project_id)
    if pdf_url:
        print(f"  {label}: downloading from compile output URL...")
        r2 = session.get(
            pdf_url,
            headers={"Referer": f"{BASE}/project/{project_id}", "Accept": "application/pdf,*/*"},
            allow_redirects=True,
            timeout=60,
        )
        if r2.status_code == 200 and "pdf" in r2.headers.get("content-type", ""):
            out_path.write_bytes(r2.content)
            print(f"  {label}: {len(r2.content) // 1024} KB")
            return True
        print(
            f"  {label}: compile output URL returned {r2.status_code}, "
            "falling back to direct path..."
        )

    # Fallback: /project/{id}/output/output.pdf after short wait
    time.sleep(3)
    r3 = session.get(
        direct_url,
        headers={"Referer": f"{BASE}/project/{project_id}", "Accept": "application/pdf,*/*"},
        allow_redirects=True,
        timeout=60,
    )
    if r3.status_code == 200 and "pdf" in r3.headers.get("content-type", ""):
        out_path.write_bytes(r3.content)
        print(f"  {label}: {len(r3.content) // 1024} KB (fallback path)")
        return True

    print(f"  {label}: download failed (status {r3.status_code}).")
    return False


def test_session(session_cookie: str) -> bool:
    """
    Check whether the session cookie is valid by hitting the Overleaf
    projects page and looking for a sign-in indicator in the HTML.
    """
    session = make_session(session_cookie)
    print("Checking session validity...")
    try:
        r = session.get(f"{BASE}/project", timeout=20)
    except requests.RequestException as e:
        print(f"Request failed: {e}")
        return False

    if r.status_code != 200:
        print(f"Projects page returned HTTP {r.status_code} — not logged in.")
        return False

    soup = BeautifulSoup(r.content, "html.parser")

    # If logged in, the page has user meta tags; if not, it redirects or shows login
    user_meta = soup.find("meta", {"name": "ol-user"})
    email_meta = soup.find("meta", {"name": "ol-usersEmail"})

    if user_meta or email_meta:
        email = email_meta.get("content", "unknown") if email_meta else "unknown"
        print(f"Session is VALID — logged in as: {email}")
        return True

    # Check if we got redirected to login page
    if "login" in r.url or soup.find("form", {"action": "/login"}):
        print("Session is INVALID — redirected to login page.")
        return False

    # Heuristic: look for ol-prefetchedProjectsBlob which is present when logged in
    projects_meta = soup.find("meta", {"name": "ol-prefetchedProjectsBlob"})
    if projects_meta:
        print("Session is VALID — projects page loaded successfully.")
        return True

    print(
        f"Could not determine login state (final URL: {r.url}). "
        "Page snippet:"
    )
    print(r.text[:400])
    return False


if __name__ == "__main__":
    session = os.environ.get("OVERLEAF_SESSION")
    if not session:
        sys.exit("ERROR: OVERLEAF_SESSION env var not set.")

    # URL-decode the cookie if needed (GitHub Actions secrets may store it encoded)
    session = normalize_cookie(session)

    if "--test" in sys.argv:
        ok = test_session(session)
        sys.exit(0 if ok else 1)

    ASSETS.mkdir(exist_ok=True)
    ok1 = download_pdf(EN_ID, ASSETS / "CV Jose Gelves (EN).pdf", "EN CV", session)
    ok2 = download_pdf(ES_ID, ASSETS / "CV Jose Gelves (ES).pdf", "ES CV", session)

    if not (ok1 and ok2):
        sys.exit(1)

    print("Both CVs downloaded successfully.")
