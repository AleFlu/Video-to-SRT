/* transcription.jsx — Home · Progress · Result (tab Trascrizione) */
const { useState, useEffect, useRef } = React;

/* ---------- Toggle switch ---------- */
function Toggle({ on, onToggle, onLabel, offLabel }) {
  return (
    <div className={"toggle" + (on ? " on" : "")} onClick={onToggle}>
      <span className="pill"><i></i></span>
      <span className="state">{on ? onLabel : offLabel}</span>
    </div>
  );
}

/* ---------- Drop zone (idle / hover / loaded / error) ---------- */
function DropZone({ file, onPick, onChange }) {
  const [hover, setHover] = useState(false);
  if (file) {
    return (
      <div className="drop loaded">
        <div className="file-icn">▶</div>
        <div className="stack" style={{ flex: 1, minWidth: 0 }}>
          <div className="drop-title" style={{ whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{file.name}</div>
          <div className="drop-sub">{file.size} · {file.ext}</div>
        </div>
        <button className="btn sm ghost" onClick={onChange}>Cambia</button>
      </div>
    );
  }
  return (
    <div
      className={"drop" + (hover ? " hover" : "")}
      onClick={onPick}
      onDragOver={(e) => { e.preventDefault(); setHover(true); }}
      onDragLeave={() => setHover(false)}
      onDrop={(e) => { e.preventDefault(); setHover(false); onPick(); }}
    >
      <div className="drop-icn">↓</div>
      <div className="drop-title">{hover ? "Rilascia per caricare" : "Trascina qui un file video o audio"}</div>
      {!hover && <div className="drop-sub">oppure <span className="kbd">⌘O</span> per scegliere · MP4, MOV, MKV, WAV, MP3 fino a 4 GB</div>}
    </div>
  );
}

/* ---------- Settings card ---------- */
function SettingsCard({ settings, set }) {
  const active = [settings.vad && "VAD", settings.high && "Alta precisione"].filter(Boolean);
  const preset = `${window.LANGS.find(l => l[0] === settings.language)[1].split(" ")[0]} · ${settings.high ? "Alta precisione" : "Standard"}`;
  return (
    <div className="card settings">
      <div className="settings-head">
        <span className="label">Impostazioni di trascrizione</span>
        <span className="mono" style={{ fontSize: 10.5, color: "var(--faint)" }}>{active.length} attive · preset “{preset}”</span>
      </div>
      <div className="settings-grid">
        <div className="field">
          <span className="label">Modello Whisper</span>
          <select className="select" value={settings.model} onChange={(e) => set({ model: e.target.value })}>
            {window.MODELS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select>
        </div>
        <div className="field">
          <span className="label">Lingua</span>
          <select className="select" value={settings.language} onChange={(e) => set({ language: e.target.value })}>
            {window.LANGS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select>
        </div>
        <div className="field">
          <span className="label">Filtro VAD</span>
          <Toggle on={settings.vad} onToggle={() => set({ vad: !settings.vad })} onLabel="Attivo" offLabel="Disattivo" />
        </div>
        <div className="field">
          <span className="label">Alta precisione</span>
          <Toggle on={settings.high} onToggle={() => set({ high: !settings.high })} onLabel="Attiva" offLabel="Standard" />
        </div>
      </div>
    </div>
  );
}

/* ---------- HomeWidget ---------- */
function HomeWidget({ file, settings, setSettings, onPick, onChange, onStart, depsWarn }) {
  return (
    <div className="scene fade">
      <div className="aurora"></div>
      <div className="col">
        {depsWarn && (
          <div className="deps" style={{ marginBottom: 20 }}>
            <span className="di">⚠️</span>
            <span style={{ fontSize: 12.5, color: "var(--dim)" }}>Modello Whisper non ancora scaricato — la prima trascrizione lo scaricherà automaticamente.</span>
          </div>
        )}
        <div className="eyebrow">Trascrizione</div>
        <h1 className="h1 mt12">Trasforma il tuo video<br />in sottotitoli SRT.</h1>
        <p className="lead mt12" style={{ maxWidth: 560 }}>
          Trascrizione automatica in italiano, interamente in locale sul tuo Mac. Trascina un file, scegli il modello e ottieni sottotitoli pronti da rifinire nell’editor.
        </p>

        <div className="mt24"><DropZone file={file} onPick={onPick} onChange={onChange} /></div>

        <div className="mt16"><SettingsCard settings={settings} set={(p) => setSettings({ ...settings, ...p })} /></div>

        <div className="row mt20">
          <span className="mono" style={{ fontSize: 12, color: "var(--muted)" }}>
            {file ? "Stima · ~1,8× tempo reale" : "Stima · –"}
          </span>
          <span className="spacer"></span>
          <button className="btn ghost" disabled={!file}>Anteprima impostazioni</button>
          <button className="btn primary" style={{ minWidth: 210 }} disabled={!file} onClick={onStart}>
            <span>▶</span> Avvia trascrizione
          </button>
        </div>

        <div className="mt32">
          <div className="label" style={{ marginBottom: 12 }}>Recenti</div>
          <div className="recents-grid">
            {window.SAMPLE_RECENTS.map((r, i) => (
              <div className="recent" key={i} onClick={onPick}>
                <div className="ri">▦</div>
                <div className="stack" style={{ minWidth: 0 }}>
                  <div className="rn">{r.name}</div>
                  <div className="rs">{r.size} · {r.ext}</div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

/* ---------- ProgressWidget ---------- */
function ProgressWidget({ file, settings, pct, log, status, onStop }) {
  const logRef = useRef(null);
  useEffect(() => { if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight; }, [log]);
  const cfg = `${window.MODELS.find(m => m[0] === settings.model)[1].split(" ")[0]} · ${window.LANGS.find(l => l[0] === settings.language)[1]} · VAD ${settings.vad ? "on" : "off"}${settings.high ? " · alta precisione" : ""}`;
  return (
    <div className="scene fade">
      <div className="aurora"></div>
      <div className="col">
        <div className="row gap10">
          <div className="spinner"></div>
          <h2 className="h2">Trascrizione in corso…</h2>
        </div>
        <div className="card u-pad mt20" style={{ display: "flex", alignItems: "center", gap: 14 }}>
          <div className="file-icn">▶</div>
          <div className="stack" style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontWeight: 600 }}>{file ? file.name : "—"}</div>
            <div className="mono" style={{ fontSize: 11.5, color: "var(--muted)" }}>{cfg}</div>
          </div>
          <div className="mono" style={{ fontSize: 22, fontWeight: 600, color: "var(--acc)" }}>{Math.round(pct)}%</div>
        </div>

        <div className="bar mt20"><i style={{ width: pct + "%" }}></i></div>
        <div className="mt12" style={{ fontSize: 13, color: "var(--dim)" }}>{status}</div>

        <div className="logbox mt16" ref={logRef}>
          {log.map((l, i) => <div key={i}><span className="ts">[{String(Math.floor(i * 1.3)).padStart(2, "0")}:{String((i * 7) % 60).padStart(2, "0")}]</span>  {l}</div>)}
        </div>

        <div className="row mt20">
          <span className="spacer"></span>
          <button className="btn danger" onClick={onStop}>Interrompi trascrizione</button>
        </div>
      </div>
    </div>
  );
}

/* ---------- ResultWidget ---------- */
function ResultWidget({ subs, file, modified, onNew, onExport, onOpenEditor }) {
  const n = subs.length;
  const avg = (subs.reduce((a, s) => a + (s.end - s.start), 0) / n);
  const avgCps = (subs.reduce((a, s) => a + window.cps(s), 0) / n);
  const coverage = Math.min(100, Math.round((subs.reduce((a, s) => a + (s.end - s.start), 0) / (file ? file.duration : 184)) * 100));
  return (
    <div className="scene fade">
      <div className="col">
        <div className="eyebrow" style={{ color: "var(--ok)" }}>✓ Completata</div>
        <h1 className="h1 mt12">Trascrizione completata</h1>
        <div className="row mt12" style={{ gap: 14 }}>
          <span className="lead" style={{ margin: 0 }}>{n} sottotitoli · {file ? file.name : "video.mp4"}</span>
          {modified && <span className="mod-badge">⚠ Versione modificata nell’editor</span>}
        </div>

        <div className="stats mt24">
          <div className="stat"><div className="v acc">{n}</div><div className="k">Sottotitoli</div></div>
          <div className="stat"><div className="v">{avg.toFixed(1)}<span style={{ fontSize: 15, color: "var(--muted)" }}>s</span></div><div className="k">Durata media</div></div>
          <div className="stat"><div className="v">{avgCps.toFixed(1)}</div><div className="k">CPS medio</div></div>
          <div className="stat"><div className="v">{coverage}<span style={{ fontSize: 15, color: "var(--muted)" }}>%</span></div><div className="k">Copertura</div></div>
        </div>

        <div className="label mt24" style={{ marginBottom: 10 }}>Anteprima</div>
        <div className="preview-rows">
          {subs.slice(0, 6).map((s, i) => (
            <div className="prow" key={i}>
              <span className="pn">{i + 1}</span>
              <span className="pt">{window.fmtTC(s.start)}</span>
              <span className="px">{s.text.replace(/\n/g, " ")}</span>
            </div>
          ))}
        </div>

        <div className="row mt24">
          <button className="btn ghost" onClick={onNew}>Nuova trascrizione</button>
          <span className="spacer"></span>
          <button className="btn" onClick={onExport}>Esporta SRT</button>
          <button className="btn primary" onClick={onOpenEditor}>Apri nell’editor →</button>
        </div>
      </div>
    </div>
  );
}

Object.assign(window, { HomeWidget, ProgressWidget, ResultWidget, Toggle });
