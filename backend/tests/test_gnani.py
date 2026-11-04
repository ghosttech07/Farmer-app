"""Gnani client tests against fake responses shaped like docs.gnani.ai; no network, no credits."""
import base64
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import gnani  # noqa: E402


class FakeResponse:
    def __init__(self, status=200, json_body=None, content=b"", content_type="application/json"):
        self.status_code = status
        self.ok = 200 <= status < 300
        self._json = json_body
        self.content = content
        self.headers = {"content-type": content_type}
        self.text = str(json_body) if json_body is not None else content.decode("latin-1")

    def json(self):
        if self._json is None:
            raise ValueError("not json")
        return self._json


@pytest.fixture
def calls(monkeypatch):
    monkeypatch.setenv("GNANI_API_KEY", "test-key")
    monkeypatch.delenv("GNANI_BASE_URL", raising=False)
    monkeypatch.delenv("GNANI_STT_MODEL", raising=False)
    monkeypatch.delenv("GNANI_TTS_MODEL", raising=False)
    monkeypatch.delenv("GNANI_TTS_VOICE", raising=False)
    monkeypatch.setattr(gnani.time, "sleep", lambda s: None)
    log = {"requests": [], "responses": []}

    def fake_post(url, **kwargs):
        log["requests"].append((url, kwargs))
        return log["responses"].pop(0)

    monkeypatch.setattr(gnani.requests, "post", fake_post)
    return log


def test_transcribe_sends_documented_request(calls):
    calls["responses"].append(FakeResponse(json_body={"success": True, "request_id": "r1", "transcript": " పత్తి పురుగు ", "model": "prisma-v2.5"}))
    assert gnani.transcribe(b"RIFF....", "te-IN") == "పత్తి పురుగు"
    url, kw = calls["requests"][0]
    assert url == "https://api.vachana.ai/stt/v3"
    assert kw["headers"]["X-API-Key-ID"] == "test-key"
    assert kw["files"]["audio_file"][0] == "audio.wav"
    assert kw["data"] == {"language_code": "te-IN"}  # no model = Prisma v2.5 default


def test_transcribe_uses_chosen_model(calls, monkeypatch):
    monkeypatch.setenv("GNANI_STT_MODEL", "prisma-v3.0")
    calls["responses"].append(FakeResponse(json_body={"success": True, "transcript": "", "model": "prisma-v3.0"}))
    assert gnani.transcribe(b"x", "hi-IN") == ""
    assert calls["requests"][0][1]["data"] == {"language_code": "hi-IN", "model": "prisma-v3.0"}


def test_unsupported_language_is_not_sent_to_prisma(calls):
    with pytest.raises(gnani.GnaniError) as e:
        gnani.transcribe(b"x", "fr-FR")
    assert e.value.kind == "UNSUPPORTED_LANGUAGE"
    assert calls["requests"] == []
    assert gnani.synthesize("bonjour", "fr-FR") == ""


def test_synthesize_returns_base64_wav_with_language_voice(calls):
    wav = b"RIFF\x24\x00\x00\x00WAVEfmt "
    calls["responses"].append(FakeResponse(content=wav, content_type="audio/wav"))
    assert base64.b64decode(gnani.synthesize("నమస్కారం", "te-IN")) == wav
    url, kw = calls["requests"][0]
    assert url == "https://api.vachana.ai/api/v1/tts/inference"
    body = kw["json"]
    assert body["model"] == "timbre-v2.5" and body["voice"] == "Lavanya" and body["language"] == "te-IN"
    assert body["audio_config"]["container"] == "wav" and body["audio_config"]["encoding"] == "linear_pcm"
    assert kw["headers"]["X-API-Key-ID"] == "test-key"


def test_hindi_and_english_voices_and_v3(calls, monkeypatch):
    calls["responses"] += [FakeResponse(content=b"a", content_type="audio/wav"), FakeResponse(content=b"b", content_type="audio/wav")]
    gnani.synthesize("नमस्ते", "hi-IN")
    assert calls["requests"][0][1]["json"]["voice"] == "Nalini"
    monkeypatch.setenv("GNANI_TTS_MODEL", "timbre-v3.0")
    gnani.synthesize("hello", "en-IN")
    assert calls["requests"][1][1]["json"]["voice"] == "Lakshmi"


@pytest.mark.parametrize(
    "status, body, kind",
    [
        (400, {"success": False, "error": {"type": "MAX_AUDIO_DURATION_EXCEEDED", "message": "too long"}}, "MAX_AUDIO_DURATION_EXCEEDED"),
        (401, {"detail": {"error_code": "INVALID_API_KEY", "message": "bad key", "status_code": 401}}, "INVALID_API_KEY"),
        (422, {"detail": [{"loc": ["body", "language_code"], "msg": "field required"}]}, "VALIDATION_ERROR"),
        (402, {"success": False, "message": "Insufficient credit", "status_code": 402}, "HTTP_ERROR"),
    ],
)
def test_error_shapes_are_read(calls, status, body, kind):
    calls["responses"].append(FakeResponse(status=status, json_body=body))
    with pytest.raises(gnani.GnaniError) as e:
        gnani.transcribe(b"x", "te-IN")
    assert e.value.status == status and e.value.kind == kind


def test_retries_once_on_temporary_failure(calls):
    calls["responses"] += [
        FakeResponse(status=503, json_body={"success": False, "error": {"type": "SERVICE_UNAVAILABLE", "message": "busy"}}),
        FakeResponse(json_body={"success": True, "transcript": "ok"}),
    ]
    assert gnani.transcribe(b"x", "en-IN") == "ok"
    assert len(calls["requests"]) == 2


def test_evon_only_when_self_hosted(monkeypatch):
    monkeypatch.delenv("GNANI_LLM_URL", raising=False)
    assert gnani.evon_available() is False
    monkeypatch.setenv("GNANI_LLM_URL", "http://localhost:8000/v1/chat/completions")
    assert gnani.evon_available() is True
