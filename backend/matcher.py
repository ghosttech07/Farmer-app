"""Rule-based symptom matcher. No generative model is involved in choosing the diagnosis."""
import json
import re
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path

KB_PATH = Path(__file__).parent / "knowledge_base.json"

CROP_BONUS = 2
CROP_MISMATCH_PENALTY = 4
STRONG_SCORE = 6      # minimum score for a confident answer
STRONG_MARGIN = 2     # lead needed over the runner-up
MIN_SCORE = 2         # below this we have nothing useful: escalate

_TELUGU_DIGITS = str.maketrans("౦౧౨౩౪౫౬౭౮౯०१२३४५६७८९", "0123456789" * 2)  # Telugu, Devanagari


def load_kb(path=KB_PATH):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFC", text or "").lower()
    text = text.translate(_TELUGU_DIGITS)
    text = text.replace("‌", "").replace("‍", "")  # ZWNJ/ZWJ
    return re.sub(r"\s+", " ", text).strip()


def detect_crops(text: str, kb: dict) -> set:
    t = normalize(text)
    return {crop for crop, words in kb["crops"].items() if any(normalize(w) in t for w in words)}


FUZZY_RATIO = 0.85  # English speech-to-text slips: "bowlworm"/"ballworm" for bollworm, "army worm" for armyworm
FUZZY_MIN_LEN = 6   # short words ("blast", "thrips") stay exact: too many near neighbours


def _has(keyword: str, t: str) -> bool:
    k = normalize(keyword)
    if k in t:
        return True
    if len(k) < FUZZY_MIN_LEN or not k.isascii():
        return False
    words, n = t.split(), len(k.split())
    spans = {" ".join(words[i:i + size]) for size in (n, n + 1) for i in range(len(words) - size + 1)}
    return any(SequenceMatcher(None, k, s).ratio() >= FUZZY_RATIO for s in spans)


def score_entry(text: str, entry: dict, crops: set) -> tuple:
    t = normalize(text)
    score, hits = 0, []
    for group in entry["symptoms"]:
        matched = [k for k in group["k"] if _has(k, t)]
        if matched:  # a group counts once, however many synonyms hit
            score += group["w"]
            hits.append(matched[0])
    if hits:  # crop evidence only adjusts entries that already have symptom evidence
        if crops & set(entry["crops"]):
            score += CROP_BONUS
        elif crops:
            score -= CROP_MISMATCH_PENALTY
    return score, hits


def match(text: str, kb: dict) -> dict:
    """Return {status: strong|ambiguous|none, entry, candidates, score, hits, crops}."""
    crops = detect_crops(text, kb)
    ranked = []
    for entry in kb["entries"]:
        s, hits = score_entry(text, entry, crops)
        if s > 0:
            ranked.append((s, entry, hits))
    ranked.sort(key=lambda r: r[0], reverse=True)

    base = {"crops": sorted(crops), "candidates": [r[1]["id"] for r in ranked[:3]]}
    if not ranked or ranked[0][0] < MIN_SCORE:
        return {**base, "status": "none", "entry": None, "score": ranked[0][0] if ranked else 0, "hits": []}

    top_score, top, hits = ranked[0]
    runner = ranked[1][0] if len(ranked) > 1 else 0
    strong = top_score >= STRONG_SCORE and top_score - runner >= STRONG_MARGIN
    return {**base, "status": "strong" if strong else "ambiguous", "entry": top, "score": top_score, "hits": hits}
