import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import advice  # noqa: E402
import matcher  # noqa: E402

KB = matcher.load_kb()


def m(text):
    return matcher.match(text, KB)


def test_rice_blast_strong():
    r = m("నా వరి పొలంలో అగ్గి తెగులు వచ్చింది, ఆకులపై కంటి ఆకారపు మచ్చలు ఉన్నాయి")
    assert r["status"] == "strong" and r["entry"]["id"] == "rice_blast"


def test_cotton_pink_bollworm():
    r = m("పత్తి కాయల్లో గులాబీ రంగు పురుగు ఉంది")
    assert r["status"] == "strong" and r["entry"]["id"] == "cotton_pink_bollworm"


def test_fall_armyworm_mixed_english():
    r = m("మొక్కజొన్నలో కత్తెర పురుగు, whorl లో మలం కనిపిస్తోంది")
    assert r["status"] == "strong" and r["entry"]["id"] == "maize_faw"


def test_leaf_curl_disambiguated_by_crop():
    assert m("మిరప ఆకులు ముడుచుకుపోతున్నాయి, తామర పురుగులు")["entry"]["id"] == "chilli_thrips"
    assert m("పత్తి ఆకులు ముడుచుకుంటున్నాయి తెల్ల దోమ")["entry"]["id"] == "cotton_whitefly"


def test_vague_is_not_strong():
    r = m("నా పంట బాగా లేదు")
    assert r["status"] == "none"
    out = advice.build(r, KB)
    assert out["status"] == "escalate" and "1800" in out["answer_en"]


def test_single_weak_clue_asks_followup_once():
    r = m("వరి ఆకులపై మచ్చలు ఉన్నాయి")
    assert r["status"] == "ambiguous"
    assert advice.build(r, KB, can_ask_followup=True)["followup"] is True
    assert advice.build(r, KB, can_ask_followup=False)["status"] == "escalate"


def test_evon_guard_rejects_invented_dose():
    e = next(x for x in KB["entries"] if x["id"] == "rice_blast")
    good = "Tricyclazole 0.6 గ్రాములు లీటరుకు, 30 రోజులు ఆగండి"
    bad = "Tricyclazole 2 గ్రాములు లీటరుకు, 30 రోజులు ఆగండి"
    missing = "ఈ మందు వాడండి 0.6 గ్రాములు 30 రోజులు"
    assert advice.evon_is_faithful(good, e)
    assert not advice.evon_is_faithful(bad, e)
    assert not advice.evon_is_faithful(missing, e)


def test_every_entry_has_required_fields():
    for e in KB["entries"]:
        for k in ("name_te", "cause_te", "treatment", "waiting_days", "followup_te", "source"):
            assert e.get(k), (e["id"], k)
        assert e["treatment"]["dose_te"] and e["treatment"]["dose_per_litre"]


def test_strong_answer_exposes_card_fields():
    out = advice.build(m("పత్తి కాయల్లో గులాబీ రంగు పురుగు ఉంది"), KB)
    assert out["crop_en"] == "Cotton" and out["crop"] == "పత్తి" and out["lang"] == "te"
    for k in ("name", "name_en", "cause", "cause_en", "source", "answer"):
        assert out[k], k
    assert out["treatment"]["dose_local"]


def test_hindi_description_matches():
    r = m("मेरे कपास के टिंडे में गुलाबी सुंडी है")
    assert r["status"] == "strong" and r["entry"]["id"] == "cotton_pink_bollworm"
    out = advice.build(r, KB, lang="hi")
    assert out["crop"] == "कपास" and "2" in out["treatment"]["dose_local"] and "20" in out["answer"]


def test_every_entry_has_hindi_with_same_numbers():
    for e in KB["entries"]:
        for lang in ("hi",):
            for k in ("name", "cause", "dose", "followup"):
                assert e["i18n"][lang].get(k), (e["id"], lang, k)
            assert advice._numbers(e["i18n"][lang]["dose"]) - {"1"} == advice._numbers(e["treatment"]["dose_te"]) - {"1"}, (e["id"], lang)  # "1 litre" vs "one litre"
            assert advice.evon_is_faithful(advice.template_answer(e, lang), e, lang), (e["id"], lang)


def test_unknown_language_falls_back_to_telugu():
    assert advice.build(m("నా పంట బాగా లేదు"), KB, lang="xx")["lang"] == "te"


def test_followup_yes_confirms_entry(monkeypatch, tmp_path):
    monkeypatch.setenv("GNANI_MOCK", "1")
    import app as server
    monkeypatch.setattr(server, "LOG", tmp_path / "log.jsonl")
    c = server.app.test_client()
    r = c.post("/api/advise", data={"confirm_id": "rice_blast", "context": "వరి ఆకులపై మచ్చలు"}).get_json()
    assert r["status"] == "strong" and r["matched_id"] == "rice_blast" and r["crop_en"] == "Rice"
    assert c.post("/api/advise", data={"confirm_id": "nope"}).status_code == 400


def test_block_unverified_sends_draft_entries_to_the_officer():
    r = m("పత్తి కాయల్లో గులాబీ రంగు పురుగు ఉంది")
    assert advice.build(r, KB)["status"] == "strong"
    assert advice.build(r, KB)["verified"] is False
    assert advice.build(r, KB, block_unverified=True)["status"] == "escalate"


def _client(monkeypatch, tmp_path, **env):
    monkeypatch.setenv("GNANI_MOCK", "1")
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    import app as server
    monkeypatch.setattr(server, "LOG", tmp_path / "log.jsonl")
    server._hits.clear()
    return server, server.app.test_client()


def test_advise_returns_reference_and_logs_pilot_fields(monkeypatch, tmp_path):
    import json
    server, c = _client(monkeypatch, tmp_path)
    r = c.post("/api/advise", data={"text": "मेरे कपास के टिंडे में गुलाबी सुंडी है", "lang": "hi", "input": "Typed"}).get_json()
    assert r["ref"].startswith("PS-") and r["status"] == "strong"
    c.post("/api/feedback", json={"useful": True, "ref": r["ref"], "lang": "hi"})
    rows = [json.loads(l) for l in (tmp_path / "log.jsonl").read_text(encoding="utf-8").splitlines()]
    assert rows[0]["language"] == "Hindi" and rows[0]["outcome"] == "Answered" and rows[0]["input"] == "Typed"
    assert rows[1]["event"] == "feedback" and rows[1]["ref"] == r["ref"]


def test_block_unverified_setting_applies_to_api(monkeypatch, tmp_path):
    server, c = _client(monkeypatch, tmp_path, BLOCK_UNVERIFIED="1")
    r = c.post("/api/advise", data={"text": "పత్తి కాయల్లో గులాబీ రంగు పురుగు ఉంది"}).get_json()
    assert r["status"] == "escalate"


def test_rate_limit_and_text_limit(monkeypatch, tmp_path):
    server, c = _client(monkeypatch, tmp_path)
    monkeypatch.setattr(server, "RATE_LIMIT_PER_MIN", 2)
    assert c.post("/api/advise", data={"text": "x" * 501}).status_code == 413
    assert c.post("/api/advise", data={"text": "spots"}).status_code == 200
    assert c.post("/api/advise", data={"text": "spots"}).status_code == 429


def test_serves_built_frontend(monkeypatch, tmp_path):
    server, c = _client(monkeypatch, tmp_path)
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<p>app</p>", encoding="utf-8")
    monkeypatch.setattr(server, "FRONTEND_DIST", dist)
    assert c.get("/").data == b"<p>app</p>"
    assert c.get("/result").data == b"<p>app</p>"  # client-side routes fall back to the app
    assert c.get("/api/nope").status_code == 404


def test_pilot_report_summarises(tmp_path, capsys):
    import json
    import pilot_report
    log = tmp_path / "log.jsonl"
    log.write_text("\n".join(json.dumps(r) for r in [
        {"event": "advise", "ts": "2026-11-04T10:00:00", "outcome": "Answered", "language": "Telugu", "input": "Voice", "problem": "Aphids"},
        {"event": "feedback", "useful": True, "ref": "PS-1", "next_action": "Sprayed neem oil"},
    ]), encoding="utf-8")
    import sys
    sys.argv = ["pilot_report.py", str(log)]
    pilot_report.main()
    out = capsys.readouterr().out
    assert "Consultations: 1" in out and "helpful 1 (100%)" in out and "Sprayed neem oil" in out


def test_health_lists_gnani_voice_languages(monkeypatch, tmp_path):
    server, c = _client(monkeypatch, tmp_path)
    assert c.get("/api/health").get_json()["stt_languages"] == ["te", "hi", "en"]


def _entry(i):
    return next(e for e in KB["entries"] if e["id"] == i)


def test_waiting_period_follows_the_farmers_crop():
    e = _entry("fruit_borer")
    strong = lambda crops: advice.build({"status": "strong", "entry": e, "candidates": [e["id"]], "crops": crops}, KB)
    assert strong(["tomato"])["treatment"]["waiting_days"] == 3
    assert strong(["pulses"])["treatment"]["waiting_days"] == 29
    unknown = strong([])
    assert unknown["treatment"]["waiting_days"] == 29 and unknown["crop_id"] is None  # crop not said: longest wait
    assert "29" in unknown["answer"] and "29" not in strong(["tomato"])["answer"]


def test_every_entry_cites_the_cibrc_row():
    for e in KB["entries"]:
        official = e["sources"][0]  # the treatment row; later sources (TNAU symptoms) are extra
        assert official["url"].startswith("https://ppqs.gov.in/") and official["row"] and official["page"], e["id"]
        assert e["verified"] is False  # only an agriculture officer may flip this


def test_answer_switches_language_with_same_facts(monkeypatch, tmp_path):
    server, c = _client(monkeypatch, tmp_path)
    te = c.post("/api/advise", data={"confirm_id": "fruit_borer", "context": "టమాటా కాయల్లో పురుగు", "lang": "te"}).get_json()
    assert te["status"] == "strong" and te["crop_id"] == "tomato" and te["treatment"]["waiting_days"] == 3
    for lang in ("hi", "en", "te"):
        r = c.post("/api/answer", json={"kind": "strong", "matched_id": te["matched_id"], "crop": te["crop_id"],
                                        "lang": lang, "ref": te["ref"]}).get_json()
        assert r["lang"] == lang and r["ref"] == te["ref"] and r["matched_id"] == te["matched_id"]
        assert r["treatment"]["waiting_days"] == te["treatment"]["waiting_days"]
        assert r["treatment"]["per_litre"] == te["treatment"]["per_litre"] and "audio_base64" in r
    hi = c.post("/api/answer", json={"kind": "strong", "matched_id": te["matched_id"], "crop": te["crop_id"], "lang": "hi"}).get_json()
    assert hi["crop"] == "टमाटर"


def test_followup_and_escalation_switch_language(monkeypatch, tmp_path):
    server, c = _client(monkeypatch, tmp_path)
    f = c.post("/api/answer", json={"kind": "followup", "matched_id": "rice_blast", "lang": "hi"}).get_json()
    assert f["followup"] and f["answer"] == _entry("rice_blast")["i18n"]["hi"]["followup"]
    x = c.post("/api/answer", json={"kind": "escalate", "lang": "en"}).get_json()
    assert x["status"] == "escalate" and x["answer"] == advice.ESCALATE["en"]
    assert c.post("/api/answer", json={"kind": "strong", "matched_id": "nope", "lang": "hi"}).status_code == 400
    assert c.post("/api/answer", json={"kind": "bogus", "lang": "hi"}).status_code == 400


def test_english_speech_slips_still_match():
    # exactly what Gnani Prisma returned for "pink bollworm inside my cotton bolls" on 04.11.2026
    assert m("pink ballworm inside my cotton bowls")["entry"]["id"] == "cotton_pink_bollworm"
    assert m("pink ballworm inside my cotton bowls")["status"] == "strong"


def test_english_fuzzy_matching_is_tolerant_but_not_loose():
    assert m("pink bowlworm inside my cotton bowls")["entry"]["id"] == "cotton_pink_bollworm"  # Prisma, 2nd try
    assert m("army worm eating my maize whorl")["entry"]["id"] == "maize_faw"
    assert m("strips on my chilli leaves")["status"] != "strong"  # 'strips' must not become thrips


def test_knowledge_base_matches_official_cibrc_rows():
    import audit_kb
    assert audit_kb.audit() == []


def test_strong_answer_lists_other_registered_sprays_only_for_a_known_crop():
    e = next(x for x in KB["entries"] if x["id"] == "maize_faw")
    out = advice.build({"status": "strong", "entry": e, "candidates": [e["id"]], "crops": ["maize"]}, KB)
    assert out["options"] and all(o["url"].startswith("https://ppqs.gov.in/") and o["per_litre"] for o in out["options"])
    assert not any(registry_same(o["product"], e["treatment"]["product"]) for o in out["options"])
    fb = next(x for x in KB["entries"] if x["id"] == "fruit_borer")  # several crops, none said: no options
    assert advice.build({"status": "strong", "entry": fb, "candidates": [fb["id"]], "crops": []}, KB)["options"] == []


def registry_same(a, b):
    import registry
    return registry.same_product(a, b)



def test_answer_voice_comes_from_gnani_in_the_chosen_language(monkeypatch, tmp_path):
    server, c = _client(monkeypatch, tmp_path, GNANI_MOCK="0", GNANI_API_KEY="k")
    spoken = []
    monkeypatch.setattr(server.gnani, "synthesize", lambda text, code: spoken.append(code) or "UklGRg==")
    for lang in ("te", "hi", "en"):
        r = c.post("/api/answer", json={"kind": "followup", "matched_id": "rice_blast", "lang": lang}).get_json()
        assert r["audio_base64"] == "UklGRg==" and r["lang"] == lang
    assert spoken == ["te-IN", "hi-IN", "en-IN"]


def test_odia_is_gone():
    import re
    import app as server
    assert advice.LANGS == ("te", "hi", "en") and "or" not in server.SPEECH_CODES
    assert advice.lang_or_default("or") == "te"  # an old link asking for Odia gets Telugu
    assert not re.search("[଀-୿]", json.dumps(KB, ensure_ascii=False))


def test_broad_question_asks_crop_then_offers_problems_then_answers(monkeypatch, tmp_path):
    server, c = _client(monkeypatch, tmp_path)
    q = c.post("/api/advise", data={"text": "నా మొక్కకు గొంగళి పురుగులు ఉన్నాయి ఏం చేయాలి", "lang": "te"}).get_json()
    assert q["status"] == "choose" and q["choose"] == "crop" and len(q["choices"]) == len(KB["crops"])
    p = c.post("/api/advise", data={"crop": "tomato", "context": q["context"], "lang": "te"}).get_json()
    assert p["status"] == "choose" and p["choose"] == "problem"
    ids = [x["id"] for x in p["choices"]]
    assert "fruit_borer" in ids and "tomato_early_blight" not in ids  # caterpillars: no diseases offered
    a = c.post("/api/advise", data={"confirm_id": "fruit_borer", "context": p["context"], "lang": "te"}).get_json()
    assert a["status"] == "strong" and a["crop_en"] == "Tomato" and a["treatment"]["waiting_days"] == 3


def test_every_broad_question_gets_choices_not_a_dead_end(monkeypatch, tmp_path):
    server, c = _client(monkeypatch, tmp_path)
    for text, lang in [("मेरे पौधे पर कीड़े हैं क्या करूँ", "hi"), ("my plants are dying", "en"),
                       ("my cotton has a disease", "en"), ("చెరకు పంటకు పురుగు పట్టింది", "te")]:
        r = c.post("/api/advise", data={"text": text, "lang": lang}).get_json()
        assert r["status"] == "choose" and r["choices"] and r["answer"], text


def test_no_to_the_yes_no_question_offers_the_crops_problems(monkeypatch, tmp_path):
    server, c = _client(monkeypatch, tmp_path)
    f = c.post("/api/advise", data={"text": "వరి ఆకుల మీద మచ్చలు వచ్చాయి", "lang": "te"}).get_json()
    assert f["followup"]
    g = c.post("/api/advise", data={"guide": "1", "context": f["context"], "reject": f["matched_id"], "lang": "te"}).get_json()
    assert g["status"] == "choose" and g["choose"] == "problem" and g["crop_id"] == "rice"


def test_choices_switch_language(monkeypatch, tmp_path):
    server, c = _client(monkeypatch, tmp_path)
    r = c.post("/api/answer", json={"kind": "choose", "context": "tomato caterpillar", "crop": "tomato", "lang": "hi"}).get_json()
    assert r["status"] == "choose" and r["lang"] == "hi" and "टमाटर" in r["answer"]
