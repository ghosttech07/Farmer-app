"""Build backend/pesticides.db from the CIB&RC "Major Uses of Pesticides" lists (ppqs.gov.in).

Every row of the official lists becomes one registered use: product, crop, pest, dose per hectare, water per hectare,
waiting period, with the source PDF and page. The app only reads the database (Python's built-in sqlite3); this
script is a developer tool and needs PyMuPDF (pip install pymupdf).

    python tools/build_pesticide_db.py <folder for the PDFs>      # downloads the PDFs if missing, then builds
"""
import re
import sqlite3
import sys
from pathlib import Path

import fitz  # PyMuPDF
import requests

AS_ON = "30.09.2026"
BASE = "https://ppqs.gov.in/sites/default/files/"
LISTS = [  # (kind, file name on ppqs.gov.in, pages with agricultural uses)
    ("insecticide", "MUP%20%28insecticide%29%20%2030.09.2026.pdf", range(2, 85)),  # p.85 on: public health, household
    ("fungicide", "Fungicide%20MUP%20%20as%20on%2030.09.2026.pdf", range(2, 92)),
    ("bio-insecticide", "MUP%20%28bio%20insecticide%29%2030.09.2026.pdf", range(1, 20)),
    ("bio-fungicide", "3.%20bio%20fungicides%20MUP%20as%20on%2030.09.2026.pdf", range(1, 60)),
]
HERE = Path(__file__).resolve().parent.parent
DB = HERE / "pesticides.db"

# Public-health, household and storage rows that sit between the crop rows in some tables
NOT_A_CROP = re.compile(r"culex|aedes|anoph|mosquito|housefl|cockroach|bed bug|godown|stored|warehouse|termite proof|"
                        r"building|wood|fumigation", re.I)
HEADER_WORDS = ("crop", "name of", "common name", "dosage", "formulation", "dilution", "waiting", "a.i", "pest")
FORMULATION = re.compile(r"\b(\d+(?:\.\d+)?\s*%|EC|SC|WP|WG|WDG|SG|SP|DP|GR|CS|EW|SL|OD|SE|ME|FS|WS|DS|ZC|SE|Granules|Dust|L)\b", re.I)


def clean(v):
    if v is None:
        return ""
    v = v.replace("�", "-").replace("–", "-").replace("—", "-").replace("\n", " ")
    return re.sub(r"\s+", " ", v).strip()


def is_product(cells):
    """A full-width row naming the product, e.g. 'Chlorantraniliprole 18.50 % SC'."""
    filled = [c for c in cells if c]
    if len(filled) != 1:
        return False
    name = filled[0]
    return bool(FORMULATION.search(name)) and not any(w in name.lower() for w in HEADER_WORDS) and len(name) < 140


def waiting_min(text):
    m = re.search(r"\d+", text or "")
    return int(m.group()) if m and re.fullmatch(r"\s*\d+\s*(?:-\s*\d+)?\s*(?:days?)?\s*", text or "", re.I) else None


def rows_of(page):
    for table in page.find_tables().tables:
        for raw in table.extract():
            yield [clean(c) for c in raw]


def build(pdf_dir: Path):
    pdf_dir.mkdir(parents=True, exist_ok=True)
    if DB.exists():
        DB.unlink()
    con = sqlite3.connect(DB)
    con.executescript(
        """
        CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT);
        CREATE TABLE uses(
            id INTEGER PRIMARY KEY, kind TEXT, product TEXT, crop TEXT, pest TEXT,
            ai_per_ha TEXT, formulation_per_ha TEXT, water_l_per_ha TEXT, waiting_period TEXT, waiting_days INTEGER,
            source_url TEXT, page INTEGER);
        CREATE INDEX uses_crop ON uses(crop);
        CREATE INDEX uses_product ON uses(product);
        """
    )
    total = 0
    for kind, name, pages in LISTS:
        pdf = pdf_dir / (kind + ".pdf")
        if not pdf.exists():
            r = requests.get(BASE + name, timeout=120)
            r.raise_for_status()
            pdf.write_bytes(r.content)
        doc = fitz.open(pdf)
        product, crop, n = None, None, 0
        for p in pages:
            if p > len(doc):
                break
            for cells in rows_of(doc[p - 1]):
                if is_product(cells):
                    product, crop = next(c for c in cells if c), None
                    continue
                vals = [c for c in cells if c != ""]
                if not product or len(vals) < 5 or any(w in " ".join(vals[:2]).lower() for w in ("crop", "name of")):
                    continue
                # crop column empty = same crop as the row above
                if cells[0] == "" and len(vals) == 5:
                    vals = [crop] + vals
                if len(vals) < 6:
                    continue
                crop = vals[0]
                if NOT_A_CROP.search(crop):
                    continue
                c, pest, ai, form, water, wait = vals[0], vals[1], vals[2], vals[3], vals[4], " ".join(vals[5:])
                con.execute(
                    "INSERT INTO uses(kind, product, crop, pest, ai_per_ha, formulation_per_ha, water_l_per_ha,"
                    " waiting_period, waiting_days, source_url, page) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (kind, product, c, pest, ai, form, water, wait, waiting_min(wait), BASE + name, p),
                )
                n += 1
        print(f"{kind}: {n} registered uses")
        total += n
    con.executemany("INSERT INTO meta VALUES (?,?)", [
        ("source", "CIB&RC, Major Uses of Pesticides (registered under the Insecticides Act, 1968), ppqs.gov.in"),
        ("as_on", AS_ON),
        ("disclaimer", "Compiled by CIB&RC for guidance and not for legal purposes; the product label is final."),
    ])
    con.commit()
    con.close()
    print(f"{total} uses -> {DB}")


if __name__ == "__main__":
    build(Path(sys.argv[1]) if len(sys.argv) > 1 else HERE / ".cibrc_pdfs")
