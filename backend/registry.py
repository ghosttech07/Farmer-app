"""Read-only access to pesticides.db: every use registered by CIB&RC (crop, pest, product, dose, waiting period).

Built by tools/build_pesticide_db.py from the official "Major Uses of Pesticides" lists. Used to
1) show other registered options for a diagnosed problem, and 2) check the knowledge base against the official rows.
"""
import re
import sqlite3
from functools import lru_cache
from pathlib import Path

DB = Path(__file__).parent / "pesticides.db"

# Knowledge-base crop ids -> how the CIB&RC lists name those crops
CROP_NAMES = {
    "rice": ["rice", "paddy"],
    "cotton": ["cotton"],
    "chilli": ["chilli", "chillies", "chilies", "chili"],
    "groundnut": ["groundnut", "ground nut"],
    "tomato": ["tomato"],
    "maize": ["maize", "corn"],
    "pulses": ["pigeon pea", "red gram", "redgram", "bengal gram", "chickpea", "chick pea", "gram", "black gram",
               "green gram", "cowpea", "cow pea", "moong", "urid", "urd", "arhar", "tur", "pea"],
    "vegetable": ["brinjal", "okra", "bhindi", "cabbage", "cauliflower", "vegetable", "cucumber", "bitter gourd", "beans"],
    "wheat": ["wheat"],
    "sugarcane": ["sugarcane"],
    "onion": ["onion"],
    "potato": ["potato"],
    "soybean": ["soybean", "soyabean"],
    "mango": ["mango"],
    "banana": ["banana"],
    "brinjal": ["brinjal"],
    "okra": ["okra", "bhindi"],
    "cabbage": ["cabbage", "cauliflower"],
    "mustard": ["mustard"],
}
GRAM_FORMS = r"\b(WP|WG|WDG|SG|SP|DP|GR|WS|DS|DF|Granules?|Dust|Powder|TB|Tablet)\b"
ML_FORMS = r"\b(EC|SC|SL|EW|OD|SE|CS|ME|FS|ZC|SC-SE|EC/SC|L|Liquid|AS|DC)\b"


def available() -> bool:
    return DB.exists()


@lru_cache(maxsize=1)
def _rows():
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    rows = [dict(r) for r in con.execute("SELECT * FROM uses")]
    meta = dict(con.execute("SELECT key, value FROM meta").fetchall())
    con.close()
    return rows, meta


def meta() -> dict:
    return _rows()[1] if available() else {}


def unit(product: str) -> str:
    if re.search(GRAM_FORMS, product, re.I):
        return "g"
    if re.search(ML_FORMS, product, re.I):
        return "ml"
    return ""


def _amounts(text: str):
    """'1500 - 2000' -> (1500, 2000); '1.5-2kg' -> (1500, 2000); None when it is not a plain per-hectare amount."""
    t = (text or "").lower().replace(",", "")
    t = re.sub(r"\s+\d+(?:\.\d+)?\s*\(via drone.*", "", t)  # "500 20 (via Drone application)": knapsack figure first
    if re.search(r"seed|tree|plant|sucker|/l|per l|%|ppm|m2|m3|broadcast|drone|bait|cfu", t):
        return None
    nums = [float(n) for n in re.findall(r"\d+(?:\.\d+)?", t)]
    if not nums or len(nums) > 2:
        return None
    if re.search(r"\b(kg|lit|litre|liter|l)\b|kg", t) and max(nums) < 50:
        nums = [n * 1000 for n in nums]
    return min(nums), max(nums)


def per_litre(row: dict):
    """Dose per litre of spray from the per-hectare figures, as (low, high, unit), or None."""
    f, w, u = _amounts(row["formulation_per_ha"]), _amounts(row["water_l_per_ha"]), unit(row["product"])
    if not f or not w or not u or w[0] < 100:  # less than 100 L/ha is drone or ULV spraying, not a knapsack
        return None
    low, high = f[0] / w[1], f[1] / w[0]
    if low < 0.05 or high > 15:  # outside any knapsack dose: a misread row in the PDF, not a real dose
        return None
    return round(low, 2), round(high, 2), u


def fmt(pl) -> str:
    low, high, u = pl
    n = lambda x: f"{x:g}" if x >= 1 else f"{x:.2g}"
    return f"{n(low)} {u}" if abs(high - low) < 0.01 else f"{n(low)}-{n(high)} {u}"


def _crop_hit(db_crop: str, crop_id: str) -> bool:
    c = db_crop.lower()
    return any(re.search(rf"\b{re.escape(name)}\b", c) for name in CROP_NAMES.get(crop_id, [crop_id]))


def uses(crop_id: str, pest_terms: list) -> list:
    """Registered uses for a crop and a pest (any of pest_terms appears in the official pest column)."""
    if not available():
        return []
    terms = [t.lower() for t in pest_terms]
    return [r for r in _rows()[0] if _crop_hit(r["crop"], crop_id) and any(t in r["pest"].lower() for t in terms)]


def same_product(a: str, b: str) -> bool:
    """'Fipronil 05 % SC' == 'Fipronil 5% SC'; 'Chlorantraniliprole 18.50 % SC' == 'Chlorantraniliprole 18.5% SC'."""
    def key(s):
        s = re.sub(r"\(.*?\)", "", s.lower())
        s = re.sub(r"(\d)\.\s+(\d)", r"\1.\2", s)  # "22. 0%" in the PDF
        s = re.sub(r"(\d+(?:\.\d+)?)", lambda m: f"{float(m.group()):g}", s)
        return re.sub(r"[^a-z0-9.%+]", "", s.replace("w/w", "").replace("min.", ""))
    ka, kb = key(a), key(b)
    return ka == kb or ka.startswith(kb) or kb.startswith(ka)


def options(crop_id: str, pest_terms: list, exclude: str = "", limit: int = 4) -> list:
    """Other sprays registered for this crop and pest, shortest waiting period first (one row per product)."""
    seen, out = set(), []
    rows = sorted(uses(crop_id, pest_terms), key=lambda r: (r["waiting_days"] is None, r["waiting_days"] or 0))
    for r in rows:
        pl = per_litre(r)
        if not pl or r["product"] in seen or (exclude and same_product(r["product"], exclude)):
            continue
        seen.add(r["product"])
        out.append({"product": r["product"], "per_litre": fmt(pl), "waiting_days": r["waiting_days"],
                    "waiting_period": r["waiting_period"], "crop": r["crop"], "pest": r["pest"],
                    "page": r["page"], "url": r["source_url"]})
        if len(out) == limit:
            break
    return out
