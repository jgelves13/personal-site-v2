"""
update_site.py — Sync CV content from Overleaf into index.html

Steps:
  1. Downloads latest EN + ES CVs from Overleaf  (calls update_cv.py logic)
  2. Parses both PDFs with pdfplumber
  3. Sends text to Claude API to extract structured data as JSON
  4. Updates index.html: about paragraphs, experience items, education items

Usage:
    py update_site.py            # full update (download + parse + update HTML)
    py update_site.py --no-dl    # skip Overleaf download, use existing PDFs

Requirements (auto-installed if missing):
    pip install pdfplumber anthropic beautifulsoup4 lxml
"""

import sys, json, re, os
from pathlib import Path

# ─── paths ────────────────────────────────────────────────────────────────────
BASE      = Path(__file__).parent
EN_PDF    = BASE / "assets" / "CV Jose Gelves (EN).pdf"
ES_PDF    = BASE / "assets" / "CV Jose Gelves (ES).pdf"
INDEX     = BASE / "index.html"

# ─── auto-install deps ────────────────────────────────────────────────────────
def _ensure(pkg, import_name=None):
    import importlib, subprocess
    try:
        importlib.import_module(import_name or pkg)
    except ImportError:
        print(f"  installing {pkg}...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", pkg, "-q"])

_ensure("pdfplumber")
_ensure("anthropic")
_ensure("beautifulsoup4", "bs4")
_ensure("lxml")

import pdfplumber
import anthropic
from bs4 import BeautifulSoup, NavigableString

# ─── 1. download CVs ──────────────────────────────────────────────────────────
def download_cvs():
    print("Downloading CVs from Overleaf...")
    # reuse update_cv.py logic
    import importlib.util, types
    spec = importlib.util.spec_from_file_location("update_cv", BASE / "update_cv.py")
    mod  = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    sp = mod.ensure_playwright()
    mod.do_download(sp)

# ─── 2. extract PDF text ──────────────────────────────────────────────────────
def pdf_text(path: Path) -> str:
    with pdfplumber.open(path) as pdf:
        return "\n".join(page.extract_text() or "" for page in pdf.pages)

# ─── 3. Claude extraction ─────────────────────────────────────────────────────
PROMPT = """\
You are given the text of two CVs (EN and ES) for Jose Gelves Cabrera.
Extract the following data and return ONLY valid JSON with this exact schema:

{
  "about": {
    "p1_en": "first about paragraph in English (2-3 sentences, background + focus)",
    "p1_es": "primer párrafo en español",
    "p2_en": "second about paragraph in English (recent work highlights)",
    "p2_es": "segundo párrafo en español",
    "p3_en": "third about paragraph in English (building with AI agents)",
    "p3_es": "tercer párrafo en español"
  },
  "experience": [
    {
      "role_en": "Job title in English",
      "role_es": "Título en español",
      "org": "Organization name",
      "dates": "Month. Year – Month. Year  (e.g. Apr. 2025 – Present)",
      "desc_en": "1-2 sentence description in English",
      "desc_es": "descripción en español"
    }
  ],
  "education": [
    {
      "institution": "University name",
      "degree_en": "Degree · Minor etc",
      "degree_es": "Título en español",
      "dates": "Year – Year",
      "award_en": "Scholarship name and description (or empty string)",
      "award_es": "Beca en español (o cadena vacía)"
    }
  ]
}

Rules:
- experience: list the 4 most recent roles only, most recent first
- education: list all, most recent first
- Keep descriptions concise but specific (mention key outputs, numbers, methods)
- dates: use abbreviated month format: Jan. Feb. Mar. Apr. May Jun. Jul. Aug. Sep. Oct. Nov. Dec.
- Do NOT wrap in markdown code fences — return raw JSON only

=== EN CV TEXT ===
{en_text}

=== ES CV TEXT ===
{es_text}
"""

def extract_data(en_text: str, es_text: str) -> dict:
    api_key = os.environ.get("ANTHROPIC_API_KEY") or _load_dotenv_key()
    if not api_key:
        sys.exit("ERROR: ANTHROPIC_API_KEY not set. Export it or put it in a .env file.")

    client = anthropic.Anthropic(api_key=api_key)
    print("Calling Claude API to parse CV data...")
    msg = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4096,
        messages=[{
            "role": "user",
            "content": PROMPT.format(en_text=en_text[:12000], es_text=es_text[:12000])
        }]
    )
    raw = msg.content[0].text.strip()
    # strip markdown fences if present
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    return json.loads(raw)

def _load_dotenv_key():
    env = BASE / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            if line.startswith("ANTHROPIC_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"\'')
    return None

# ─── 4. update HTML ──────────────────────────────────────────────────────────
def update_html(data: dict):
    html = INDEX.read_text(encoding="utf-8")
    soup = BeautifulSoup(html, "lxml")

    changes = 0

    # ── about paragraphs ──
    about_section = soup.find("section", id="about")
    about_ps = about_section.select("p.body-text.reveal")
    about_map = [
        ("p1_en", "p1_es"),
        ("p2_en", "p2_es"),
        ("p3_en", "p3_es"),
    ]
    for idx, (key_en, key_es) in enumerate(about_map):
        if idx >= len(about_ps):
            break
        p = about_ps[idx]
        new_en = data["about"].get(key_en, "")
        new_es = data["about"].get(key_es, "")
        if new_en and p.get("data-en") != new_en:
            p["data-en"] = new_en
            p["data-es"] = new_es
            # update visible text
            for child in list(p.children):
                if isinstance(child, NavigableString):
                    child.replace_with(NavigableString("\n        " + new_en + "\n      "))
                    break
            changes += 1
            print(f"  updated about p{idx+1}")

    # ── experience items ──
    work_section  = soup.find("section", id="work")
    right_col     = work_section.select_one(".section-right")
    existing_items = right_col.select("div.exp-item")
    new_exp = data.get("experience", [])

    for i, exp in enumerate(new_exp):
        if i < len(existing_items):
            item = existing_items[i]
        else:
            # create new item
            item = soup.new_tag("div", **{"class": "exp-item reveal"})
            right_col.append(item)
            existing_items.append(item)

        # role
        role_el = item.select_one("h3.exp-role") or item.select_one(".exp-role")
        if role_el:
            role_el["data-en"] = exp["role_en"]
            role_el["data-es"] = exp["role_es"]
            role_el.string = exp["role_en"]

        # date
        date_el = item.select_one("span.exp-date")
        if date_el:
            date_el.string = exp["dates"]

        # org
        org_el = item.select_one("p.exp-org")
        if org_el:
            org_el.string = exp["org"]

        # desc
        desc_el = item.select_one("p.exp-desc")
        if desc_el:
            desc_el["data-en"] = exp["desc_en"]
            desc_el["data-es"] = exp["desc_es"]
            desc_el.string = exp["desc_en"]

        changes += 1

    # remove extra items if CV now has fewer entries
    for item in existing_items[len(new_exp):]:
        item.decompose()
        changes += 1

    # ── education items ──
    edu_section   = soup.find("section", id="education")
    edu_right     = edu_section.select_one(".section-right")
    existing_edu  = edu_right.select("div.exp-item")
    new_edu = data.get("education", [])

    for i, edu in enumerate(new_edu):
        if i < len(existing_edu):
            item = existing_edu[i]
        else:
            item = soup.new_tag("div", **{"class": "exp-item reveal"})
            edu_right.append(item)
            existing_edu.append(item)

        role_el = item.select_one("h3.exp-role") or item.select_one(".exp-role")
        if role_el:
            role_el.string = edu["institution"]

        date_el = item.select_one("span.exp-date")
        if date_el:
            date_el.string = edu["dates"]

        org_el = item.select_one("p.exp-org")
        if org_el:
            org_el["data-en"] = edu["degree_en"]
            org_el["data-es"] = edu["degree_es"]
            org_el.string = edu["degree_en"]

        desc_el = item.select_one("p.exp-desc")
        if desc_el and (edu.get("award_en") or edu.get("award_es")):
            desc_el["data-en"] = edu["award_en"]
            desc_el["data-es"] = edu["award_es"]
            desc_el.string = edu["award_en"]

        changes += 1

    # write back
    # lxml adds <!DOCTYPE> and <html><body> wrappers — strip them
    result = soup.decode(formatter="html5")
    # remove lxml-added wrapper if any
    result = re.sub(r"^<html><head></head><body>", "", result)
    result = re.sub(r"</body></html>$", "", result)

    # Use the raw serialization to preserve the original doctype
    output = str(soup)
    INDEX.write_text(output, encoding="utf-8")
    print(f"\nDone. {changes} section(s) updated in index.html.")

# ─── main ────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    skip_dl = "--no-dl" in sys.argv

    if not skip_dl:
        download_cvs()
    else:
        print("Skipping download (--no-dl).")

    print("Parsing PDFs...")
    en_text = pdf_text(EN_PDF)
    es_text = pdf_text(ES_PDF)

    data = extract_data(en_text, es_text)

    print("\nExtracted data preview:")
    print(f"  experience items : {len(data.get('experience', []))}")
    print(f"  education items  : {len(data.get('education', []))}")
    print()

    update_html(data)
