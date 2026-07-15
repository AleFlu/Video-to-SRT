/* shell.jsx — finestra macOS, menu, TabBar, status bar, state machine */
const { useState: s_uS, useEffect: s_uE, useRef: s_uR } = React;

/* ---------- Menu bar ---------- */
const MENUS = {
  File: [
    ["Apri file…", "⌘O"], ["Apri progetto .v2srt…", ""], ["Apri recenti", "▸"],
    "sep",
    ["Nuovo progetto", "⌃⇧T"], ["Nuova trascrizione", "⌘N"],
    "sep",
    ["Salva progetto .v2srt…", "⌘⇧S"], ["Esporta sottotitoli…", "⌘S"],
    "sep",
    ["Esci", "⌘Q"],
  ],
  Modifica: [
    ["Annulla", "⌘Z"], ["Ripristina", "⌘⇧Z"], "sep",
    ["Dividi", "⌘K"], ["Unisci", "⌘M"], ["Elimina", "⌘⇧K"], "sep",
    ["Trova e Sostituisci", "⌘F"],
  ],
  Vista: [["Schermo intero", "⌃⌘F"], "sep", ["Mostra/Nascondi Ispettore", "⌘I"]],
  Aiuto: [["Informazioni…", ""]],
};

function MenuBar({ open, setOpen, onAction }) {
  return (
    <div className="menubar" onMouseLeave={() => setOpen(null)}>
      {Object.keys(MENUS).map((name) => (
        <div key={name} style={{ position: "relative" }}>
          <button className={"menu-item" + (open === name ? " open" : "")}
            onClick={() => setOpen(open === name ? null : name)}
            onMouseEnter={() => open && setOpen(name)}>{name}</button>
          {open === name && (
            <div className="menu-pop">
              {MENUS[name].map((it, i) => it === "sep"
                ? <div className="menu-sep" key={i}></div>
                : <div className="menu-row" key={i} onClick={() => { setOpen(null); onAction(it[0]); }}>
                    <span>{it[0]}</span><span className="sc">{it[1]}</span>
                  </div>)}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

/* ---------- Tab bar ---------- */
function TabBar({ tab, setTab, unlocked, badge }) {
  return (
    <div className="tabbar">
      <button className={"tab" + (tab === 0 ? " active" : "")} onClick={() => setTab(0)}>Trascrizione</button>
      <button className={"tab" + (tab === 1 ? " active" : "")} onClick={() => setTab(1)}>
        Editor {unlocked ? (badge && <span className="badge-dot"></span>) : <span className="lock">🔒</span>}
      </button>
      <button className={"tab" + (tab === 2 ? " active" : "")} onClick={() => setTab(2)}>
        Esportazione {!unlocked && <span className="lock">🔒</span>}
      </button>
    </div>
  );
}

/* ---------- Export tab → app/export.jsx ---------- */

/* ---------- Toast ---------- */
function Toast({ msg }) {
  if (!msg) return null;
  return <div style={{ position: "absolute", bottom: 38, left: "50%", transform: "translateX(-50%)", zIndex: 80,
    background: "var(--card)", border: "1px solid var(--line-2)", borderRadius: 10, padding: "11px 18px",
    boxShadow: "var(--shadow)", fontSize: 13, color: "var(--text)", display: "flex", gap: 9, alignItems: "center" }}>
    <span style={{ color: "var(--ok)" }}>✓</span>{msg}</div>;
}

/* ---------- App ---------- */
const TWEAK_DEFAULTS = /*EDITMODE-BEGIN*/{
  "theme": "dark",
  "accent": ["#5b8cff", "#82a6ff", "#3f6fd8"],
  "density": 1,
  "radius": 11,
  "aurora": 1
}/*EDITMODE-END*/;

function App() {
  const hash = (location.hash || "").replace("#", "");
  const deep = hash === "editor" || hash === "result";
  const [t, setTweak] = useTweaks(TWEAK_DEFAULTS);
  const theme = t.theme;
  const setTheme = (v) => setTweak("theme", v);
  const [tab, setTab] = s_uS(hash === "editor" ? 1 : 0);
  const [sub, setSub] = s_uS(deep ? "result" : "home"); // home | progress | result
  const [file, setFile] = s_uS(deep ? window.SAMPLE_SOURCE : null);
  const [settings, setSettings] = s_uS({ model: "large-v3", language: "it", vad: true, high: false });
  const [subs, setSubs] = s_uS(deep ? window.SAMPLE_SUBS.map(x => ({ ...x })) : []);       // editor subtitles
  const [editorLoaded, setEditorLoaded] = s_uS(hash === "editor");
  const [modified, setModified] = s_uS(false);
  const [menu, setMenu] = s_uS(null);
  const [toast, setToast] = s_uS(null);
  const [inline, setInline] = s_uS(null);
  const [prog, setProg] = s_uS({ pct: 0, log: [], status: "" });
  const toastT = s_uR(null);

  s_uE(() => {
    const el = document.documentElement;
    el.classList.add("theme-switch");
    el.setAttribute("data-theme", theme);
    const id = setTimeout(() => el.classList.remove("theme-switch"), 60);
    return () => clearTimeout(id);
  }, [theme]);

  /* apply visual tweaks → CSS variables */
  s_uE(() => {
    const r = document.documentElement.style;
    if (t.accent) { r.setProperty("--acc", t.accent[0]); r.setProperty("--acc-h", t.accent[1]); r.setProperty("--acc-d", t.accent[2]); }
    r.setProperty("--radius-skip", "");
    r.setProperty("--r", t.radius + "px");
    r.setProperty("--density", t.density);
    r.setProperty("--aurora", t.aurora);
  }, [t.accent, t.radius, t.density, t.aurora]);

  const flash = (m) => { setToast(m); clearTimeout(toastT.current); toastT.current = setTimeout(() => setToast(null), 2200); };
  const unlocked = subs.length > 0;
  const badge = subs.length > 0;

  /* tweak host handled by useTweaks */

  /* progress simulation */
  function startTranscription() {
    setSub("progress"); setProg({ pct: 0, log: [], status: "Avvio…" });
    let p = 0;
    const id = setInterval(() => {
      p = Math.min(100, p + 6 + Math.random() * 4);
      const lines = window.PROGRESS_LOG.slice(0, Math.min(window.PROGRESS_LOG.length, Math.floor(p / 10) + 1));
      const status = p < 30 ? "Preparazione audio…" : p < 95 ? `Decodifica segmenti… ${Math.round(p)}%` : "Finalizzazione…";
      setProg({ pct: p, log: lines, status });
      if (p >= 100) {
        clearInterval(id);
        setTimeout(() => { setSubs(window.SAMPLE_SUBS.map(x => ({ ...x }))); setEditorLoaded(false); setModified(false); setSub("result"); }, 350);
      }
    }, 240);
  }

  function openEditor() {
    if (!editorLoaded) setEditorLoaded(true);
    setTab(1);
  }

  /* navigazione tab: una tab “bloccata” carica la trascrizione demo per esplorarla */
  function goTab(i) {
    if (i > 0 && subs.length === 0) {
      setSubs(window.SAMPLE_SUBS.map((x) => ({ ...x })));
      if (!file) setFile(window.SAMPLE_SOURCE);
      setEditorLoaded(true);
      setModified(false);
      if (sub === "home") setSub("result");
    }
    if (i === 1) setEditorLoaded(true);
    setTab(i);
  }
  function newTranscription() {
    if (modified || subs.length) {
      if (!window.confirm(`Hai ${subs.length} sottotitoli non esportati. Avviare una nuova trascrizione?`)) return;
    }
    setFile(null); setSub("home"); setTab(0);
  }
  function editRow(row, field, val) {
    setSubs((arr) => arr.map((s, i) => {
      if (i !== row) return s;
      if (field === "text") return { ...s, text: val };
      if (field === "shift") return { ...s, start: Math.max(0, s.start + val / 1000), end: s.end + val / 1000 };
      return s;
    }));
    setModified(true);
  }
  function importInEditor() {
    if (inline) return;
    setInline({ pct: 0 });
    let p = 0;
    const id = setInterval(() => {
      p = Math.min(100, p + 6 + Math.random() * 5);
      setInline({ pct: Math.round(p) });
      if (p >= 100) { clearInterval(id); setTimeout(() => { setInline(null); flash("File importato nell’editor"); }, 300); }
    }, 200);
  }

  function menuAction(label) {
    switch (label) {
      case "Apri file…": setFile(window.SAMPLE_SOURCE); setTab(0); setSub("home"); break;
      case "Nuova trascrizione": case "Nuovo progetto": newTranscription(); break;
      case "Esporta sottotitoli…": if (unlocked) setTab(2); else flash("Nessun sottotitolo da esportare"); break;
      case "Salva progetto .v2srt…": flash("Progetto salvato · .v2srt"); break;
      case "Mostra/Nascondi Ispettore": flash("Ispettore: usa il pulsante nella toolbar timeline"); break;
      case "Informazioni…": flash("Video → SRT v2 · redesign “Studio”"); break;
      case "Esci": flash("(Esci)"); break;
      default: flash(label);
    }
  }

  return (
    <div className="win">
      <div className="titlebar">
        <div className="traffic"><i className="c-red"></i><i className="c-yel"></i><i className="c-grn"></i></div>
        <div className="win-title"><span className="glyph">≋</span> Video → SRT</div>
        <div className="titlebar-right">
          <button className="theme-toggle" onClick={() => setTheme(theme === "dark" ? "light" : "dark")}>
            {theme === "dark" ? "☾ Scuro" : "☀ Chiaro"}
          </button>
        </div>
      </div>

      <MenuBar open={menu} setOpen={setMenu} onAction={menuAction} />
      <TabBar tab={tab} setTab={goTab} unlocked={unlocked} badge={badge} />

      <div className="stage" onClick={() => menu && setMenu(null)}>
        {tab === 0 && sub === "home" && (
          <HomeWidget file={file} settings={settings} setSettings={setSettings}
            onPick={() => setFile(window.SAMPLE_SOURCE)} onChange={() => setFile(null)}
            onStart={startTranscription} depsWarn={false} />
        )}
        {tab === 0 && sub === "progress" && (
          <ProgressWidget file={file} settings={settings} pct={prog.pct} log={prog.log} status={prog.status}
            onStop={() => { setSub("home"); }} />
        )}
        {tab === 0 && sub === "result" && (
          <ResultWidget subs={subs} file={file} modified={modified && editorLoaded}
            onNew={newTranscription} onExport={() => setTab(2)} onOpenEditor={openEditor} />
        )}

        {tab === 1 && (
          editorLoaded
            ? <WorkspaceWidget subs={subs} file={file} inline={inline} onImport={importInEditor} onEdit={editRow} />
            : <PlaceholderWidget onGoTranscription={() => setTab(0)} onImport={() => { if (unlocked) { setEditorLoaded(true); } else { setTab(0); } }} />
        )}

        {tab === 2 && <ExportTab subs={subs} file={file} onSave={(f) => { setModified(false); flash(`Esportato · ${file ? file.name.replace(/\.[^.]+$/, "") : "sottotitoli"}.${f.toLowerCase()}`); }} />}

        <Toast msg={toast} />
      </div>

      <StatusBar tab={tab} sub={sub} subs={subs} file={file} modified={modified && editorLoaded} prog={prog} inline={inline} />

      <TweaksPanel title="Tweaks">
        <TweakSection label="Tema" />
        <TweakRadio label="Aspetto" value={t.theme} options={["dark", "light"]} onChange={(v) => setTweak("theme", v)} />
        <TweakColor label="Accent" value={t.accent}
          options={[["#5b8cff", "#82a6ff", "#3f6fd8"], ["#34c98a", "#5fd9a6", "#23a06d"], ["#a78bfa", "#c0a9ff", "#8b66f0"], ["#f5853f", "#ff9e5e", "#dc6a26"]]}
          onChange={(v) => setTweak("accent", v)} />
        <TweakSection label="Layout" />
        <TweakSlider label="Densità" value={t.density} min={0.82} max={1.18} step={0.04} onChange={(v) => setTweak("density", v)} />
        <TweakSlider label="Angoli" value={t.radius} min={2} max={18} step={1} unit="px" onChange={(v) => setTweak("radius", v)} />
        <TweakSlider label="Aurora" value={t.aurora} min={0} max={1.4} step={0.1} onChange={(v) => setTweak("aurora", v)} />
      </TweaksPanel>
    </div>
  );
}

/* ---------- Status bar ---------- */
function StatusBar({ tab, sub, subs, file, modified, prog, inline }) {
  const counts = subs.reduce((a, s, i) => { const sev = window.rowDiag(s, subs[i - 1]).sev; a[sev]++; return a; }, { ok: 0, warning: 0, error: 0 });
  let left = "Pronto";
  if (tab === 0 && sub === "home") left = file ? `Sorgente: ${file.name}` : "Trascina un file per iniziare";
  else if (tab === 0 && sub === "progress") left = `Trascrizione… ${Math.round(prog.pct)}%`;
  else if (tab === 0 && sub === "result") left = `${subs.length} sottotitoli · trascrizione completata`;
  else if (tab === 1) left = inline ? "Importazione in corso…" : `${subs.length} sottotitoli`;
  else if (tab === 2) left = "Pronto per l’esportazione";
  return (
    <div className="statusbar">
      <div className="sb-l">
        <span>{left}</span>
        {(tab === 1 || (tab === 0 && sub === "result")) && subs.length > 0 && (
          <React.Fragment>
            <span className="sdot"><i style={{ background: "var(--ok)" }}></i>{counts.ok}</span>
            <span className="sdot"><i style={{ background: "var(--warn)" }}></i>{counts.warning}</span>
            <span className="sdot"><i style={{ background: "var(--err)" }}></i>{counts.error}</span>
            {modified && <span style={{ color: "var(--warn)" }}>● modificato</span>}
          </React.Fragment>
        )}
      </div>
      <div>{file ? `${file.ext} · ${file.size}` : "VideoSRT v2"}</div>
    </div>
  );
}

ReactDOM.createRoot(document.getElementById("root")).render(<App />);
Object.assign(window, { App });
