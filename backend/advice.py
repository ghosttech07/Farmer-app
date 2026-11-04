"""Builds the farmer-facing answer. The KB entry is the only source of products and doses."""
import json
import re

import gnani
import registry
from matcher import normalize

LANGS = ("te", "hi", "en")
LANG_NAMES = {"te": "Telugu", "hi": "Hindi", "en": "English"}

ESCALATE = {
    "te": "మీ సమస్యను ఖచ్చితంగా గుర్తించలేకపోయాను. దయచేసి మీ స్థానిక వ్యవసాయ అధికారిని లేదా రైతు సేవా కేంద్రాన్ని సంప్రదించండి. కిసాన్ కాల్ సెంటర్: 1800-180-1551.",
    "hi": "मैं आपकी समस्या ठीक से नहीं पहचान पाया। कृपया अपने स्थानीय कृषि अधिकारी या किसान सेवा केंद्र से संपर्क करें। किसान कॉल सेंटर: 1800-180-1551.",
    "en": "I could not identify the problem reliably. Please contact your local agriculture officer or Kisan Call Centre 1800-180-1551.",
}
ESCALATE_TE, ESCALATE_EN = ESCALATE["te"], ESCALATE["en"]

TEMPLATE = {
    "te": "మీ సమస్య {name} అయి ఉండవచ్చు. {cause} చికిత్స: {product}, {dose}. పిచికారీ చేసిన తర్వాత కోతకు {days} రోజులు ఆగాలి.",
    "hi": "आपकी समस्या {name} हो सकती है। {cause} इलाज: {product}, {dose}। छिड़काव के बाद कटाई से पहले {days} दिन रुकें।",
    "en": "Your problem may be {name}. {cause} Treatment: {product}, {dose}. After spraying, wait {days} days before harvest.",
}


def evon_system(lang: str) -> str:
    name = LANG_NAMES[lang]
    return (
        f"You are a careful agriculture assistant for {name}-speaking farmers. "
        f"Rewrite the given advisory in simple, short, spoken {name} (4-6 sentences). "
        "Use ONLY facts in the provided JSON. Do not add any product, dose, crop, or advice that is not in it. "
        "Keep the product name exactly as written in English letters and keep every number unchanged. "
        f"Mention the waiting period before harvest. Output only the {name} answer."
    )


EVON_SYSTEM = evon_system("te")


def lang_or_default(lang) -> str:
    return lang if lang in LANGS else "te"


def loc(entry: dict, field: str, lang: str) -> str:
    """name, cause, dose or followup of a KB entry in one language."""
    t = entry["treatment"]
    if lang == "en":
        return f"{t['dose_per_litre']} per litre of water" if field == "dose" else entry[f"{field}_en"]
    if lang == "te":
        return t["dose_te"] if field == "dose" else entry[f"{field}_te"]
    return entry["i18n"][lang][field]


def waiting_days(entry: dict, crop: str | None) -> int:
    """Label waiting period for the farmer's crop; if the crop is unknown, the longest one (the safe choice)."""
    by_crop = entry.get("waiting_by_crop", {})
    if crop in by_crop:
        return by_crop[crop]
    return max([entry["waiting_days"], *by_crop.values()])


def template_answer(entry: dict, lang: str = "te") -> str:
    return TEMPLATE[lang].format(name=loc(entry, "name", lang), cause=loc(entry, "cause", lang),
                                 product=entry["treatment"]["product"], dose=loc(entry, "dose", lang),
                                 days=entry["waiting_days"])


def _numbers(s: str) -> set:
    return set(re.findall(r"\d+(?:\.\d+)?", normalize(s)))


def evon_is_faithful(text: str, entry: dict, lang: str = "te") -> bool:
    """Reject Evon output that dropped the product/dose/waiting period or introduced new numbers."""
    t = entry["treatment"]
    if t["product"].split()[0].lower() not in text.lower():
        return False
    allowed = _numbers(t["product"] + " " + loc(entry, "dose", lang) + " " + t["dose_per_litre"] + f" {entry['waiting_days']}")
    got = _numbers(text)
    needed = _numbers(t["dose_per_litre"]) | {str(entry["waiting_days"])}
    return needed <= got and got <= allowed


def strong_answer(entry: dict, lang: str = "te") -> tuple:
    """Returns (answer_text_in_lang, phrased_by)."""
    if not gnani.mock_mode() and gnani.evon_available():
        try:
            payload = json.dumps(
                {"name": loc(entry, "name", lang), "cause": loc(entry, "cause", lang), "product": entry["treatment"]["product"],
                 "dose": loc(entry, "dose", lang), "waiting_days": entry["waiting_days"]},
                ensure_ascii=False,
            )
            text = gnani.phrase_with_evon(evon_system(lang), payload)
            if evon_is_faithful(text, entry, lang):
                return text, "evon"
        except Exception:
            pass  # fall through to the deterministic template
    return template_answer(entry, lang), "template"


def build(result: dict, kb: dict, can_ask_followup: bool = True, lang: str = "te", block_unverified: bool = False) -> dict:
    """block_unverified: during a farmer pilot, an entry nobody has checked against PJTSAU/ICAR and the label
    is sent to the officer instead of showing its dose."""
    lang = lang_or_default(lang)
    meta = kb["_meta"]
    status, entry = result["status"], result["entry"]
    if entry and block_unverified and not entry.get("verified"):
        status = "none"
    out = {"status": status, "lang": lang, "disclaimer": meta[f"disclaimer_{lang}"], "disclaimer_en": meta["disclaimer_en"],
           "matched_id": entry["id"] if entry else None, "candidates": result["candidates"]}

    if status == "strong":
        said = next((c for c in result.get("crops", []) if c in entry["crops"]), None)
        crop = said or entry["crops"][0]
        entry = {**entry, "waiting_days": waiting_days(entry, said)}
        text, by = strong_answer(entry, lang)
        out.update(answer=text, phrased_by=by, source=entry["source"], verified=bool(entry.get("verified")),
                   name=loc(entry, "name", lang), name_en=entry["name_en"],
                   cause=loc(entry, "cause", lang), cause_en=entry["cause_en"],
                   crop=kb["crop_names"][crop][lang], crop_en=kb["crop_names"][crop]["en"],
                   crop_id=said,  # the crop the farmer named, if any (decides the waiting period)
                   # other sprays CIB&RC registers for this crop and pest; only when the crop is certain
                   options=registry.options(said or entry["crops"][0], entry.get("pest_terms", []),
                                            exclude=entry["treatment"]["product"])
                   if (said or len(entry["crops"]) == 1) and entry.get("pest_terms") else [],
                   treatment={"product": entry["treatment"]["product"], "dose": entry["treatment"]["dose_per_litre"] + " per litre",
                              "per_litre": entry["treatment"]["dose_per_litre"],
                              "dose_local": loc(entry, "dose", lang), "waiting_days": entry["waiting_days"]})
    elif status == "ambiguous" and can_ask_followup:
        out.update(answer=loc(entry, "followup", lang), answer_en=entry["followup_en"], followup=True)
    else:
        out.update(status="escalate", answer=ESCALATE[lang], answer_en=ESCALATE["en"])
    return out
