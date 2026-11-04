import json
import os
import secrets
import threading
import time
from collections import defaultdict, deque
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS

load_dotenv()

import advice  # noqa: E402
import general  # noqa: E402
import gnani  # noqa: E402
import matcher  # noqa: E402

HERE = Path(__file__).parent


def _env_flag(name: str) -> bool:
    return os.getenv(name, "0").strip() == "1"


# Settings come from .env (see .env.example).
ALLOWED_ORIGINS = [o.strip() for o in os.getenv("ALLOWED_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",") if o.strip()]
def _path_setting(name: str, default: Path) -> Path:
    p = Path(os.getenv(name, str(default)))
    return p if p.is_absolute() else (HERE / p).resolve()


LOG = _path_setting("PILOT_LOG_PATH", HERE / "pilot_log.jsonl")
RATE_LIMIT_PER_MIN = int(os.getenv("RATE_LIMIT_PER_MIN", "20"))
FRONTEND_DIST = _path_setting("FRONTEND_DIST", HERE.parent / "frontend" / "dist")
MAX_AUDIO = 5 * 1024 * 1024
MAX_TEXT = 500
MAX_CONTEXT = 1000
SPEECH_CODES = {"te": "te-IN", "hi": "hi-IN", "en": "en-IN"}
LANGUAGE_NAMES = {"te": "Telugu", "hi": "Hindi", "en": "English"}

app = Flask(__name__, static_folder=None)
CORS(app, resources={r"/api/*": {"origins": ALLOWED_ORIGINS}})
KB = matcher.load_kb()

_log_lock = threading.Lock()
_hits = defaultdict(deque)
_hits_lock = threading.Lock()


def _log(record: dict):
    record["ts"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with _log_lock, open(LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def _client_ip() -> str:
    # Behind a proxy (Render, Railway, Docker host), set TRUST_PROXY=1 so the farmer's own address is used.
    if _env_flag("TRUST_PROXY"):
        forwarded = request.headers.get("X-Forwarded-For", "")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return request.remote_addr or "unknown"


def _rate_limited() -> bool:
    """Sliding one-minute window per client, so one phone cannot burn through the Gnani credits."""
    if RATE_LIMIT_PER_MIN <= 0:
        return False
    now = time.monotonic()
    with _hits_lock:
        q = _hits[_client_ip()]
        while q and now - q[0] > 60:
            q.popleft()
        if len(q) >= RATE_LIMIT_PER_MIN:
            return True
        q.append(now)
    return False


def _make_ref() -> str:
    """A short code the farmer can read out on a follow-up call, e.g. PS-261104-K7M2."""
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return f"PS-{time.strftime('%y%m%d')}-" + "".join(secrets.choice(alphabet) for _ in range(4))


@app.get("/api/health")
def health():
    return {
        "ok": True,
        "mock": gnani.mock_mode(),
        "entries": len(KB["entries"]),
        "verified": sum(1 for e in KB["entries"] if e.get("verified")),
        "block_unverified": _env_flag("BLOCK_UNVERIFIED"),
        "gnani_configured": gnani.configured(),
        "stt_languages": [code for code, speech in SPEECH_CODES.items() if gnani.stt_supports(speech)],
    }


@app.post("/api/advise")
def advise():
    """multipart: audio (16k mono wav) OR text; optional context = earlier transcript(s) when answering a follow-up;
    optional confirm_id = KB entry the farmer said "yes" to in the follow-up question; input = Voice | Typed."""
    if _rate_limited():
        return jsonify(error="rate_limited", detail="Too many questions from this device; wait a minute."), 429

    context = request.form.get("context", "")[:MAX_CONTEXT]
    transcript = request.form.get("text", "").strip()
    if len(transcript) > MAX_TEXT:
        return jsonify(error="too_long", detail=f"Describe the problem in under {MAX_TEXT} characters."), 413
    audio = request.files.get("audio")
    confirm_id = request.form.get("confirm_id", "")
    lang = advice.lang_or_default(request.form.get("lang"))
    input_kind = request.form.get("input") if request.form.get("input") in ("Voice", "Typed") else ("Voice" if audio else "Typed")
    block = _env_flag("BLOCK_UNVERIFIED")

    if confirm_id:
        entry = next((e for e in KB["entries"] if e["id"] == confirm_id), None)
        if not entry:
            return jsonify(error="unknown entry"), 400
        crops = sorted(matcher.detect_crops(context, KB))
        resp = advice.build({"status": "strong", "entry": entry, "candidates": [confirm_id], "crops": crops}, KB,
                            lang=lang, block_unverified=block)
        resp.update(transcript=context, context="")
        return _finish(resp, "confirm", input_kind)

    if audio and not transcript:
        data = audio.read()
        if len(data) > MAX_AUDIO:
            return jsonify(error="audio too large"), 413
        if gnani.mock_mode():
            return jsonify(error="mock mode: send 'text' instead of audio"), 400
        if not gnani.stt_supports(SPEECH_CODES[lang]):
            return jsonify(error="language_unsupported", detail="Gnani speech-to-text does not cover this language"), 400
        try:
            transcript = gnani.transcribe(data, SPEECH_CODES[lang])
        except gnani.GnaniError as e:
            app.logger.warning("STT failed: %s", e)
            status = 502 if e.status >= 500 or e.status in (401, 402, 403, 429) else 400
            return jsonify(error="stt_failed", kind=e.kind), status
        except Exception:
            app.logger.exception("STT failed")
            return jsonify(error="stt_failed"), 502
    # The farmer tapped a crop button: the crop's name joins what they already said
    picked_crop = request.form.get("crop", "")
    if picked_crop in KB["crops"]:
        transcript = transcript or next((w for w in KB["crops"][picked_crop] if w.isascii()), picked_crop)
    want_guide = request.form.get("guide") == "1"  # farmer said "no" to the yes/no question
    if not transcript and not want_guide:
        return jsonify(error="no speech detected", status="empty"), 400

    combined = f"{context} {transcript}".strip()
    result = matcher.match(combined, KB)
    # Not one clear problem: ask the crop / offer that crop's problems instead of giving up.
    # (A first ambiguous result still gets its one yes/no question.)
    if want_guide or result["status"] == "none" or (result["status"] == "ambiguous" and context):
        rejected = request.form.get("reject", "")
        resp = general.guide(combined, KB, result["crops"], lang, [c for c in result["candidates"] if c != rejected])
        if resp:
            resp.update(transcript=transcript or context)
            return _finish(resp, "advise", input_kind)
    resp = advice.build(result, KB, can_ask_followup=not context, lang=lang, block_unverified=block)
    resp.update(transcript=transcript, context=combined if resp.get("followup") else "")
    return _finish(resp, "advise", input_kind)


@app.post("/api/answer")
def answer_in_language():
    """The farmer switches language on the answer screen: the same answer, text and voice, in the new language.
    JSON: kind = strong | followup | escalate, matched_id, crop (crop_id from the first answer), lang, ref."""
    if _rate_limited():
        return jsonify(error="rate_limited", detail="Too many questions from this device; wait a minute."), 429
    j = request.get_json(silent=True) or {}
    lang = advice.lang_or_default(j.get("lang"))
    kind = j.get("kind")
    entry = next((e for e in KB["entries"] if e["id"] == j.get("matched_id")), None)
    crop = j.get("crop") if j.get("crop") in KB["crop_names"] else None
    if kind in ("strong", "followup") and not entry:
        return jsonify(error="unknown entry"), 400
    if kind == "choose":  # crop or problem choices, re-read in the new language
        context = str(j.get("context", ""))[:MAX_CONTEXT]
        crops = [crop] if crop else sorted(matcher.detect_crops(context, KB))
        resp = general.guide(context, KB, crops, lang, [c for c in j.get("candidates", []) if isinstance(c, str)])
        if not resp:
            return jsonify(error="nothing to choose"), 400
        result = None
    elif kind == "strong":
        result = {"status": "strong", "entry": entry, "candidates": [entry["id"]], "crops": [crop] if crop else []}
    elif kind == "followup":
        result = {"status": "ambiguous", "entry": entry, "candidates": [entry["id"]]}
    elif kind == "escalate":
        result = {"status": "none", "entry": None, "candidates": []}
    else:
        return jsonify(error="kind must be strong, followup, escalate or choose"), 400
    if result:
        resp = advice.build(result, KB, lang=lang, block_unverified=_env_flag("BLOCK_UNVERIFIED"))
    _speak(resp)
    ref = str(j.get("ref", ""))[:40]
    resp["ref"] = ref or _make_ref()
    _log({"event": "language_switch", "ref": resp["ref"], "language": LANGUAGE_NAMES[lang], "matched": resp["matched_id"]})
    return jsonify(resp)


def _speak(resp: dict):
    """Gnani Timbre voice for the answer; '' when Timbre fails, so the phone speaks it."""
    resp["audio_base64"] = ""
    if gnani.mock_mode():
        return
    try:
        resp["audio_base64"] = gnani.synthesize(resp["answer"], SPEECH_CODES[resp["lang"]])
    except Exception:
        app.logger.exception("TTS failed")


def _finish(resp: dict, event: str, input_kind: str):
    _speak(resp)
    resp["ref"] = _make_ref()
    outcome = ("Answered" if resp["status"] == "strong" else "Follow-up asked" if resp.get("followup")
               else f"Asked to choose a {resp['choose']}" if resp["status"] == "choose" else "Escalated")
    _log({
        "event": event,
        "ref": resp["ref"],
        "language": LANGUAGE_NAMES[resp["lang"]],
        "input": input_kind,
        "outcome": outcome,
        "matched": resp["matched_id"],
        "problem": resp.get("name_en"),
        "crop": resp.get("crop_en"),
        "phrased_by": resp.get("phrased_by"),
        "transcript": resp["transcript"],
    })
    return jsonify(resp)


@app.post("/api/feedback")
def feedback():
    """Pilot data: was the advice useful, and what did the farmer do next?"""
    if _rate_limited():
        return jsonify(error="rate_limited"), 429
    j = request.get_json(silent=True) or {}
    lang = advice.lang_or_default(j.get("lang"))
    _log({
        "event": "feedback",
        "ref": str(j.get("ref", ""))[:40],
        "useful": j.get("useful"),
        "language": LANGUAGE_NAMES[lang],
        "next_action": str(j.get("next_action", ""))[:200],
        "matched": j.get("matched_id"),
    })
    return {"ok": True}


# One-service hosting: when the React app has been built (frontend/dist), this server also serves it,
# so a single HTTPS address runs the whole app.
@app.get("/", defaults={"path": ""})
@app.get("/<path:path>")
def frontend(path):
    if path.startswith("api/") or not FRONTEND_DIST.is_dir():
        return jsonify(error="not found"), 404
    target = FRONTEND_DIST / path
    if path and target.is_file():
        return send_from_directory(FRONTEND_DIST, path)
    return send_from_directory(FRONTEND_DIST, "index.html")


if __name__ == "__main__":
    # Development server. For a pilot or deployment, run `python serve.py` instead.
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)), debug=False)
