import { createContext, useContext, useEffect, useRef, useState } from "react";
import { toWav16k } from "./wav.js";
import * as Icon from "./icons.jsx";
import { LANGS, SPEECH, S, T } from "./strings.js";

const KCC = "1800-180-1551";
const MAX_SECS = 30; // auto-stop; Gnani speech-to-text takes clips of up to 30 seconds per request
const MIN_MS = 1200; // shorter than this is almost always an accidental tap
const SILENT_RMS = 0.012; // loudest moment below this = we heard nothing worth sending
const SR = window.SpeechRecognition || window.webkitSpeechRecognition;

const Lang = createContext("te");

// The chosen language first, English beneath it (nothing beneath when English is chosen).
function useText(t) {
  const lang = useContext(Lang);
  const main = t[lang] ? [t[lang], lang] : [t.en, "en"];
  const sub = main[1] !== "en" && t.en ? [t.en, "en"] : null;
  return [main, sub];
}

// Text that came back from the API: in the language it was asked in, plus English.
const fromApi = (res, local, en) => ({ [res.lang || "te"]: local, en });

function Bi({ t, className = "", as: Tag = "div", id, ...rest }) {
  const [[a, la], sub] = useText(t);
  return (
    <div className={`bi ${className}`} {...rest}>
      <Tag className="pri" lang={la} id={id}>{a}</Tag>
      {sub && <div className="sec" lang={sub[1]}>{sub[0]}</div>}
    </div>
  );
}

// Control label: the chosen language, English a step smaller beneath it.
function J({ t }) {
  const [[a, la], sub] = useText(t);
  return (
    <span className="j">
      <span className="j1" lang={la}>{a}</span>
      {sub && <span className="j2" lang={sub[1]}>{sub[0]}</span>}
    </span>
  );
}

const Spinner = () => <span className="spinner" aria-hidden="true" />;

function Steps({ step, alert }) {
  const lang = useContext(Lang);
  return (
    <div className="steps" role="img" aria-label={S.step[lang].replace("{n}", step)}>
      {[1, 2, 3].map((n) => (
        <span key={n} className={n === 3 && alert ? "alert" : n <= step ? "on" : ""} />
      ))}
    </div>
  );
}

function TopBar({ onBack, backLabel = S.back, step, alert, right }) {
  const lang = useContext(Lang);
  return (
    <header className="bar">
      <button type="button" className="key key--icon" onClick={onBack} aria-label={backLabel[lang]}><Icon.Back size={20} /></button>
      <Steps step={step} alert={alert} />
      {right || <span className="spacer" />}
    </header>
  );
}

const mmss = (s) => `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;

function savedLang() {
  try {
    const saved = localStorage.getItem("lang");
    return SPEECH[saved] ? saved : "te";
  } catch {
    return "te";
  }
}

export default function App() {
  const [lang, setLang] = useState(savedLang);
  const [screen, setScreen] = useState("home"); // home | listen | confirm | result | escalate
  const [phase, setPhase] = useState("rec"); // rec | busy (while on the listen screen)
  const [voice, setVoice] = useState("server"); // server (Gnani STT) | browser (Web Speech, mock mode) | none
  const [sttLangs, setSttLangs] = useState(null); // languages Gnani can transcribe; null until the health check answers
  const [res, setRes] = useState(null);
  const [error, setError] = useState(null);
  const [rated, setRated] = useState(null);
  const [secs, setSecs] = useState(0);
  const [heard, setHeard] = useState("");
  const [sun, setSun] = useState(false);
  const [how, setHow] = useState(false);
  const [typed, setTyped] = useState(false); // confirm screen used as a text box (no recording)
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [langOpen, setLangOpen] = useState(false);
  const [blocked, setBlocked] = useState(false); // browser refused to autoplay the spoken answer // language choices under the answer screen's language key
  const [declined, setDeclined] = useState(false);
  const [metered, setMetered] = useState(false); // live mic levels drive the bars
  const recorder = useRef(null);
  const chunks = useRef([]);
  const cancelled = useRef(false);
  const startedAt = useRef(0);
  const meter = useRef(null); // { ctx, raf, peak }
  const bars = useRef([]);
  const heardRef = useRef("");
  const context = useRef("");
  const player = useRef(null);
  const officer = useRef(null);
  const main = useRef(null);
  const back = useRef(() => {});
  const pushed = useRef(false);
  const firstRender = useRef(true);

  useEffect(() => {
    fetch("/api/health")
      .then((r) => r.json())
      .then((j) => {
        if (j.mock) setVoice(SR ? "browser" : "none");
        if (Array.isArray(j.stt_languages)) setSttLangs(j.stt_languages);
      })
      .catch(() => {});
  }, []);

  useEffect(() => {
    document.documentElement.lang = lang;
    document.title = lang === "en" ? "Pantha Sahayam" : `${S.appName[lang]} (Pantha Sahayam)`;
    try {
      localStorage.setItem("lang", lang);
    } catch {}
  }, [lang]);

  useEffect(() => {
    if (screen !== "listen" || phase !== "rec") return;
    if (secs >= MAX_SECS) return stopRec();
    const id = setTimeout(() => setSecs((s) => s + 1), 1000);
    return () => clearTimeout(id);
  }, [screen, phase, secs]);

  // Move focus to the new screen's heading so screen readers and keyboards follow along.
  useEffect(() => {
    if (firstRender.current) return void (firstRender.current = false);
    main.current?.querySelector("[data-focus]")?.focus();
    window.scrollTo(0, 0);
  }, [screen]);

  // The phone's back button steps back inside the app instead of leaving it.
  useEffect(() => {
    if (screen !== "home" && !pushed.current) {
      history.pushState({ app: 1 }, "");
      pushed.current = true;
    }
  }, [screen]);
  useEffect(() => {
    const onPop = () => {
      pushed.current = false;
      back.current();
    };
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  function begin() {
    setError(null);
    stopAudio();
    setSecs(0);
    setHeard("");
    heardRef.current = "";
    cancelled.current = false;
    startedAt.current = Date.now();
    setPhase("rec");
    setScreen("listen");
  }

  async function start() {
    if (voice === "none") return typeInstead(T.mic);
    if (voice === "browser") return startBrowser();
    // A language Gnani cannot transcribe: use the phone's own recognition, or ask the farmer to type.
    if (sttLangs && !sttLangs.includes(lang)) return SR ? startBrowser() : typeInstead(T.noVoiceLang);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: { noiseSuppression: true, echoCancellation: true },
      });
      const rec = new MediaRecorder(stream);
      chunks.current = [];
      rec.ondataavailable = (e) => chunks.current.push(e.data);
      rec.onstop = () => {
        stream.getTracks().forEach((t) => t.stop());
        const peak = stopMeter();
        if (cancelled.current) return;
        if (Date.now() - startedAt.current < MIN_MS) return fail(T.short);
        if (peak < SILENT_RMS) return fail(T.empty);
        send(new Blob(chunks.current, { type: rec.mimeType }));
      };
      recorder.current = rec;
      begin();
      rec.start();
      startMeter(stream);
    } catch {
      typeInstead(T.mic);
    }
  }

  // Mock mode (no Gnani credits): let the browser's own speech recognition produce the transcript.
  function startBrowser() {
    const r = new SR();
    r.lang = SPEECH[lang];
    r.interimResults = true;
    r.continuous = true;
    let final = "";
    let denied = false;
    r.onresult = (e) => {
      let interim = "";
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const t = e.results[i][0].transcript;
        if (e.results[i].isFinal) final += t + " ";
        else interim += t;
      }
      heardRef.current = (final + interim).trim();
      setHeard(heardRef.current);
    };
    r.onerror = (e) => {
      denied = e.error === "not-allowed" || e.error === "service-not-allowed";
    };
    r.onend = () => {
      if (cancelled.current) return;
      if (denied) return typeInstead(T.mic);
      if (!heardRef.current) return fail(T.empty);
      sendText(heardRef.current);
    };
    recorder.current = r;
    begin();
    r.start();
  }

  function startMeter(stream) {
    try {
      const ctx = new (window.AudioContext || window.webkitAudioContext)();
      const an = ctx.createAnalyser();
      an.fftSize = 256;
      ctx.createMediaStreamSource(stream).connect(an);
      const freq = new Uint8Array(an.frequencyBinCount);
      const wave = new Uint8Array(an.fftSize);
      const m = { ctx, raf: 0, peak: 0 };
      const tick = () => {
        an.getByteFrequencyData(freq);
        an.getByteTimeDomainData(wave);
        let sum = 0;
        for (const v of wave) sum += ((v - 128) / 128) ** 2;
        m.peak = Math.max(m.peak, Math.sqrt(sum / wave.length));
        bars.current.forEach((el, i) => {
          if (el) el.style.transform = `scaleY(${0.18 + (freq[2 + i * 2] / 255) * 0.82})`;
        });
        m.raf = requestAnimationFrame(tick);
      };
      tick();
      meter.current = m;
      setMetered(true);
    } catch {
      meter.current = null; // no meter: bars fall back to the CSS animation, silence check is skipped
    }
  }

  function stopMeter() {
    const m = meter.current;
    meter.current = null;
    setMetered(false);
    if (!m) return 1;
    cancelAnimationFrame(m.raf);
    m.ctx.close();
    return m.peak;
  }

  function stopRec() {
    if (recorder.current?.state === "recording" || voice === "browser") recorder.current?.stop();
  }

  function cancel() {
    cancelled.current = true;
    stopRec();
    stopMeter();
    setScreen("home");
  }

  function fail(msg) {
    setError(msg);
    setScreen("home");
  }

  function typeInstead(msg = null) {
    stopAudio();
    setError(msg);
    setRes(null);
    setTyped(true);
    setEditing(true);
    setDraft("");
    setScreen("confirm");
  }

  async function ask(fields) {
    const fd = new FormData();
    Object.entries({ lang, ...fields }).forEach(([k, v]) => fd.append(k, v));
    const r = await fetch("/api/advise", { method: "POST", body: fd });
    const j = await r.json();
    if (!r.ok) throw Object.assign(new Error(j.error || "failed"), { empty: j.status === "empty" });
    return j;
  }

  async function send(blob) {
    setPhase("busy");
    try {
      const wav = await toWav16k(blob);
      toConfirm(await ask({ audio: new File([wav], "audio.wav"), context: context.current, input: "Voice" }));
    } catch (e) {
      fail(e.empty ? T.empty : T.err);
    }
  }

  async function sendText(text) {
    setPhase("busy");
    try {
      toConfirm(await ask({ text, context: context.current, input: "Voice" }));
    } catch (e) {
      fail(e.empty ? T.empty : T.err);
    }
  }

  function toConfirm(j) {
    setRes(j);
    setLangOpen(false);
    setDraft(j.transcript);
    setTyped(false);
    setEditing(false);
    setScreen("confirm");
  }

  // Farmer confirmed (or typed) the words: ask again only when the text changed, then show the outcome.
  async function confirm() {
    const text = draft.trim();
    const unchanged = !typed && !(editing && text && text !== res.transcript);
    if (unchanged && res.lang === lang) return show(res);
    if (!text) return;
    setBusy(true);
    setError(null);
    try {
      // language changed on this screen: the same answer in the chosen language
      show(unchanged ? await answerIn(res, lang) : await ask({ text, context: context.current, input: "Typed" }));
    } catch (e) {
      setError(e.empty ? T.empty : T.err);
    }
    setBusy(false);
  }

  async function followYes() {
    setBusy(true);
    try {
      show(await ask({ confirm_id: res.matched_id, context: res.context }));
    } catch {
      setError(T.err);
    }
    setBusy(false);
  }

  // "No" to the yes/no question: offer that crop's problems (or ask the crop) before sending to the officer.
  async function followNo() {
    if (res.followup) {
      setBusy(true);
      try {
        const j = await ask({ guide: "1", context: res.context, reject: res.matched_id || "" });
        setBusy(false);
        if (j.status === "choose") return show(j);
      } catch {
        setBusy(false);
      }
    }
    toOfficer();
  }

  // A crop or problem button was tapped: narrow down, or get the full answer.
  async function choose(c) {
    setBusy(true);
    setError(null);
    try {
      show(await ask(res.choose === "crop" ? { crop: c.id, context: res.context, input: "Typed" }
        : { confirm_id: c.id, context: res.context, input: "Typed" }));
    } catch {
      setError(T.err);
    }
    setBusy(false);
  }

  function toOfficer() {
    setDeclined(true);
    context.current = "";
    requestAnimationFrame(() => {
      officer.current?.scrollIntoView({ behavior: "smooth", block: "center" });
      officer.current?.querySelector("a")?.focus({ preventScroll: true });
    });
  }

  function show(j) {
    context.current = j.followup || j.status === "choose" ? j.context : "";
    setRes(j);
    setTyped(false);
    setRated(null);
    setDeclined(false);
    setError(null);
    setLangOpen(false);
    setScreen(j.status === "strong" ? "result" : "escalate");
    speak(j);
  }

  // Gnani's Timbre audio when we have it; otherwise the phone's own Telugu voice.
  function speak(j) {
    stopAudio();
    if (j.audio_base64) {
      player.current.src = "data:audio/wav;base64," + j.audio_base64;
      // a browser that blocks autoplay gets a clear "listen" key instead of silence
      player.current.play().then(() => setBlocked(false), () => setBlocked(true));
    } else if (window.speechSynthesis) {
      const u = new SpeechSynthesisUtterance(j.answer);
      u.lang = SPEECH[j.lang] || "te-IN";
      speechSynthesis.speak(u);
    }
  }

  // The same answer (text and voice) in another language, keeping what the farmer said and the follow-up context.
  async function answerIn(base, code) {
    const kind = base.status === "choose" ? "choose" : base.followup ? "followup" : base.status === "strong" ? "strong" : "escalate";
    const r = await fetch("/api/answer", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ kind, matched_id: base.matched_id, crop: base.crop_id, lang: code, ref: base.ref,
        context: base.context, candidates: base.candidates }),
    });
    const j = await r.json();
    if (!r.ok) throw new Error(j.error || "failed");
    return { ...j, transcript: base.transcript, context: base.context, followup: base.followup && j.followup };
  }

  // Language key: on the answer screens it re-reads the answer at once; on the "You said" screen it
  // only chooses the answer language, used when the farmer confirms.
  async function relang(code) {
    if (busy) return;
    if (screen === "confirm") {
      setLang(code);
      setLangOpen(false);
      return;
    }
    if (code === res.lang) return;
    setLang(code);
    setBusy(true);
    setError(null);
    stopAudio();
    try {
      const j = await answerIn(res, code);
      setRes(j);
      setLangOpen(false);
      speak(j);
    } catch {
      setError(T.err);
    }
    setBusy(false);
  }

  function stopAudio() {
    player.current?.pause();
    window.speechSynthesis?.cancel();
  }

  function rate(useful) {
    setRated(useful);
    fetch("/api/feedback", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ useful, matched_id: res?.matched_id, ref: res?.ref, lang: res?.lang }),
    }).catch(() => {});
  }

  function again() {
    stopAudio();
    context.current = "";
    setRes(null);
    setError(null);
    setScreen("home");
  }

  function backToConfirm() {
    stopAudio();
    setError(null);
    setScreen("confirm");
  }

  back.current = { home: () => {}, listen: cancel, confirm: again, result: backToConfirm, escalate: backToConfirm }[screen];

  const canSpeak = !!res?.audio_base64 || !!window.speechSynthesis;
  const callPrimary = !((res?.followup || res?.status === "choose") && !declined);
  // "2 ml" -> ["2", "ml"]; older backends only send "2 ml per litre"
  const perLitre = (res?.treatment?.per_litre || res?.treatment?.dose?.replace(/ per litre$/, "") || "").split(" ");
  const listenKey = (
    <button type="button" className={`replay${blocked ? " replay--nudge" : ""}`} onClick={() => speak(res)} disabled={!canSpeak}>
      <Icon.Speaker size={20} /> <J t={S.replay} />
    </button>
  );
  const langKey = (
    <button type="button" className="key key--icon" aria-label={S.language[lang]} aria-expanded={langOpen}
      aria-controls="answer-langs" aria-pressed={langOpen} onClick={() => setLangOpen(!langOpen)}>
      {busy ? <Spinner /> : <Icon.Language size={20} />}
    </button>
  );
  const answerLangs = langOpen && (
    <div id="answer-langs" className="seg langs" role="group" aria-label={S.language[lang]} aria-busy={busy}>
      {LANGS.map(([code, label]) => (
        <button key={code} type="button" lang={code} aria-pressed={(screen === "confirm" ? lang : res?.lang) === code} disabled={busy}
          onClick={() => relang(code)}>
          {label}
        </button>
      ))}
    </div>
  );
  const err = error && (
    <div className="error" role="alert">
      <Icon.Alert size={20} />
      <Bi t={error} />
    </div>
  );

  return (
    <Lang.Provider value={lang}>
      <div className={`app${sun ? " sun" : ""}`} ref={main}>
        {screen === "home" && (
          <main className="screen home">
            <header className="bar">
              <div className="mark">
                <span className="name" lang={lang}>{S.appName[lang]}</span>
              </div>
              <button type="button" className="key key--icon" aria-label={S.sun[lang]} aria-pressed={sun}
                onClick={() => setSun(!sun)}>
                <Icon.Sun size={20} />
              </button>
            </header>
            <div className="seg langs" role="group" aria-label={S.language[lang]}>
              {LANGS.map(([code, label]) => (
                <button key={code} type="button" lang={code} aria-pressed={lang === code} onClick={() => setLang(code)}>
                  {label}
                </button>
              ))}
            </div>

            <div className="body">
              <Bi as="h1" className="ask" data-focus tabIndex={-1} t={S.ask} />

              <section className="talk">
                <button type="button" className="mic" onClick={start} aria-labelledby="mic-hint">
                  <Icon.Mic size={56} />
                </button>
                <Bi className="mic-label" id="mic-hint" t={S.tap} />
                {err}
              </section>

              <div className="more">
                <button type="button" className="quiet" onClick={() => typeInstead()}>
                  <Icon.Keyboard size={20} />
                  <span className="grow"><J t={S.typeInstead} /></span>
                </button>
                <div>
                  <button type="button" className="quiet" aria-expanded={how} aria-controls="how-text" onClick={() => setHow(!how)}>
                    <Icon.Help size={20} />
                    <span className="grow"><J t={S.how} /></span>
                  </button>
                  {how && (
                    <div id="how-text" className="how-text">
                      <Bi t={S.howText} />
                    </div>
                  )}
                </div>
              </div>

              <Bi className="note-foot" t={S.foot} />
            </div>
          </main>
        )}

        {screen === "listen" && (
          <main className="screen listen">
            <header className="bar">
              <button type="button" className="quiet cancel" onClick={cancel}>
                <Icon.X size={20} /> <span lang={lang}>{S.cancel[lang]}</span>
              </button>
              <Steps step={1} />
              <span className="spacer" />
            </header>
            <div className="body">
              <div role="status" aria-live="polite">
                {phase === "rec" ? (
                  <Bi as="h1" className="status" data-focus tabIndex={-1} t={S.listening} />
                ) : (
                  <Bi as="h1" className="status" t={S.thinking} />
                )}
              </div>
              {phase === "rec" ? (
                <div className="clock" aria-label={S.seconds[lang].replace("{n}", secs).replace("{m}", MAX_SECS)}>
                  <span className="time">{mmss(secs)}</span>
                  <span className="of">/ {mmss(MAX_SECS)}</span>
                </div>
              ) : (
                <div className="thinking"><Spinner /></div>
              )}
              <div className={`wave${metered ? " metered" : ""}${phase === "busy" ? " paused" : ""}`} aria-hidden="true">
                {[14, 26, 40, 20, 36, 44, 24, 32, 16, 28, 12].map((h, i) => (
                  <span key={i} ref={(el) => (bars.current[i] = el)} style={{ animationDelay: `${(i % 5) * -0.18}s`, "--h": h / 44 }}
                    className={h >= 30 ? "hi" : ""} />
                ))}
              </div>
              {heard && <p className="heard" lang={lang}>“{heard}”</p>}
            </div>
            {phase === "rec" && (
              <div className="foot">
                <button type="button" className="key key--primary" onClick={stopRec}>
                  <Icon.Stop size={20} /> <J t={S.stop} />
                </button>
              </div>
            )}
          </main>
        )}

        {screen === "confirm" && (typed || res) && (
          <main className="screen confirm">
            <TopBar onBack={typed ? again : start} backLabel={typed ? S.back : S.reRecord} step={2} right={langKey} />
            {answerLangs}
            <div className="body">
              <h1 className="said" data-focus={typed ? undefined : true} tabIndex={-1}>
                {typed ? <Icon.Keyboard size={20} /> : <Icon.Mic size={20} />}
                <J t={typed ? S.describe : S.said} />
              </h1>
              {editing ? (
                <div className="field">
                  <label htmlFor="draft"><J t={S.field} /></label>
                  <textarea id="draft" className="draft" value={draft} rows={4} data-focus={typed || undefined} lang={lang}
                    placeholder={S.placeholder[lang]} onChange={(e) => setDraft(e.target.value)} />
                </div>
              ) : (
                <div className="sheet"><p className="quote">“{res.transcript}”</p></div>
              )}
              {!typed && (
                <>
                  <Bi className="check" t={S.check} />
                  {!editing && (
                    <button type="button" className="quiet" onClick={() => setEditing(true)}>
                      <Icon.Pencil size={18} /> <J t={S.edit} />
                    </button>
                  )}
                </>
              )}
              {err}
            </div>
            <div className="foot">
              <button type="button" className="key key--primary" onClick={confirm} aria-busy={busy}
                disabled={busy || (editing && !draft.trim())}>
                {busy ? <><Spinner /> <J t={S.busy} /></> : <J t={typed ? S.getAdvice : S.yesRight} />}
              </button>
              <button type="button" className="quiet" onClick={start}>
                <Icon.Mic size={18} /> <J t={typed ? S.speakInstead : S.recordAgain} />
              </button>
            </div>
          </main>
        )}

        {screen === "result" && res && (
          <main className="screen result">
            <TopBar onBack={backToConfirm} step={3} right={langKey} />
            {answerLangs}
            {err && <div className="langs-err">{err}</div>}
            <div className="body">
              <article className="entry">
                <div className="entry-head">
                  <J t={fromApi(res, res.crop, res.crop_en)} />
                  <span className="chip"><Icon.Check size={14} /> <J t={S.highMatch} /></span>
                </div>
                <Bi as="h1" className="entry-title" data-focus tabIndex={-1} t={fromApi(res, res.name, res.name_en)} />
                <dl className="cells notebook">
                  <div className="cell cell--wide">
                    <dt><J t={S.treatment} /></dt>
                    <dd lang="en">{res.treatment.product}</dd>
                  </div>
                  <div className="cell">
                    <dt><J t={S.dose} /></dt>
                    <dd>
                      <span className="figure">
                        <span className="big">{perLitre[0]}</span>
                        <span className="unit">{perLitre.slice(1).join(" ")}</span>
                      </span>
                      <span lang={res.lang}>{S.perLitre[res.lang]}</span>
                    </dd>
                  </div>
                  <div className="cell cell--right">
                    <dt><J t={S.wait} /></dt>
                    <dd>
                      <span className="figure">
                        <span className="big">{res.treatment.waiting_days}</span>
                        <span className="unit" lang={res.lang}>{S.days[res.lang]}</span>
                      </span>
                      <span lang={res.lang}>{S.beforeHarvest[res.lang]}</span>
                    </dd>
                  </div>
                  {res.lang !== "en" && ( // in English the mixing line only repeats the dose figure above
                    <div className="cell cell--wide">
                      <dt><J t={S.mix} /></dt>
                      <dd lang={res.lang}>{res.treatment.dose_local}</dd>
                    </div>
                  )}
                  <div className="cell cell--wide">
                    <dt><J t={S.cause} /></dt>
                    <dd lang={res.lang}>{res.cause}</dd>
                  </div>
                </dl>
                <div className="entry-keys">
                  {listenKey}
                  <div className="helpful" aria-live="polite">
                    <J t={rated === null ? S.helpful : S.thanks} />
                  </div>
                  <button type="button" className="thumb" aria-label={S.helpfulYes[lang]} aria-pressed={rated === true}
                    disabled={rated !== null} onClick={() => rate(true)}>
                    <Icon.Thumb size={20} />
                  </button>
                  <button type="button" className="thumb down" aria-label={S.helpfulNo[lang]} aria-pressed={rated === false}
                    disabled={rated !== null} onClick={() => rate(false)}>
                    <Icon.Thumb size={20} />
                  </button>
                </div>
              </article>

              <div className="side">
                {res.verified === false && (
                  <p className="draft-note"><Icon.Alert size={18} /> <J t={S.draft} /></p>
                )}
                {res.options?.length > 0 && (
                  <section className="ruled options" aria-labelledby="options-title">
                    <div className="src" id="options-title"><J t={S.alsoReg} /></div>
                    <ul>
                      {res.options.map((o) => (
                        <li key={o.product}>
                          <a href={`${o.url}#page=${o.page}`} target="_blank" rel="noopener noreferrer" lang="en">{o.product}</a>
                          <span className="num">{o.per_litre} · {o.waiting_days ?? "-"} <span lang={res.lang}>{S.days[res.lang]}</span></span>
                        </li>
                      ))}
                    </ul>
                  </section>
                )}
                <aside className="ruled">
                  <div className="src"><J t={S.source} /></div>
                  <div>{res.source}</div>
                  <Bi t={fromApi(res, res.disclaimer, res.disclaimer_en)} />
                  {res.ref && <div className="ref num">{res.ref}</div>}
                </aside>
                <button type="button" className="key key--primary" onClick={again}><J t={S.another} /></button>
              </div>
            </div>
          </main>
        )}

        {screen === "escalate" && res && (
          <main className="screen escalate">
            <TopBar onBack={backToConfirm} step={3} alert right={langKey} />
            {answerLangs}
            <div className="body">
              <div className="lead">
                <h1 className="state" data-focus tabIndex={-1}>
                  <Icon.Help size={20} /> <J t={res.status === "choose" ? S.narrow : S.notSure} />
                </h1>

                {res.status === "choose" && !declined ? (
                  <>
                    <Bi className="question" t={fromApi(res, res.answer, res.answer_en)} />
                    {listenKey}
                    <div className={`choices${res.choose === "crop" ? " choices--crops" : ""}`} aria-busy={busy}>
                      {res.choices.map((c) => (
                        <button key={c.id} type="button" className="key" lang={res.lang} disabled={busy} onClick={() => choose(c)}>
                          {c.label}
                        </button>
                      ))}
                    </div>
                    <button type="button" className="quiet" onClick={toOfficer} disabled={busy}><J t={S.noneOfThese} /></button>
                    {err}
                  </>
                ) : res.followup && !declined ? (
                  <>
                    <Bi className="sorry" t={S.sorry} />
                    <Bi className="question" t={fromApi(res, res.answer, res.answer_en)} />
                    {listenKey}
                    <div className="yn">
                      <button type="button" className="key key--primary" onClick={followYes} disabled={busy} aria-busy={busy}>
                        {busy ? <Spinner /> : <J t={S.yes} />}
                      </button>
                      <button type="button" className="key" onClick={followNo} disabled={busy}><J t={S.no} /></button>
                    </div>
                    {err}
                    <p className="or" lang={lang}>{S.or[lang]}</p>
                  </>
                ) : (
                  <>
                    <Bi className="sorry" t={fromApi(res, res.answer, res.answer_en)} />
                    {listenKey}
                    {err}
                  </>
                )}
              </div>

              <div className="side">
                <section className="officer" ref={officer} aria-labelledby="officer-title">
                  <Bi as="h2" id="officer-title" t={S.officer} />
                  <a className={`key key--wide${callPrimary ? " key--primary" : ""}`} href={`tel:${KCC.replace(/-/g, "")}`}>
                    <Icon.Phone size={20} /> <span className="num">{KCC}</span>
                  </a>
                  <Bi className="kcc-note" t={S.kcc} />
                </section>

                <button type="button" className="quiet" onClick={again}><J t={S.tryAgain} /></button>
              </div>
            </div>
          </main>
        )}

        <audio ref={player} />
      </div>
    </Lang.Provider>
  );
}
