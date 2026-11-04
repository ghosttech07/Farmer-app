"""Gnani AI clients: Prisma (speech-to-text) and Timbre (text-to-speech), per docs.gnani.ai.

- Base URL https://api.vachana.ai, API key in the X-API-Key-ID header (create it at app.gnani.ai/voice).
- Prisma REST:  POST /stt/v3, multipart audio_file + language_code; clips of up to 30 seconds.
- Timbre REST:  POST /api/v1/tts/inference, JSON; the response body is raw WAV audio.
- Evon is not on Gnani's API platform; phrase_with_evon only runs if GNANI_LLM_URL points at an Evon
  deployment you host yourself (OpenAI-compatible chat API).
"""
import base64
import os
import time

import requests

TIMEOUT = 30
RETRY_STATUS = {429, 500, 503, 504}

# Languages Gnani covers (docs.gnani.ai: STT languages, TTS voices).
STT_LANGUAGES = {"bn-IN", "en-IN", "gu-IN", "hi-IN", "kn-IN", "ml-IN", "mr-IN", "pa-IN", "ta-IN", "te-IN"}
TTS_LANGUAGES = STT_LANGUAGES

# Timbre v2.5 voices whose preferred language matches; override all with GNANI_TTS_VOICE.
TTS_VOICES_V25 = {"te-IN": "Lavanya", "hi-IN": "Nalini", "en-IN": "Kaveri"}
TTS_VOICE_V30 = "Lakshmi"  # every Timbre v3.0 voice speaks all ten languages


class GnaniError(Exception):
    """A Gnani API failure with its HTTP status and error type, e.g. 401 INVALID_API_KEY."""

    def __init__(self, status: int, kind: str, message: str):
        super().__init__(f"{status} {kind}: {message}")
        self.status = status
        self.kind = kind


def mock_mode() -> bool:
    return os.getenv("GNANI_MOCK", "0") == "1"


def configured() -> bool:
    return bool(os.getenv("GNANI_API_KEY"))


def _base() -> str:
    return os.getenv("GNANI_BASE_URL", "https://api.vachana.ai").rstrip("/")


def _headers() -> dict:
    return {"X-API-Key-ID": os.getenv("GNANI_API_KEY", "")}


def _error(r: requests.Response) -> GnaniError:
    """Gnani uses three error shapes: {error:{type,message}}, {detail:{error_code,message}} and {message}."""
    kind, message = "HTTP_ERROR", r.text[:200]
    try:
        j = r.json()
    except ValueError:
        return GnaniError(r.status_code, kind, message)
    if isinstance(j.get("error"), dict):
        kind = j["error"].get("type", kind)
        message = j["error"].get("message", message)
    elif isinstance(j.get("detail"), dict):
        kind = j["detail"].get("error_code", kind)
        message = j["detail"].get("message", message)
    elif isinstance(j.get("detail"), list):
        kind, message = "VALIDATION_ERROR", str(j["detail"])[:200]
    else:
        kind = j.get("code", kind)
        message = j.get("message", message)
    return GnaniError(r.status_code, kind, message)


def _post(path: str, **kwargs) -> requests.Response:
    """POST with one retry on rate limits and temporary server errors (Gnani sends no Retry-After)."""
    url = _base() + path
    for attempt in range(2):
        r = requests.post(url, headers={**_headers(), **kwargs.pop("headers", {})}, timeout=TIMEOUT, **kwargs)
        if r.status_code not in RETRY_STATUS or attempt == 1:
            break
        time.sleep(1.5)
    if not r.ok:
        raise _error(r)
    return r


def stt_supports(language: str) -> bool:
    return language in STT_LANGUAGES


def transcribe(wav_bytes: bytes, language: str = "te-IN") -> str:
    """Prisma speech-to-text for a clip of up to 30 seconds. Returns '' when there was no speech."""
    if not stt_supports(language):
        raise GnaniError(400, "UNSUPPORTED_LANGUAGE", f"Prisma does not support {language}")
    data = {"language_code": language}
    model = os.getenv("GNANI_STT_MODEL", "").strip()
    if model:  # empty = Gnani's default, Prisma v2.5
        data["model"] = model
    r = _post("/stt/v3", files={"audio_file": ("audio.wav", wav_bytes, "audio/wav")}, data=data)
    return (r.json().get("transcript") or "").strip()


def synthesize(text: str, language: str = "te-IN") -> str:
    """Timbre text-to-speech. Returns base64 WAV for the browser, or '' for a language Timbre lacks."""
    if language not in TTS_LANGUAGES:
        return ""
    model = os.getenv("GNANI_TTS_MODEL", "timbre-v2.5").strip() or "timbre-v2.5"
    voice = os.getenv("GNANI_TTS_VOICE", "").strip()
    if not voice:
        voice = TTS_VOICE_V30 if model == "timbre-v3.0" else TTS_VOICES_V25.get(language, "Kaveri")
    body = {
        "text": text,
        "model": model,
        "voice": voice,
        "language": language,
        "speed": 1.0,
        "audio_config": {
            "sample_rate": 22050,
            "num_channels": 1,
            "sample_width": 2,
            "encoding": "linear_pcm",
            "container": "wav",
        },
    }
    r = _post("/api/v1/tts/inference", json=body, headers={"Content-Type": "application/json"})
    return base64.b64encode(r.content).decode()


def evon_available() -> bool:
    return bool(os.getenv("GNANI_LLM_URL"))


def phrase_with_evon(system: str, user: str) -> str:
    """Evon chat completion on a self-hosted, OpenAI-compatible deployment (GNANI_LLM_URL)."""
    r = requests.post(
        os.environ["GNANI_LLM_URL"],
        headers={"Authorization": f"Bearer {os.getenv('GNANI_LLM_KEY', '')}"},
        json={
            "model": os.getenv("GNANI_LLM_MODEL", "evon-v3.3"),
            "temperature": 0.1,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        },
        timeout=TIMEOUT,
    )
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"].strip()
