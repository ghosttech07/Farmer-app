"""Guided answers for broad questions ("there are caterpillars on my plant, what do I do?").

When the symptom matcher cannot name one problem, the app does not give up: it asks which crop (if none was said),
then lists that crop's problems of the kind the farmer described (caterpillars / sucking insects / disease) as
choices. Picking one gives the full checked answer. Only "none of these" goes to the agriculture officer.
Nothing here invents advice: the choices are knowledge-base entries, each checked against CIB&RC.
"""
import advice
from matcher import normalize

# What kind of problem the farmer is describing, in Telugu, Hindi and English
KINDS = {
    "chewing": ["గొంగళి", "లద్దె", "తొలుచు", "తొలిచే", "ఆకులు తిన", "ఆకులను తిన", "కాయలు తిన", "రంధ్ర",
                "इल्ली", "इल्लियाँ", "इल्लियां", "सुंडी", "सूंडी", "कैटरपिलर", "छेदक", "पत्ते खा", "पत्तियाँ खा", "छेद",
                "caterpillar", "worm", "larva", "larvae", "borer", "eating the leaves", "eating leaves", "holes"],
    "sucking": ["రసం పీల్చ", "పేనుబంక", "దోమ", "నల్లి", "తామర", "చిన్న పురుగులు",
                "रस चूस", "माहू", "मक्खी", "तेला", "थ्रिप्स", "माइट", "छोटे कीड़े",
                "aphid", "sucking", "whitefl", "white fl", "jassid", "thrips", "mite", "hopper", "small insects", "tiny insects"],
    "disease": ["తెగులు", "మచ్చ", "బూజు", "కుళ్ళు", "ఎండిపో", "మాడు", "వ్యాధి",
                "रोग", "धब्बे", "धब्बा", "फफूंद", "सड़", "झुलसा", "बीमारी", "सूख",
                "disease", "spot", "fungus", "rot", "blight", "mildew", "rust", "drying", "dying"],
}
# Plain "insects / pests" without saying which kind: show both insect kinds
INSECTS = ["పురుగు", "కీటక", "కీడ", "कीड़", "कीड़े", "कीट", "insect", "pest", "bug"]

ENTRY_KIND = {
    "chewing": {"rice_stem_borer", "cotton_pink_bollworm", "fruit_borer", "maize_faw", "rice_leaf_folder", "rice_gall_midge",
                "cotton_american_bollworm", "groundnut_leaf_miner", "groundnut_spodoptera", "tomato_leaf_miner",
                "maize_stem_borer", "brinjal_shoot_fruit_borer", "cabbage_dbm", "sugarcane_early_shoot_borer",
                "soybean_girdle_beetle", "soybean_semilooper"},
    "sucking": {"rice_bph", "cotton_whitefly", "chilli_thrips", "aphids", "cotton_jassids", "cotton_mealybug", "chilli_mites",
                "wheat_aphid", "onion_thrips", "mango_hopper", "mustard_aphid", "cotton_thrips"},
}

ASK_CROP = {
    "te": "ఈ సమస్య ఏ పంటలో ఉంది? కింద మీ పంటను ఎంచుకోండి.",
    "hi": "यह समस्या किस फसल में है? नीचे अपनी फसल चुनें।",
    "en": "Which crop has this problem? Choose your crop below.",
}
PICK = {
    "te": "మీ {crop} పంటలో వీటిలో ఏది కనిపిస్తోంది? దాన్ని ఎంచుకోండి.",
    "hi": "आपकी {crop} फसल में इनमें से क्या दिख रहा है? उसे चुनें।",
    "en": "Which of these do you see on your {crop}? Choose one.",
}
MAX_CHOICES = 8


def entry_kind(entry_id: str) -> str:
    for kind, ids in ENTRY_KIND.items():
        if entry_id in ids:
            return kind
    return "disease"


def kinds_in(text: str) -> set:
    t = normalize(text)
    found = {k for k, words in KINDS.items() if any(normalize(w) in t for w in words)}
    if not found and any(normalize(w) in t for w in INSECTS):
        found = {"chewing", "sucking"}
    return found


def crop_choices(kb: dict, lang: str) -> list:
    return [{"id": c, "label": kb["crop_names"][c][lang]} for c in kb["crops"]]


def problem_choices(kb: dict, crop: str, kinds: set, lang: str, first: list = ()) -> list:
    on_crop = [e for e in kb["entries"] if crop in e["crops"]]
    picked = [e for e in on_crop if not kinds or entry_kind(e["id"]) in kinds] or on_crop
    picked.sort(key=lambda e: (e["id"] not in first, list(first).index(e["id"]) if e["id"] in first else 0))
    return [{"id": e["id"], "label": advice.loc(e, "name", lang)} for e in picked[:MAX_CHOICES]]


def guide(text: str, kb: dict, crops: list, lang: str, candidates: list = ()) -> dict:
    """status 'choose': choose = 'crop' (which crop?) or 'problem' (which of these problems?)."""
    lang = advice.lang_or_default(lang)
    base = {"status": "choose", "lang": lang, "matched_id": None, "candidates": list(candidates),
            "disclaimer": kb["_meta"][f"disclaimer_{lang}"], "disclaimer_en": kb["_meta"]["disclaimer_en"],
            "context": text}
    known = [c for c in crops if c in kb["crop_names"]]
    if not known:
        return {**base, "choose": "crop", "answer": ASK_CROP[lang], "answer_en": ASK_CROP["en"],
                "choices": crop_choices(kb, lang)}
    crop = known[0]
    choices = problem_choices(kb, crop, kinds_in(text), lang, candidates)
    if not choices:
        return None
    return {**base, "choose": "problem", "crop_id": crop,
            "answer": PICK[lang].format(crop=kb["crop_names"][crop][lang]),
            "answer_en": PICK["en"].format(crop=kb["crop_names"][crop]["en"]), "choices": choices}
