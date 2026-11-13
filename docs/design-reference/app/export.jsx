/* export.jsx — Tab Esportazione: formato + opzioni + anteprima live + salvataggio */
const { useState: x_uS } = React;

function wrapLine(text, max) {
  return text.split("\n").map((line) => {
    if (line.length <= max) return line;
    const words = line.split(" "); const out = []; let cur = "";
    for (const w of words) {
      if ((cur + " " + w).trim().length > max) { out.push(cur.trim()); cur = w; }
      else cur += " " + w;
    }
    if (cur.trim()) out.push(cur.trim());
    return out.join("\n");
  }).join("\n");
}

window.buildExport = function (fmt, subs, opts) {
  const wrap = (t) => opts.wrap ? wrapLine(t, window.CONST.MAX_CHARS_PER_LINE) : t;
  if (fmt === "TXT") return subs.map((s) => wrap(s.text).replace(/\n/g, " ")).join("\n");
  if (fmt === "VTT") {
    let o = "WEBVTT\n\n";
    subs.forEach((s, i) => { o += `${i + 1}\n${window.fmtVttStamp(s.start)} --> ${window.fmtVttStamp(s.end)}\n${wrap(s.text)}\n\n`; });
    return o.trimEnd();
  }
  if (fmt === "ASS") {
    let o = "[Script Info]\nTitle: intervista_cagliari\nScriptType: v4.00+\nWrapStyle: 0\n\n";
    o += "[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, Bold, Alignment, MarginV\n";
    o += "Style: Default,Helvetica,42,&H00FFFFFF,0,2,28\n\n";
    o += "[Events]\nFormat: Layer, Start, End, Style, Text\n";
    subs.forEach((s) => { o += `Dialogue: 0,${window.fmtAssStamp(s.start)},${window.fmtAssStamp(s.end)},Default,${wrap(s.text).replace(/\n/g, "\\N")}\n`; });
    return o.trimEnd();
  }
  // SRT
  let o = "";
  subs.forEach((s, i) => { o += `${i + 1}\n${window.fmtSrtStamp(s.start)} --> ${window.fmtSrtStamp(s.end)}\n${wrap(s.text)}\n\n`; });
  return o.trimEnd();
};

const EXPORT_FORMATS = [
  ["SRT", "srt", "SubRip · standard universale, compatibile ovunque"],
  ["VTT", "vtt", "WebVTT · sottotitoli per il web (HTML5)"],
  ["TXT", "txt", "Solo testo, senza marcatori temporali"],
  ["ASS", "ass", "Advanced SubStation · stili e posizionamento"],
];

function ExportTab({ subs, file, onSave }) {
  const [fmt, setFmt] = x_uS("SRT");
  const [wrap, setWrap] = x_uS(true);
  const [bom, setBom] = x_uS(false);
  const [done, setDone] = x_uS(null);
  const base = file ? file.name.replace(/\.[^.]+$/, "") : "sottotitoli";
  const name = `${base}.${fmt.toLowerCase()}`;
  const content = window.buildExport(fmt, subs, { wrap });
  const bytes = new Blob([content]).size;
  const kb = bytes < 1024 ? `${bytes} B` : `${(bytes / 1024).toFixed(1)} KB`;

  function save() { setDone(name); onSave(fmt); }

  return (
    <div className="scene fade">
      <div className="aurora"></div>
      <div className="exp-col">
        <div className="eyebrow">Esportazione</div>
        <h1 className="h1 mt12">Esporta i sottotitoli</h1>
        <p className="lead mt12">{subs.length} sottotitoli da <span className="mono" style={{ color: "var(--dim)" }}>{file ? file.name : "—"}</span>, pronti per il salvataggio.</p>

        <div className="exp-grid mt24">
          {/* left: settings */}
          <div className="stack" style={{ gap: 18 }}>
            <div>
              <div className="label" style={{ marginBottom: 10 }}>Formato</div>
              <div className="stack" style={{ gap: 9 }}>
                {EXPORT_FORMATS.map(([k, ext, d]) => (
                  <div key={k} className={"fmt-card" + (fmt === k ? " sel" : "")} onClick={() => { setFmt(k); setDone(null); }}>
                    <span className="radio">{fmt === k && <i></i>}</span>
                    <div className="stack" style={{ flex: 1 }}>
                      <span className="fmt-ext">.{ext}</span>
                      <span className="fmt-desc">{d}</span>
                    </div>
                  </div>
                ))}
              </div>
            </div>

            <div>
              <div className="label" style={{ marginBottom: 10 }}>Opzioni</div>
              <div className="stack" style={{ gap: 9 }}>
                <div className={"opt-row" + (wrap ? " on" : "")} onClick={() => setWrap(!wrap)}>
                  <span className="check">{wrap && "✓"}</span>
                  <div className="stack"><span className="opt-t">Spezza righe lunghe</span><span className="opt-d">Massimo {window.CONST.MAX_CHARS_PER_LINE} caratteri per riga</span></div>
                </div>
                <div className={"opt-row" + (bom ? " on" : "") + (fmt === "ASS" ? " dis" : "")} onClick={() => fmt !== "ASS" && setBom(!bom)}>
                  <span className="check">{bom && "✓"}</span>
                  <div className="stack"><span className="opt-t">Includi BOM UTF-8</span><span className="opt-d">Per compatibilità con alcuni lettori Windows</span></div>
                </div>
              </div>
            </div>

            <div className="exp-dest">
              <div className="field" style={{ flex: 1 }}>
                <span className="label">Nome file</span>
                <div className="spin"><input value={name} readOnly /></div>
              </div>
              <div className="field" style={{ flex: 1 }}>
                <span className="label">Cartella</span>
                <div className="exp-folder"><span className="mono" style={{ color: "var(--dim)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>~/Documenti/Sottotitoli</span><button className="btn sm ghost">Scegli…</button></div>
              </div>
            </div>
          </div>

          {/* right: live preview */}
          <div className="stack" style={{ minWidth: 0 }}>
            <div className="row" style={{ marginBottom: 10 }}>
              <span className="label">Anteprima · {name}</span>
              <span className="spacer"></span>
              <span className="mono" style={{ fontSize: 11, color: "var(--muted)" }}>{kb} · UTF-8{bom ? " · BOM" : ""}</span>
            </div>
            <pre className="exp-preview">{content}</pre>
          </div>
        </div>

        <div className="row mt24">
          {done && <span className="mod-badge" style={{ background: "var(--ok-soft)", borderColor: "color-mix(in srgb,var(--ok) 36%, transparent)", color: "var(--ok)" }}>✓ Esportato · {done}</span>}
          <span className="spacer"></span>
          {done
            ? <React.Fragment>
                <button className="btn ghost" onClick={() => setDone(null)}>Esporta di nuovo</button>
                <button className="btn primary" style={{ minWidth: 180 }}>Mostra nel Finder</button>
              </React.Fragment>
            : <button className="btn primary" style={{ minWidth: 200 }} onClick={save}>Esporta {fmt} →</button>}
        </div>
      </div>
    </div>
  );
}

Object.assign(window, { ExportTab });
