/* editor.jsx — WorkspaceWidget DaVinci: Preview + Transport + Timeline + Inspector */
const { useState: uS, useEffect: uE, useRef: uR, useMemo: uM } = React;

/* ---------- Waveform (canvas) ---------- */
function WaveformCanvas({ subs, duration, cur, selRow, severities, onSeek, onClickSub }) {
  const ref = uR(null);
  const peaks = uM(() => {
    const N = 900; const a = [];
    let s = 7;
    const rnd = () => { s = (s * 9301 + 49297) % 233280; return s / 233280; };
    for (let i = 0; i < N; i++) {
      const env = 0.35 + 0.65 * Math.abs(Math.sin(i / 26) * Math.sin(i / 7.3));
      a.push(Math.max(0.04, env * (0.55 + 0.45 * rnd())));
    }
    return a;
  }, []);
  uE(() => {
    const cv = ref.current; if (!cv) return;
    const dpr = window.devicePixelRatio || 1;
    const W = cv.clientWidth, H = cv.clientHeight;
    cv.width = W * dpr; cv.height = H * dpr;
    const g = cv.getContext("2d"); g.setTransform(dpr, 0, 0, dpr, 0, 0);
    g.clearRect(0, 0, W, H);
    const css = getComputedStyle(document.documentElement);
    const fill = css.getPropertyValue("--wave-fill").trim() || "#3a5f8a";
    const acc = css.getPropertyValue("--acc").trim();
    const ok = css.getPropertyValue("--ok").trim(), warn = css.getPropertyValue("--warn").trim(), err = css.getPropertyValue("--err").trim();
    const sevColor = { ok, warning: warn, error: err };
    const mid = H * 0.5, maxH = H * 0.4;
    // subtitle blocks (top strip)
    subs.forEach((sub, i) => {
      const x0 = (sub.start / duration) * W, x1 = (sub.end / duration) * W;
      const c = sevColor[severities[i]] || ok;
      g.fillStyle = c + "26";
      g.fillRect(x0, 0, Math.max(2, x1 - x0), H);
      if (i === selRow) { g.fillStyle = acc + "22"; g.fillRect(x0, 0, Math.max(2, x1 - x0), H); }
      g.fillStyle = c; g.fillRect(x0, 0, Math.max(2, x1 - x0), 3);
    });
    // waveform bars
    const bw = W / peaks.length;
    peaks.forEach((p, i) => {
      const x = i * bw, h = p * maxH;
      const played = (i * bw) / W < cur / duration;
      g.fillStyle = played ? acc : fill;
      g.globalAlpha = played ? 0.95 : 0.7;
      g.fillRect(x, mid - h, Math.max(0.6, bw - 0.4), h * 2);
    });
    g.globalAlpha = 1;
    // playhead
    const px = (cur / duration) * W;
    g.strokeStyle = "#ff5a5a"; g.lineWidth = 1.5;
    g.beginPath(); g.moveTo(px, 0); g.lineTo(px, H); g.stroke();
    g.fillStyle = "#ff5a5a"; g.beginPath(); g.moveTo(px - 4, 0); g.lineTo(px + 4, 0); g.lineTo(px, 6); g.fill();
  });
  const handle = (e, cb) => {
    const r = ref.current.getBoundingClientRect();
    const t = ((e.clientX - r.left) / r.width) * duration;
    cb(t);
  };
  return (
    <canvas ref={ref} className="wave-canvas"
      onClick={(e) => {
        const r = ref.current.getBoundingClientRect();
        const t = ((e.clientX - r.left) / r.width) * duration;
        const hit = subs.findIndex(s => t >= s.start && t <= s.end);
        if (hit >= 0) onClickSub(hit); else onSeek(t);
      }} />
  );
}

/* ---------- Transport bar ---------- */
function TransportBar({ playing, cur, duration, onPlay, onStop, onSeek, loop, onLoop, speed, setSpeed }) {
  const seekRef = uR(null);
  const pct = (cur / duration) * 100;
  const seek = (e) => { const r = seekRef.current.getBoundingClientRect(); onSeek(((e.clientX - r.left) / r.width) * duration); };
  return (
    <div className="transport">
      <button className="tbtn play" onClick={onPlay}>{playing ? "❚❚" : "▶"}</button>
      <button className="tbtn" onClick={onStop}>■</button>
      <span className="vsep"></span>
      <span className="tc-now">{window.fmtTC(cur)}</span>
      <span className="tc-dur">/ {window.fmtClock(duration)}</span>
      <div className="seek" ref={seekRef} onClick={seek}>
        <div className="fill" style={{ width: pct + "%" }}></div>
        <div className="knob" style={{ left: pct + "%" }}></div>
      </div>
      <span className="vsep"></span>
      <span style={{ color: "var(--muted)", fontSize: 13 }}>🔊</span>
      <div className="vol"><div className="fill" style={{ width: "72%" }}></div></div>
      <span className="vsep"></span>
      <select className="select speed-sel" style={{ width: 74, height: 28 }} value={speed} onChange={(e) => setSpeed(e.target.value)}>
        {window.SPEEDS.map(s => <option key={s} value={s}>{s}</option>)}
      </select>
      <span className="vsep"></span>
      <button className={"tbtn" + (loop ? " on" : "")} onClick={onLoop} title="Loop sul sottotitolo selezionato">⟳</button>
      <span className="vsep"></span>
      <span className="jkl">J·K·L</span>
    </div>
  );
}

/* ---------- Preview area ---------- */
function PreviewArea(props) {
  const { file, subs, cur, duration, selRow, severities, onSeek, onClickSub, transport } = props;
  const isVideo = file && ["MP4", "MOV", "MKV", "AVI", "M4V", "WEBM"].includes(file.ext);
  const activeSub = subs.find(s => cur >= s.start && cur <= s.end);
  return (
    <div className="preview">
      <div className="tc-bar">
        <span className="tc-now">{window.fmtTC(cur)}</span>
        <span className="tc-dur">durata {window.fmtClock(duration)}</span>
        <span className="tc-tag">{isVideo ? "◇ Anteprima video" : "∿ Forma d’onda"} · {file ? file.ext : "—"}</span>
      </div>
      {isVideo ? (
        <div className="video-stage">
          <div className="video-frame"></div>
          <div className="video-ph">
            <div className="pl-ic">▶</div>
            <div>video preview · {file.name}</div>
          </div>
          {activeSub && <div className="sub-overlay">{activeSub.text}</div>}
        </div>
      ) : (
        <div className="wave-stage">
          <WaveformCanvas subs={subs} duration={duration} cur={cur} selRow={selRow} severities={severities} onSeek={onSeek} onClickSub={onClickSub} />
        </div>
      )}
      <TransportBar {...transport} cur={cur} duration={duration} onSeek={onSeek} />
    </div>
  );
}

/* ---------- Inspector ---------- */
function Inspector({ collapsed, sub, row, total, diag, onField, onShift }) {
  if (collapsed) return <div className="inspector collapsed"></div>;
  if (!sub) {
    return (
      <div className="inspector">
        <div className="insp-title">Ispettore</div>
        <div className="insp-empty">Nessuna selezione.<br />Seleziona una riga nella timeline.</div>
      </div>
    );
  }
  const dur = sub.end - sub.start;
  const c = window.cps(sub);
  const cpsSev = c > 20 ? "error" : c > 17 ? "warning" : "ok";
  const chars = sub.text.length;
  return (
    <div className="inspector">
      <div className="insp-title">Ispettore</div>
      <div className="insp-body">
        <div className="insp-head">Riga {row + 1} <span style={{ color: "var(--muted)", fontWeight: 400 }}>/ {total}</span></div>

        <div>
          <div className="insp-sec-t">Timing</div>
          <div className="stack" style={{ gap: 10 }}>
            <div className="tfield"><span className="label">Inizio</span>
              <div className="spin"><input value={window.fmtTC(sub.start)} onChange={() => {}} /></div></div>
            <div className="tfield"><span className="label">Fine</span>
              <div className="spin"><input value={window.fmtTC(sub.end)} onChange={() => {}} /></div></div>
            <div className="offsets">
              {[-100, -10, 10, 100].map(d => (
                <button className="offset" key={d} onClick={() => onShift(d)}>{d > 0 ? "+" : ""}{d}ms</button>
              ))}
            </div>
            <div className="calc-row">
              <span className="calc">Durata <b>{dur.toFixed(3)} s</b></span>
              <span className="calc">CPS <b className={"cps-v " + cpsSev}>{c.toFixed(1)}</b></span>
            </div>
          </div>
        </div>

        <div className="insp-divider"></div>

        <div>
          <div className="insp-sec-t">Testo</div>
          <textarea className="insp-text" value={sub.text} onChange={(e) => onField("text", e.target.value)}></textarea>
          <div className="insp-meta">
            <span>{chars} caratteri</span>
            <span className="kbd">⌘↵ per applicare</span>
          </div>
        </div>

        <div className="insp-divider"></div>

        <div>
          <div className="insp-sec-t">Diagnostica</div>
          <div className="stack" style={{ gap: 7 }}>
            {diag.issues.length === 0
              ? <div className="issue ok"><span className="dot"></span><span className="m">Nessun problema rilevato.</span></div>
              : diag.issues.map((is, i) => (
                <div className={"issue " + is.sev} key={i}><span className="dot"></span><span className="m">{is.msg}</span></div>
              ))}
          </div>
        </div>
      </div>
    </div>
  );
}

/* ---------- Find & Replace (dialog non modale) ---------- */
function buildRegex(q, opts) {
  if (!q) return null;
  let pat = opts.regex ? q : q.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  if (opts.whole) pat = "\\b" + pat + "\\b";
  try { return new RegExp(pat, opts.caseSensitive ? "g" : "gi"); } catch (e) { return null; }
}

function FindReplace({ subs, onClose, onSelectRow, onReplaceRow }) {
  const [q, setQ] = uS("");
  const [rep, setRep] = uS("");
  const [cs, setCs] = uS(false);
  const [whole, setWhole] = uS(false);
  const [rx, setRx] = uS(false);
  const [idx, setIdx] = uS(-1);
  const re = buildRegex(q, { caseSensitive: cs, whole, regex: rx });
  const matches = [];
  if (re) subs.forEach((s, i) => { const m = s.text.match(re); if (m) matches.push({ row: i, n: m.length }); });
  const totalOcc = matches.reduce((a, m) => a + m.n, 0);

  function next() {
    if (!matches.length) return;
    const ni = (idx + 1) % matches.length; setIdx(ni); onSelectRow(matches[ni].row);
  }
  function replaceOne() {
    if (!re || idx < 0 || !matches[idx]) { next(); return; }
    const row = matches[idx].row;
    onReplaceRow(row, subs[row].text.replace(re, rep));
  }
  function replaceAll() {
    if (!re) return;
    matches.forEach((m) => onReplaceRow(m.row, subs[m.row].text.replace(re, rep)));
  }

  return (
    <div className="fr-dialog">
      <div className="fr-head"><span>Trova e sostituisci</span><button className="fr-x" onClick={onClose}>×</button></div>
      <div className="fr-body">
        <div className="fr-field"><input autoFocus className="fr-input" placeholder="Trova…" value={q}
          onChange={(e) => { setQ(e.target.value); setIdx(-1); }}
          onKeyDown={(e) => { if (e.key === "Enter") next(); if (e.key === "Escape") onClose(); }} /></div>
        <div className="fr-field"><input className="fr-input" placeholder="Sostituisci con…" value={rep} onChange={(e) => setRep(e.target.value)} /></div>
        <div className="fr-opts">
          <button className={"fr-opt" + (cs ? " on" : "")} onClick={() => setCs(!cs)} title="Maiuscole/minuscole">Aa</button>
          <button className={"fr-opt" + (whole ? " on" : "")} onClick={() => setWhole(!whole)} title="Parola intera">W</button>
          <button className={"fr-opt" + (rx ? " on" : "")} onClick={() => setRx(!rx)} title="Espressione regolare">.*</button>
          <span className="fr-count">{q ? `${totalOcc} occorrenze · ${matches.length} sottotitoli` : "—"}</span>
        </div>
        <div className="fr-actions">
          <button className="btn sm ghost wfull" onClick={next} disabled={!matches.length}>Trova successivo ↵</button>
        </div>
        <div className="fr-actions">
          <button className="btn sm ghost" onClick={replaceOne} disabled={!matches.length}>Sostituisci</button>
          <button className="btn sm primary" style={{ height: 32, minHeight: 0 }} onClick={replaceAll} disabled={!matches.length}>Sostituisci tutti</button>
        </div>
      </div>
    </div>
  );
}

/* ---------- Subtitle timeline ---------- */
function SubtitleTimeline({ subs, severities, selRow, onSelect, inspectorOpen, onToggleInspector, onImport, onFind }) {
  return (
    <div className="tl">
      <div className="tl-main">
        <div className="tl-toolbar">
          <button className="tlb" title="Annulla ⌘Z"><span className="ico">↶</span></button>
          <button className="tlb" title="Ripristina ⌘⇧Z"><span className="ico">↷</span></button>
          <span className="tlb-sep"></span>
          <button className="tlb" title="Dividi ⌘K"><span className="ico">÷</span> Dividi</button>
          <button className="tlb" title="Unisci ⌘M"><span className="ico">⊔</span> Unisci</button>
          <button className="tlb" title="Elimina ⌘⇧K"><span className="ico">×</span> Elimina</button>
          <span className="tlb-sep"></span>
          <button className="tlb" onClick={onImport} title="Importa file…"><span className="ico">⤓</span> Importa</button>
          <span className="tlb-sp"></span>
          <button className="tlb" onClick={onFind} title="Trova e sostituisci ⌘F"><span className="ico">⌕</span> Trova</button>
          <button className={"tlb" + (inspectorOpen ? " on" : "")} onClick={onToggleInspector} title="Ispettore ⌘I"><span className="ico">▤</span> Ispettore</button>
        </div>
        <div className="tl-scroll">
          <table className="grid">
            <thead>
              <tr><th>#</th><th>Start</th><th>End</th><th>Durata</th><th>CPS</th><th style={{ width: "100%" }}>Testo</th></tr>
            </thead>
            <tbody>
              {subs.map((s, i) => {
                const c = window.cps(s);
                return (
                  <tr key={i} className={(i === selRow ? "sel " : "") + "sev-" + severities[i]} onClick={() => onSelect(i)}>
                    <td className="c-n"><span className={"sev-chip " + severities[i]}></span>{i + 1}</td>
                    <td className="c-t">{window.fmtTC(s.start)}</td>
                    <td className="c-t">{window.fmtTC(s.end)}</td>
                    <td className="c-d">{window.fmtDur(s.end - s.start)}</td>
                    <td className={"c-cps" + (c > 20 ? " bad" : "")}>{c.toFixed(1)}</td>
                    <td className="c-x">{s.text}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

/* ---------- Placeholder (editor vuoto) ---------- */
function PlaceholderWidget({ onGoTranscription, onImport }) {
  return (
    <div className="placeholder fade">
      <div className="ph-card">
        <div className="ph-icn">◻</div>
        <div className="ph-t">Nessuna trascrizione</div>
        <div className="ph-s">Apri l’editor da una trascrizione completata, oppure importa un progetto <span className="mono">.v2srt</span> o un file <span className="mono">.srt</span> esistente.</div>
        <div className="row gap10 mt8">
          <button className="btn primary" onClick={onGoTranscription}>Vai a Trascrizione</button>
          <button className="btn ghost" onClick={onImport}>Apri file…</button>
        </div>
      </div>
    </div>
  );
}

/* ---------- WorkspaceWidget ---------- */
function WorkspaceWidget({ subs, file, inline, onImport, onEdit }) {
  const [selRow, setSel] = uS(0);
  const [cur, setCur] = uS(0);
  const [playing, setPlaying] = uS(false);
  const [loop, setLoop] = uS(false);
  const [speed, setSpeed] = uS("1×");
  const [inspectorOpen, setInsp] = uS(true);
  const [findOpen, setFind] = uS(false);
  const duration = file ? file.duration : 184.2;
  const severities = uM(() => subs.map((s, i) => window.rowDiag(s, subs[i - 1]).sev), [subs]);

  uE(() => {
    if (!playing) return;
    const rate = parseFloat(speed) || 1;
    const id = setInterval(() => {
      setCur((c) => {
        let n = c + 0.05 * rate;
        if (loop && subs[selRow]) { if (n > subs[selRow].end) n = subs[selRow].start; }
        if (n >= duration) { n = 0; }
        return n;
      });
    }, 50);
    return () => clearInterval(id);
  }, [playing, speed, loop, selRow, subs, duration]);

  // follow playhead → select current sub
  uE(() => {
    if (!playing) return;
    const i = subs.findIndex(s => cur >= s.start && cur <= s.end);
    if (i >= 0 && i !== selRow) setSel(i);
  }, [cur, playing]);

  // ⌘F → Trova e sostituisci
  uE(() => {
    const onKey = (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "f") { e.preventDefault(); setFind(true); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const sub = subs[selRow];
  const diag = sub ? window.rowDiag(sub, subs[selRow - 1]) : { issues: [] };
  const transport = { playing, onPlay: () => setPlaying(p => !p), onStop: () => { setPlaying(false); setCur(0); }, loop, onLoop: () => setLoop(l => !l), speed, setSpeed };

  return (
    <div className="ws fade">
      {inline && (
        <div className="inline-prog">
          <div className="spinner" style={{ width: 13, height: 13 }}></div>
          <span className="ipt">Trascrizione in corso… {inline.pct}%</span>
          <div className="bar"><i style={{ width: inline.pct + "%" }}></i></div>
        </div>
      )}
      <div className="ws-top">
        <PreviewArea file={file} subs={subs} cur={cur} duration={duration} selRow={selRow}
          severities={severities} onSeek={(t) => setCur(Math.max(0, Math.min(duration, t)))}
          onClickSub={(i) => { setSel(i); setCur(subs[i].start); }} transport={transport} />
      </div>
      <div className="ws-divider"></div>
      <div className="ws-bottom">
        <div style={{ display: "flex", flex: 1, minHeight: 0 }}>
          <SubtitleTimeline subs={subs} severities={severities} selRow={selRow}
            onSelect={(i) => { setSel(i); setCur(subs[i].start); }}
            inspectorOpen={inspectorOpen} onToggleInspector={() => setInsp(o => !o)} onImport={onImport}
            onFind={() => setFind(true)} />
          <Inspector collapsed={!inspectorOpen} sub={sub} row={selRow} total={subs.length} diag={diag}
            onField={(f, v) => onEdit(selRow, f, v)} onShift={(d) => onEdit(selRow, "shift", d)} />
        </div>
      </div>
      {findOpen && (
        <FindReplace subs={subs} onClose={() => setFind(false)}
          onSelectRow={(i) => { setSel(i); setCur(subs[i].start); }}
          onReplaceRow={(i, txt) => onEdit(i, "text", txt)} />
      )}
    </div>
  );
}

Object.assign(window, { WorkspaceWidget, PlaceholderWidget });
