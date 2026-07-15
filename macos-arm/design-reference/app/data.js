/* data.js — dati di esempio + helper formato/diagnostica.
   Tutto in secondi (float) internamente; formattato MM:SS.mmm in UI.
   Soglie da core/constants.py — NON cambiare i valori. */
window.CONST = {
  MAX_CHARS_PER_LINE: 42,
  MAX_SUBTITLE_DURATION: 7.0,
  MIN_SUBTITLE_DURATION: 0.5,
  MAX_CPS: 20.0,
};

/* ---- formato ---- */
function pad(n, w) { return String(n).padStart(w, "0"); }

window.fmtTC = function (sec) {
  // "MM:SS.mmm" — ore solo se > 1h
  sec = Math.max(0, sec);
  const ms = Math.round((sec - Math.floor(sec)) * 1000);
  const total = Math.floor(sec);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  const base = `${pad(m, 2)}:${pad(s, 2)}.${pad(ms, 3)}`;
  return h > 0 ? `${pad(h, 2)}:${base}` : base;
};

window.fmtDur = function (sec) {
  // "SS.mmm"
  const ms = Math.round((sec - Math.floor(sec)) * 1000);
  return `${pad(Math.floor(sec), 2)}.${pad(ms, 3)}`;
};

window.fmtClock = function (sec) {
  const total = Math.floor(sec);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  return h > 0 ? `${pad(h, 2)}:${pad(m, 2)}:${pad(s, 2)}` : `${pad(m, 2)}:${pad(s, 2)}`;
};

/* timestamp per formato file */
window.fmtSrtStamp = function (sec) { // HH:MM:SS,mmm  (virgola — standard SRT)
  const ms = Math.round((sec - Math.floor(sec)) * 1000), t = Math.floor(sec);
  return `${pad(Math.floor(t / 3600), 2)}:${pad(Math.floor((t % 3600) / 60), 2)}:${pad(t % 60, 2)},${pad(ms, 3)}`;
};
window.fmtVttStamp = function (sec) { // HH:MM:SS.mmm  (punto — WebVTT)
  return window.fmtSrtStamp(sec).replace(",", ".");
};
window.fmtAssStamp = function (sec) { // H:MM:SS.cc  (centesimi — ASS)
  const cs = Math.round((sec - Math.floor(sec)) * 100), t = Math.floor(sec);
  return `${Math.floor(t / 3600)}:${pad(Math.floor((t % 3600) / 60), 2)}:${pad(t % 60, 2)}.${pad(cs, 2)}`;
};

window.cps = function (sub) {
  const dur = Math.max(0.001, sub.end - sub.start);
  const chars = (sub.text || "").replace(/\s/g, "").length;
  return chars / dur;
};

/* ---- diagnostica: ritorna {sev, issues[]} per una riga ---- */
window.rowDiag = function (sub, prev) {
  const C = window.CONST;
  const issues = [];
  const dur = sub.end - sub.start;
  const c = window.cps(sub);
  if (sub.end <= sub.start) issues.push({ sev: "error", msg: "Fine ≤ inizio" });
  if (prev && sub.start < prev.end) issues.push({ sev: "error", msg: "Sovrapposizione con la riga precedente" });
  if (!sub.text || !sub.text.trim()) issues.push({ sev: "error", msg: "Testo vuoto" });
  if (dur > 0 && dur < C.MIN_SUBTITLE_DURATION) issues.push({ sev: "warning", msg: `Durata < ${C.MIN_SUBTITLE_DURATION}s` });
  if (dur > C.MAX_SUBTITLE_DURATION) issues.push({ sev: "warning", msg: `Durata > ${C.MAX_SUBTITLE_DURATION}s` });
  if (c > C.MAX_CPS) issues.push({ sev: "warning", msg: `CPS ${c.toFixed(1)} oltre ${C.MAX_CPS}` });
  const line = (sub.text || "").split("\n").reduce((a, l) => Math.max(a, l.length), 0);
  if (line > C.MAX_CHARS_PER_LINE) issues.push({ sev: "warning", msg: `Riga > ${C.MAX_CHARS_PER_LINE} caratteri` });
  let sev = "ok";
  if (issues.some((i) => i.sev === "error")) sev = "error";
  else if (issues.some((i) => i.sev === "warning")) sev = "warning";
  return { sev, issues };
};

/* ---- sottotitoli di esempio (italiano) ---- */
window.SAMPLE_SOURCE = { name: "intervista_cagliari.mp4", size: "248,6 MB", ext: "MP4", duration: 184.2 };

window.SAMPLE_SUBS = [
  { start: 0.32, end: 2.84, text: "Allora, raccontami: come è nato tutto questo?" },
  { start: 2.96, end: 6.20, text: "È nato per caso, in realtà, in un pomeriggio d'estate a Cagliari." },
  { start: 6.40, end: 9.12, text: "Avevo bisogno di sottotitolare dei video\nper il museo del quartiere." },
  { start: 9.30, end: 11.05, text: "E gli strumenti che trovavo erano lentissimi." },
  { start: 11.20, end: 15.60, text: "Così ho pensato: e se costruissi qualcosa che facesse tutto in locale, sul mio Mac, senza mandare niente in rete?" },
  { start: 15.78, end: 18.40, text: "Una scelta di privacy, prima ancora che di velocità." },
  { start: 18.55, end: 21.10, text: "Esatto. I file restano sul dispositivo, sempre." },
  { start: 21.28, end: 24.02, text: "E la trascrizione gira con un modello Whisper offline." },
  { start: 24.20, end: 25.10, text: "Incredibile." },
  { start: 25.05, end: 28.40, text: "Il bello è che poi puoi rifinire ogni riga nell'editor, con la forma d'onda davanti." },
  { start: 28.60, end: 31.95, text: "Tagli, unisci, sistemi i tempi al millesimo. Come in una vera sala di montaggio." },
  { start: 32.10, end: 35.50, text: "E alla fine esporti in SRT, VTT, o nel formato di progetto." },
  { start: 35.70, end: 38.20, text: "Un flusso pulito, dall'inizio alla fine." },
  { start: 38.35, end: 40.90, text: "Proprio così. Grazie per essere passato." },
];

window.SAMPLE_RECENTS = [
  { name: "intervista_cagliari.mp4", size: "248,6 MB", ext: "MP4" },
  { name: "lezione_storia_03.mov", size: "1,2 GB", ext: "MOV" },
  { name: "podcast_ep12.mp3", size: "84,1 MB", ext: "MP3" },
];

window.MODELS = [
  ["tiny", "Tiny · veloce"],
  ["base", "Base"],
  ["small", "Small"],
  ["medium", "Medium"],
  ["large-v2", "Large v2"],
  ["large-v3", "Large v3 · qualità"],
];
window.LANGS = [
  ["it", "Italiano (auto)"],
  ["en", "English"],
  ["es", "Español"],
  ["fr", "Français"],
  ["de", "Deutsch"],
  ["auto", "Auto-detect"],
];
window.SPEEDS = ["0.5×", "0.75×", "1×", "1.25×", "1.5×", "2×"];

/* log finto per ProgressWidget */
window.PROGRESS_LOG = [
  "Verifica FFmpeg… ok",
  "Estrazione traccia audio (16 kHz mono)…",
  "Caricamento modello large-v3…",
  "VAD: rilevamento segmenti vocali…",
  "Decodifica beam search (beam=5)…",
  "Segmento 1/14  ·  00:00.320 → 00:02.840",
  "Segmento 4/14  ·  00:09.300 → 00:11.050",
  "Segmento 8/14  ·  00:21.280 → 00:24.020",
  "Post-processing timing…",
  "Allineamento parole…",
];
