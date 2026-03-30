"""
download_overleaf.py — Headless CV download from Overleaf using session cookie.

Used by GitHub Actions. Requires OVERLEAF_SESSION env var (the value of the
`overleaf_session2` cookie from your logged-in Overleaf browser session).

Usage:
    OVERLEAF_SESSION=<cookie> python download_overleaf.py
"""

import os, sys, time, requests
from pathlib import Path

EN_ID  = "677868437340b90bf9d7020a"
ES_ID  = "67786d3df2f3eb3499624999"
ASSETS = Path(__file__).parent / "assets"
BASE   = "https://www.overleaf.com"


def compile_project(project_id: str, cookies: dict, headers: dict) -> bool:
    url = f"{BASE}/project/{project_id}/compile"
    try:
        r = requests.post(
            url, cookies=cookies, headers=headers,
            json={"check": "silent", "draft": False, "incremental": True,
                  "stopOnFirstError": False},
            timeout=60,
        )
        data = r.json()
        status = data.get("status", "")
        print(f"    compile status: {status}")
        return status in ("success", "clsi-maintenance")
    except Exception as e:
        print(f"    compile request failed: {e}")
        return False


def download_pdf(project_id: str, out_path: Path, label: str, session_cookie: str) -> bool:
    cookies = {"overleaf_session2": session_cookie}
    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
        "Referer": f"{BASE}/project/{project_id}",
        "Accept": "application/pdf,*/*",
    }

    url = f"{BASE}/project/{project_id}/output/output.pdf"

    # Try direct download first (works if project was recently compiled)
    r = requests.get(url, cookies=cookies, headers=headers,
                     allow_redirects=True, timeout=30)

    if r.status_code == 200 and "pdf" in r.headers.get("content-type", ""):
        out_path.write_bytes(r.content)
        print(f"  {label}: {len(r.content) // 1024} KB")
        return True

    print(f"  {label}: direct download returned {r.status_code}, triggering compile...")

    if compile_project(project_id, cookies, headers):
        time.sleep(5)  # wait for compile
        r2 = requests.get(url, cookies=cookies, headers=headers,
                          allow_redirects=True, timeout=30)
        if r2.status_code == 200 and "pdf" in r2.headers.get("content-type", ""):
            out_path.write_bytes(r2.content)
            print(f"  {label}: {len(r2.content) // 1024} KB")
            return True

    print(f"  {label}: download failed.")
    return False


if __name__ == "__main__":
    session = os.environ.get("OVERLEAF_SESSION")
    if not session:
        sys.exit("ERROR: OVERLEAF_SESSION env var not set.")

    ASSETS.mkdir(exist_ok=True)
    ok1 = download_pdf(EN_ID, ASSETS / "CV Jose Gelves (EN).pdf", "EN CV", session)
    ok2 = download_pdf(ES_ID, ASSETS / "CV Jose Gelves (ES).pdf", "ES CV", session)

    if not (ok1 and ok2):
        sys.exit(1)

    print("Both CVs downloaded successfully.")
