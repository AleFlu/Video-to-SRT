# CLAUDE.md — Video → SRT v2

Dev guide for continuing this project (incl. Claude Code in VS Code).

---

## Progetto

macOS desktop app: **trascrizione automatica italiana** video/audio + **editor SRT professionale**.

Stack: **PySide6** + **faster-whisper** (CTranslate2) + model **large-v3**.
Refactored from `Try1/` (customtkinter) → `Try2/` workspace stile DaVinci/Premiere: sidebar, multi-panel, QDockWidget, editor con undo/redo.
Step 1+2 completi. Step 3 completo. Step 4 = roadmap.

---

## Struttura

```
Try2/
├── main.py                   # Entry point: splash Qt + thread loader + MainWindow
├── engine.py                 # Core trascrizione — non modificare senza motivo
├── pyi_rth_threads.py        # PyInstaller runtime hook
├── requirements.txt
├── setup_mac.sh              # Setup venv+deps+model
├── build_mac.py              # PyInstaller build → .app + .dmg
├── install.sh                # Installer completo (--run / --app / --dmg)
├── assets/
│   ├── make_icon.py          # Genera app.icns + app_512.png
│   ├── app.icns              # Icona macOS (generata)
│   └── app_512.png           # Preview PNG 512px
├── core/
│   ├── subtitle_model.py     # dataclass Subtitle + SubtitleProject
│   ├── subtitle_table_model.py  # QAbstractTableModel custom (6 col, validazione, issues)
│   ├── undo_commands.py      # QUndoCommand: Edit/Split/Merge/Delete/ReplaceAll
│   ├── srt_io.py             # write_srt, format_timestamp_srt, wrap_subtitle_text
│   ├── transcription_worker.py  # QThread → engine.transcribe()
│   └── audio_player.py       # QMediaPlayer + QAudioOutput wrapper
└── ui/
    ├── theme.py              # Dark palette + Qt stylesheet globale
    ├── main_window.py        # QMainWindow: sidebar + QStackedWidget + menu + statusbar
    ├── sidebar.py            # Nav 5 sezioni
    ├── source_panel.py       # Drop zone drag&drop + DepsBanner (ffmpeg/model warning)
    ├── settings_panel.py     # Modello/VAD/denoise/accuracy/beam
    ├── transcribe_panel.py   # Progress + log + start/stop
    ├── editor_panel.py       # ⭐ Core: inner QMainWindow, tabella, inspector dock, waveform
    ├── inspector_widget.py   # Editor dettaglio riga selezionata
    ├── find_replace_dialog.py  # Find & Replace (regex, case, whole word)
    ├── transport_bar.py      # Player controls: play/pause/stop/seek/volume/rate/loop
    ├── waveform_widget.py    # Waveform numpy+soundfile, overlay subtitles, playhead
    └── export_panel.py       # Salva SRT + open-in-Finder
```

`Try1/` = v1 customtkinter, backup, non toccare.

---

## Architettura

### Regole core/ui
- `core/` non importa da `ui/`
- `engine.py` indipendente

### Data flow trascrizione
```
SourcePanel.file_loaded → MainWindow._on_file_loaded → project.source_path + TranscribePanel.set_source
SettingsPanel.next_requested → MainWindow._go_transcribe → TranscribePanel.set_settings + sidebar.select("transcribe")
TranscribePanel.start → TranscriptionWorker (QThread) → engine.transcribe + post_process_timing → .finished(segments)
MainWindow._on_transcription_done → project.load_from_segments → EditorPanel.load_subtitles → sidebar.select("editor")
```

### Data flow editing
Tutte modifiche passano da `QUndoStack` di EditorPanel:
- Tabella edit → `SubtitleTableModel.setData` → `edit_handler` → `EditFieldCommand` → push stack
- Inspector → emette segnali `(row, new_value)` → EditorPanel crea `QUndoCommand`
- `apply_edit_raw(row, col, value)` = unica via per modificare model senza handler (usata da undo/redo)

### Inspector = view, non controller
Non modifica model. Emette segnali → EditorPanel decide. Evita loop infiniti su dataChanged.

### Issues detection
- `row_issues(row)` → lista problemi (overlap, end≤start, CPS>20, durata<0.5s, testo vuoto)
- `row_severity(row)` → `"error"|"warning"|"ok"` → colora tabella + statusbar

### Timestamp parsing
`parse_timestamp(str)` accetta `HH:MM:SS.mmm`, `MM:SS.mmm`, `MM:SS`, secondi decimali. `None` se non parsabile → `setData` scarta.

---

## Step completati

### Step 1 — Scaffolding
Struttura PySide6, splash, sidebar+panels, drop zone, settings panel, QThread worker, export SRT, menubar, statusbar.

### Step 2 — Editor professionale
QAbstractTableModel 6 col, editing inline, Inspector QDockWidget, QUndoStack (5 comandi, merge typing), Find & Replace, diagnostica auto (rosso/giallo/tooltip), Split/Merge/Delete shortcut, menu Modifica, conferma chiusura non salvato, ⌘1-5 nav.

### Step 3 — Waveform + player
`audio_player.py`, `transport_bar.py`, `waveform_widget.py` — dock waveform inferiore, shortcut Space/J/K/L/←/→.

### Step 4 — Polish + distribuzione (parziale)
- `build_mac.py` ✅ — PyInstaller → .app + .dmg, code signing, Info.plist patch
- `install.sh` ✅ — installer completo (venv, ffmpeg, model download, build)
- `assets/app.icns` ✅ — icona generata con QPainter puro
- Icona Dock macOS ✅ — `NSApp.setApplicationIconImage_()` via pyobjc
- UI cosmetic polish ✅ — sidebar unicode, dropzone QPainter, toolbar tooltip, inspector fix

### Step 5 — DaVinci-style layout ✅ COMPLETO

Obiettivo: abbandonare il modello sidebar+stack e adottare un layout **a pannelli fissi sempre visibili**, ispirato a DaVinci Resolve / Premiere Pro.

#### Layout target (fullscreen, tre fasce orizzontali):

```
┌─────────────────────────────────────────────────────────────┐
│  MENU BAR  (File / Modifica / Visualizza / Aiuto)           │
├──────────┬──────────────────────────────┬───────────────────┤
│          │                              │                   │
│  MEDIA   │     ANTEPRIMA / WAVEFORM     │   INSPECTOR       │
│  BROWSER │     (area centrale grande)   │   (timing+testo)  │
│  (file   │                              │                   │
│  caricati│                              │                   │
│  recenti)│                              │                   │
├──────────┴──────────────────────────────┴───────────────────┤
│  TRANSPORT BAR  (play/pause/seek/timecode/rate/volume)       │
├─────────────────────────────────────────────────────────────┤
│  SUBTITLE TIMELINE  (tabella sottotitoli — area principale)  │
│  con toolbar compatta sopra (undo/redo/split/merge/find)     │
└─────────────────────────────────────────────────────────────┘
│  STATUS BAR  (n sottotitoli · issues · modified · timecode)  │
└─────────────────────────────────────────────────────────────┘
```

#### File da creare / modificare:

- **`ui/main_window.py`** — abbandonare QStackedWidget+sidebar. Nuovo layout: QSplitter verticale (top area + timeline area). Top area = QSplitter orizzontale (media_browser | preview_area | inspector). Il flusso source→settings→transcribe diventa un **wizard dialog** modale o pannello collassabile sopra la timeline.
- **`ui/workspace.py`** (nuovo) — widget centrale che orchestra i tre pannelli. Usa `QSplitter` con `setStretchFactor` per proporzioni DaVinci (20/55/25).
- **`ui/media_browser.py`** (nuovo) — pannello sinistra: lista file recenti (QListWidget), drag su timeline, miniatura. Sostituisce SourcePanel standalone.
- **`ui/preview_area.py`** (nuovo) — pannello centrale: waveform grande + timecode overlay + subtile preview centrata. Attuale `waveform_widget.py` diventa component interno.
- **`ui/subtitle_timeline.py`** (nuovo) — pannello inferiore: tabella sottotitoli con toolbar compatta integrata sopra. Estrae la logica da `editor_panel.py`.
- **`ui/setup_wizard.py`** (nuovo) — dialogo modale (o sheet macOS-style) per il flusso source→settings→transcribe. Si apre con ⌘O o drag file sul media browser.
- **`ui/toolbar_main.py`** (nuovo) — toolbar globale densa stile DaVinci sopra il workspace (non dentro ogni pannello).
- **`ui/transport_bar.py`** — espandere: timecode display (HH:MM:SS:FF), loop range, JKL indicator visivo.
- **`ui/theme.py`** — aggiornare colori per pannelli distinti: `BG_PANEL_TOP`, `BG_PANEL_BOTTOM`, `BG_TIMELINE`. Separatori tra pannelli: 2px `#111114`.

#### Architettura nuovo MainWindow:

```python
MainWindow (QMainWindow)
  └── central: WorkspaceWidget (QSplitter vertical)
        ├── top_area: QSplitter horizontal
        │     ├── MediaBrowser (QWidget, fixedWidth=220)
        │     ├── PreviewArea (QWidget, stretch=3)
        │     └── InspectorWidget (QWidget, fixedWidth=280)
        └── bottom_area: QSplitter vertical
              ├── TransportBar (fixedHeight=48)
              └── SubtitleTimeline (stretch=1)
                    └── inner toolbar (QToolBar, compact, movable=False)
```

#### Wizard modale per trascrizione:

```python
SetupWizard (QDialog, modal)
  Page 1 — Sorgente: DropZone + file info
  Page 2 — Impostazioni: modello/VAD/denoise/beam
  Page 3 — Trascrizione: progress + log + stop
```
Dopo wizard → `transcription_finished` → `SubtitleTimeline.load_subtitles` + `PreviewArea.load_audio`.

#### Proporzioni target (ispirate a DaVinci):
- Top area height: ~40% finestra. Bottom (timeline): ~60%.
- MediaBrowser width: 220px fissi. Inspector: 280px fissi. Preview: resto.
- Transport bar: 48px fissi.
- Toolbar globale: 36px fissi.

#### Trappole da evitare:
- `QDockWidget` nell'inner QMainWindow → mantenere per inspector (già funzionante). Nel nuovo layout, inspector è widget fisso nel splitter, non dock.
- Salvare geometria splitter con `QSettings` per persistenza tra sessioni.
- Il wizard non deve bloccare il thread UI durante trascrizione — usa QThread esistente in `transcription_worker.py`.

---

## Shortcut

| Shortcut | Azione |
|---|---|
| ⌘Z / ⌘⇧Z | Undo / Redo |
| ⌘K | Dividi al cursore |
| ⌘M | Unisci al successivo |
| ⌘⇧K | Elimina selezionati |
| ⌘F | Find & Replace |
| ⌘I | Toggle Inspector |
| ⌘⇧W | Toggle Waveform |
| ⌘S | Esporta |
| ⌘O | Apri file |
| ⌘1–⌘5 | Naviga sezioni |
| Space | Play / Pausa |
| K | Pausa |
| J | Seek −2s |
| L | Play |
| ← / → | Seek ±1s |
| ⇧← / ⇧→ | Subtitle prec./succ. |

---

## Setup

```bash
cd Try2
./install.sh --run      # setup + avvia dev
./install.sh --app      # setup + build .app
./install.sh --dmg      # setup + .app + .dmg
source venv/bin/activate && python main.py  # dev diretto
```

---

## Convenzioni codice

- **Lingua**: UI/docstring/commenti in italiano. Var/func/classi in inglese.
- Type hints + `from __future__ import annotations`. No black/isort. 4 spazi, ~100 char.
- Import order: stdlib → PySide6 → core → ui.
- Naming: `snake_case` per metodi custom, `camelCase` solo per override Qt API.
- Nuovo pannello: `QWidget` con `objectName="contentPanel"`.
- Card: `QFrame` con `objectName="card"`.
- Pulsante primario: `objectName="primary"`. Distruttivo: `objectName="danger"`.

---

## Trappole architetturali

**QMainWindow interno in EditorPanel**: QDockWidget richiedono QMainWindow come parent. Inner QMainWindow (`self._inner`) = tabella + dock inspector localizzati. Tecnica Qt riconosciuta.

**Inspector passivo**: se modificasse model direttamente → dataChanged → refresh inspector → editingFinished → commit → loop infinito. Segnali verso EditorPanel rompono ciclo.

**Timestamp in 2 posti**: `srt_io.format_timestamp_srt` → SRT ufficiale (`HH:MM:SS,mmm`, virgola). `subtitle_table_model.format_timestamp` → UI (`MM:SS.mmm`, punto). Standard SRT vuole virgola, UI vuole punto+compatto.

**`replace(sub)` in QUndoCommand**: `dataclasses.replace()` = copia immutabile. Senza copia, modifiche successive contaminano snapshot undo.

**Worker NON fa write_srt**: segmenti tornano vivi alla UI per editing. Solo ExportPanel scrive SRT. `engine.run_pipeline` esiste per compatibilità CLI.

**engine.py**: non modificare pipeline esistente. Estendere ok, cambiare richiede test su v1+v2.

**PyInstaller + Qt**: serve `--collect-all PySide6 --collect-all shiboken6 --collect-all ctranslate2`. Vedi `build_mac.py`.

**Dock icon macOS**: `setWindowIcon` cambia solo finestra. `NSApp.setApplicationIconImage_()` via pyobjc-framework-Cocoa = icona Dock persistente anche in dev mode.

**DepsBanner visibilità**: banner usa `QFrame { background-color: #hex }` (no rgba) per battere `QWidget { background-color }` del tema globale. Child QLabel devono avere `background: transparent`.

---

## Debug

- `engine.py` ha print abbondanti → utili per bug report modello/CTranslate2
- `transcribe_panel.py` log utente = primo posto da guardare per errori trascrizione
- Crash UI → `python main.py` da terminale → PySide6 stampa traceback completo

---

## Checklist ripresa lavoro

- [ ] `python main.py` — verifica che parta
- [ ] Apri `ui/editor_panel.py` — file più denso, chiave per capire orchestrazione
- [ ] Ogni feature che modifica subtitles → passa da QUndoStack

## TODO Step 5 — DaVinci Layout (implementazione)

Ordine consigliato per implementare senza rompere l'app a ogni step:

### Fase A — Preparazione (non rompe nulla)
- [x] **A1** Creare `ui/setup_wizard.py` — dialogo modale QDialog con 3 pagine (Sorgente / Impostazioni / Trascrizione). Estrarre logica da `source_panel.py`, `settings_panel.py`, `transcribe_panel.py`. Segnale `wizard_done(segments, source_path)` al termine.
- [x] **A2** Creare `ui/subtitle_timeline.py` — estrarre tabella + toolbar da `editor_panel.py`. `SubtitleTimeline` eredita da QWidget, contiene QMainWindow interno (per QDockWidget). Stessa API pubblica: `load_subtitles`, `load_audio`, `get_subtitles`, `export_action`.
- [x] **A3** Creare `ui/media_browser.py` — QListWidget con file recenti (max 20, salvati in QSettings). Drag & drop su timeline o doppio-click → apre wizard. Emette `file_selected(path)`.
- [x] **A4** Creare `ui/preview_area.py` — wrapper per `waveform_widget.py` + timecode overlay (QLabel in overlay, font monospace grande). Emette `seek_requested`.

### Fase B — Workspace (layout principale)
- [x] **B1** Creare `ui/workspace.py` — `WorkspaceWidget(QWidget)` con QSplitter vertical. Top: QSplitter horizontal (MediaBrowser 220px | PreviewArea stretch | InspectorWidget 280px). Bottom: SubtitleTimeline + TransportBar (48px fissi sopra timeline).
- [x] **B2** Modificare `ui/main_window.py` — sostituire `QStackedWidget + sidebar` con `WorkspaceWidget` come centralWidget. Mantenere QMenuBar, QStatusBar, QUndoStack. ⌘O → apre SetupWizard. `wizard_done` → carica audio in PreviewArea + subtitles in SubtitleTimeline.
- [x] **B3** `ui/theme.py` — aggiungere colori pannello: `BG_PANEL = "#1e1e24"`, `BG_TIMELINE = "#16161b"`, separatori `#111114`. Toolbar globale altezza 36px.

### Fase C — Polish
- [x] **C1** Persistenza geometria: `QSettings("VideoSRT", "v2")` → salva/ripristina splitter sizes, window geometry, dock states.
- [x] **C2** `ui/transport_bar.py` — timecode HH:MM:SS.mmm (font monospace, ore mostrate solo se >0).
- [x] **C3** Export VTT/TXT/ASS — `core/srt_io.py` + `ui/export_panel.py` con QComboBox formato.
- [x] **C4** Formato `.v2srt` — `core/v2srt_io.py` JSON. ⌘O apre video o progetto. ⌘⇧S salva progetto.

---

## TODO Step 6 — UX Redesign: Home → Progress → Editor

### Decisioni UX (confermate)
- Un progetto per volta (architettura multi-sessione prevista per il futuro)
- No media browser nel layout editor — menu File → "Apri recenti"
- Inspector collassabile (bottone toggle nella toolbar)
- Video player se file supportato da Qt Multimedia, waveform fallback altrimenti
- Shortcut JKL previsti, non prioritari ora
- Export: salva file (SRT/VTT/TXT/ASS/.v2srt) — nient'altro per ora

### Flusso app (3 stati)

```
[HOME]  ──Avvia──▶  [PROGRESS]  ──Done──▶  [EDITOR]
          ◀──Stop──              ◀──"Nuova"──
```

- App parte → HOME (sempre, anche se esistono recenti)
- HOME: drag&drop + impostazioni compatte + bottone Avvia
- PROGRESS: progress bar + log + Stop (torna a HOME)
- EDITOR: workspace DaVinci — preview video/waveform + timeline sottotitoli + inspector collassabile
- ⌘O da EDITOR → se modifiche non salvate chiede conferma → HOME con path pre-caricato
- ⌘O con file .v2srt → carica direttamente in EDITOR (salta HOME/PROGRESS)
- Menu File → "Apri recenti" (max 10, QSettings)

### Architettura

```
MainWindow (QMainWindow)
  ├── QMenuBar  (File | Modifica | Vista | Aiuto)
  ├── central: QStackedWidget
  │     ├── [0] HomeWidget        # drop + settings + avvia
  │     ├── [1] ProgressWidget    # progress + log + stop
  │     └── [2] WorkspaceWidget   # editor DaVinci
  └── QStatusBar  (sempre visibile, contenuto varia per stato)
```

### WorkspaceWidget (editor) — layout corretto

```
WorkspaceWidget
  └── QSplitter vertical
        ├── top: QSplitter horizontal
        │     ├── PreviewArea   (video player o waveform, stretch=3)
        │     └── [inspector dock dentro SubtitleTimeline — non qui]
        └── bottom: SubtitleTimeline
              ├── QToolBar compatta (undo/redo/split/merge/find/toggle-inspector)
              ├── QTableView  (sottotitoli)
              └── QDockWidget Inspector (destra, collassabile)
```

**Cambio chiave**: `InspectorWidget` vive SOLO dentro `SubtitleTimeline` come QDockWidget.
Rimosso dal pannello top del workspace. Rimosso `MediaBrowser` dal layout editor.

### Fix bug critici (Fase E)

| # | Bug | Fix |
|---|---|---|
| E1 | Due AudioPlayer separati (PreviewArea + SubtitleTimeline) → shortcut e transport desincroni | Rimuovere player interno da SubtitleTimeline. Aggiungere `set_player(p)`. Workspace: `timeline.set_player(preview.player)` |
| E2 | InspectorWidget duplicato (workspace top + dock SubtitleTimeline) | Rimuovere da workspace._hsplit. Lasciare solo dock in SubtitleTimeline |
| E3 | Doppia connessione inspector → doppio push undo stack | Rimuovere connect inspector da workspace._wire (già in SubtitleTimeline._wire) |
| E4 | Video player: usare QVideoWidget per .mp4/.mkv/.mov/.avi; WaveformWidget per .mp3/.wav/.flac | PreviewArea.load_media(path): rileva ext → mostra video o waveform |

### Fasi implementazione

#### Fase D — Ristrutturazione MainWindow ✅ COMPLETO
- [x] **D1** `ui/home_widget.py` — DropZone grande + DepsBanner + impostazioni (modello/VAD/denoise/beam) + bottone Avvia. Segnale `start_requested(path: str, settings: dict)`.
- [x] **D2** `ui/progress_widget.py` — progress bar + log + Stop. `start(path, settings)` avvia QThread. Segnali `transcription_done(segments, path)` e `transcription_cancelled()`.
- [x] **D3** Riscrivere `ui/main_window.py` — QStackedWidget. Gestisce transizioni, menu File (Apri/Recenti/Salva/Esporta/Nuova/Esci), status bar contestuale.

#### Fase E — Fix editor ✅ COMPLETO
- [x] **E1** Unificare AudioPlayer: `SubtitleTimeline.set_player(p)` API. Workspace chiama `timeline.set_player(preview.player)`.
- [x] **E2** Rimuovere InspectorWidget e MediaBrowser da workspace. Inspector esposto come alias `workspace.inspector → timeline.inspector`.
- [x] **E3** Rimosso wiring inspector duplicato da workspace (gestito solo da SubtitleTimeline._wire).
- [x] **E4** `PreviewArea.load_media(path)` — QVideoWidget per video, WaveformWidget fallback per audio.

#### Fase F — Polish (prossimo step)
- [ ] **F1** Placeholder timeline vuota: "Nessuna trascrizione — usa File → Apri"
- [ ] **F2** "Apri recenti" nel menu File (QSettings, max 10) ← già implementato in D3
- [ ] **F3** Status bar HOME mostra stato dipendenze ffmpeg/model ← già in DepsBanner

---

## TODO Step 7 — UX Tab: Trascrizione | Editor

### Decisioni UX (confermate con utente)

| Decisione | Scelta |
|---|---|
| Navigazione | Tab bar custom (2 tab fisse sempre visibili) |
| Post-trascrizione | Rimane in tab Trascrizione, mostra ResultWidget |
| Import dall'editor | Qualsiasi file; video → barra inline progress |
| Seconda trascrizione con editor pieno | Dialog conferma prima di sovrascrivere |
| Anteprima stale | ResultWidget mostra originale + badge giallo se editor diverge |
| Editor vuoto | Tab cliccabile, PlaceholderWidget con bottoni orientativi |
| Stop trascrizione | Torna a sotto-stato Drop |
| Player in Home/Result | Nessuno. Player solo nell'editor |

---

### Architettura target

```
MainWindow (QMainWindow)
  ├── QMenuBar
  ├── TabBar (QWidget custom, 2 tab: "Trascrizione" | "Editor [●]")
  ├── central: QStackedWidget
  │     ├── [0] TranscriptionTab (QStackedWidget interno, 3 sotto-stati)
  │     │     ├── [0.0] HomeWidget      drop + settings + [Avvia]
  │     │     ├── [0.1] ProgressWidget  progress + log + [Stop]
  │     │     └── [0.2] ResultWidget    anteprima + [Esporta] + [Apri editor] + badge
  │     └── [1] EditorTab (QWidget wrapper)
  │           ├── InlineProgressBar (QWidget, h=24px, hidden di default)
  │           ├── QStackedWidget interno
  │           │     ├── [1a] PlaceholderWidget  (se nessun sottotitolo)
  │           │     └── [1b] WorkspaceWidget    (preview + timeline + inspector)
  │           └── bottone [Importa file…] nella toolbar WorkspaceWidget
  └── QStatusBar
```

---

### Casi d'uso → flusso preciso

#### UC1 — Trascrizione lite (nessun editing)
```
Avvio app
→ TabBar: "Trascrizione" attiva, "Editor" inattivo (nessun sub)
→ HomeWidget visibile (Drop + settings)
→ Utente trascina file → [Avvia]
→ ProgressWidget (sotto-stato 0.1)
→ Trascrizione completa → ResultWidget (sotto-stato 0.2)
   - Mostra: "127 sottotitoli · video.mp4"
   - Mostra: anteprima prime 5 righe testo
   - Bottoni: [Esporta SRT ▼] [Apri nell'editor →] [Nuova trascrizione]
→ [Esporta SRT] → FileDialog → salva → done
```

#### UC2 — Trascrizione + editing
```
... (come UC1 fino a ResultWidget)
→ [Apri nell'editor →]
   → SubtitleTimeline.load_subtitles(segments_grezzi)
   → PreviewArea.load_media(source_path)
   → TabBar switcha a "Editor"
   → WorkspaceWidget visibile
→ Utente edita sottotitoli
→ TabBar torna a "Trascrizione" → ResultWidget mostra badge ⚠️ "Versione modificata nell'editor"
→ [Esporta] dall'editor → versione modificata
```

#### UC3 — Import diretto dall'editor
```
Tab "Editor" attiva
→ WorkspaceWidget toolbar: [Importa file…]
→ FileDialog apre (video/audio + .v2srt + .srt)

Caso A — file .v2srt:
→ load_project() → timeline.load_subtitles() + preview.load_media()
→ Nessun progress, aggiornamento istantaneo

Caso B — file video/audio:
→ InlineProgressBar appare sopra WorkspaceWidget (h=24px)
→ QThread TranscriptionWorker parte in background
→ Editor rimane visibile con vecchi sub (o placeholder se vuoto)
→ Trascrizione done → timeline.load_subtitles(nuovi) → InlineProgressBar nascosta
→ ResultWidget in tab Trascrizione aggiornato con nuovi segmenti grezzi

Caso C — file .srt esterno:
→ parse SRT → load_subtitles() direttamente (no trascrizione)
```

#### UC4 — Seconda trascrizione con editor pieno
```
Editor ha 127 sub caricati
→ Utente clicca tab "Trascrizione"
→ Sotto-stato rimane ResultWidget (o Drop se era già tornato lì)
→ [Nuova trascrizione] → controlla: editor ha sub?
   → Sì: QMessageBox.question("Hai 127 sottotitoli non esportati. Continuare?")
      → No: rimane dove stava
      → Sì: HomeWidget.reset() → sotto-stato 0.0 Drop
→ Utente carica nuovo file → Avvia → ...
→ ResultWidget [Apri nell'editor] → SOVRASCRIVE timeline con nuovi sub
```

#### UC5 — Stop trascrizione
```
ProgressWidget visibile
→ [Stop] → worker.request_cancel()
→ _on_cancelled() → HomeWidget.reset() → sotto-stato 0.0 Drop
→ TabBar: "Editor" rimane com'era (sub precedenti intatti se c'erano)
```

#### UC6 — Chiusura con modifiche non salvate
```
closeEvent → controlla workspace.is_modified()
→ Sì: QMessageBox "Modifiche non esportate. Uscire?"
→ No → super().closeEvent()
```

---

### Stato condiviso (MainWindow come unica fonte di verità)

```python
# MainWindow tiene:
self._segments_raw: list        # segmenti grezzi ultima trascrizione (per ResultWidget)
self._source_path: str          # path file sorgente ultima trascrizione
self.project: SubtitleProject   # stato corrente editor

# Regola: segments_raw NON viene modificato dall'editor.
# Editor modifica project.subtitles via undo stack.
# ResultWidget legge segments_raw.
# Badge "modificato" = (segments_raw != project.subtitles) dopo [Apri editor]
```

---

### File da creare / modificare

| File | Azione | Responsabilità |
|---|---|---|
| `ui/result_widget.py` | **Nuovo** | Anteprima testo (prime 5 righe), badge modificato, [Esporta], [Apri editor], [Nuova] |
| `ui/tab_bar.py` | **Nuovo** | QWidget custom: 2 pulsanti tab stilati, segnale `tab_changed(int)`, badge punto ● su Editor se sub presenti |
| `ui/editor_tab.py` | **Nuovo** | Wrapper: InlineProgressBar (nascosta) + QStackedWidget (Placeholder / WorkspaceWidget) + [Importa] |
| `ui/placeholder_widget.py` | **Nuovo** | Widget "Nessuna trascrizione" con [Vai a Trascrizione] e [Importa .v2srt/SRT] |
| `ui/main_window.py` | **Modifica** | Sostituisce QStackedWidget[Home\|Progress\|Editor] con TabBar + nuovo routing |
| `ui/home_widget.py` | **Nessuna modifica** | Già corretto (Drop + settings + [Avvia]) |
| `ui/progress_widget.py` | **Nessuna modifica** | Già corretto |
| `ui/workspace.py` | **Modifica minore** | Aggiunge azione [Importa file…] nella toolbar SubtitleTimeline |
| `ui/subtitle_timeline.py` | **Modifica minore** | Espone `act_import` QAction nella toolbar |

---

### Segnali e connessioni critiche

```
HomeWidget.start_requested(path, settings)
  → MainWindow._on_start_requested()
  → TranscriptionTab → sotto-stato ProgressWidget
  → ProgressWidget.start(path, settings)

ProgressWidget.transcription_done(segments, path)
  → MainWindow._on_transcription_done()
  → self._segments_raw = segments
  → self._source_path = path
  → ResultWidget.show_result(segments, path)
  → TranscriptionTab → sotto-stato ResultWidget

ProgressWidget.transcription_cancelled()
  → MainWindow._go_drop()
  → HomeWidget.reset()
  → TranscriptionTab → sotto-stato HomeWidget

ResultWidget.open_editor_requested()
  → MainWindow._on_open_editor()
  → workspace.load_result(segments_raw, source_path)  [se non già caricati]
  → TabBar → tab Editor

ResultWidget.new_requested()
  → MainWindow._on_new_transcription()
  → _confirm_discard_if_needed()
  → HomeWidget.reset() → sotto-stato Drop

EditorTab.import_requested(path)
  → MainWindow._on_editor_import(path)
  → se .v2srt/.srt → load diretto
  → se video/audio → InlineProgressBar.show() + nuovo QThread worker
  → worker done → workspace.load_result() + InlineProgressBar.hide()
  → aggiorna ResultWidget con nuovi segmenti

TabBar.tab_changed(0)  [→ Trascrizione]
  → nessuna azione (mostra sotto-stato corrente)

TabBar.tab_changed(1)  [→ Editor]
  → se nessun sub → PlaceholderWidget
  → altrimenti → WorkspaceWidget
```

---

### Invarianti (devono essere sempre vere)

```
INV1: segments_raw MAI modificati dall'editor
INV2: ResultWidget.badge_visible ↔ editor aperto E project.subtitles ≠ segments_raw
INV3: TabBar badge ● su Editor ↔ project.subtitles non vuoti
INV4: InlineProgressBar visibile ↔ worker attivo nell'EditorTab
INV5: un solo QThread TranscriptionWorker attivo alla volta
INV6: ProgressWidget.start() idempotente (guard se thread già attivo)
```

---

### Trappole architetturali da evitare

| Trappola | Prevenzione |
|---|---|
| `ResultWidget.open_editor_requested` chiamato due volte → load_subtitles duplicato | Guard: `if self._editor_loaded: return` in MainWindow |
| InlineProgressBar non nascosta se worker fallisce | `finally: inline_bar.hide()` in handler done/failed/cancelled |
| Dialog conferma sovrascrittura manca in UC4 | `_confirm_discard_if_needed()` chiamato in ogni entry-point che resetta editor |
| SRT import: parse errori silenti | `parse_srt()` lancia eccezioni → catch in MainWindow → QMessageBox |
| Badge "modificato" stale: non aggiornato dopo export | `mark_saved()` → `project.subtitles` e `segments_raw` resincronizzati → badge ricalcolato |
| Due worker contemporanei (UC3 mentre UC1 in corso) | `INV5`: MainWindow rifiuta nuovo worker se già attivo, mostra QMessageBox |

---

### Test requisiti (da verificare manualmente dopo implementazione)

```
T01  App parte → tab Trascrizione attiva, sotto-stato Drop
T02  Tab Editor cliccabile → PlaceholderWidget visibile
T03  Drop file + [Avvia] → sotto-stato Progress, worker parte
T04  Progress completato → sotto-stato Result, N sottotitoli corretti
T05  Result [Esporta SRT] → file salvato, contenuto corretto
T06  Result [Apri editor] → tab Editor, timeline popolata, preview caricata
T07  Tab Trascrizione con editor pieno → badge ⚠️ se sub modificati
T08  Result [Nuova] con editor vuoto → Drop senza dialog
T09  Result [Nuova] con editor pieno → dialog conferma → annulla → rimane
T10  Result [Nuova] con editor pieno → dialog → ok → Drop
T11  Progress [Stop] → sotto-stato Drop, editor intatto
T12  Editor [Importa] .v2srt → timeline caricata, no progress
T13  Editor [Importa] video → InlineProgressBar visibile → done → timeline aggiornata
T14  Editor [Importa] video mentre Progress attivo → bloccato con messaggio
T15  Chiusura con editor modificato → dialog conferma
T16  Chiusura con editor non modificato → chiude senza dialog
T17  Menu Apri recenti → lista file, click → apre correttamente
T18  ⌘O file video → tab Trascrizione, Drop pre-caricato
T19  ⌘O file .v2srt → editor caricato direttamente
T20  Badge ● su tab Editor → appare con sub, sparisce dopo reset
```

---

## Contesto proprietario

Cagliari, Mac Apple Silicon, italiano madrelingua. Vuole prodotto professionale stile DaVinci/Premiere, non script con GUI. Scelta PySide6 per dock trascinabili, fullscreen, editor tabellare, undo/redo robusto.
