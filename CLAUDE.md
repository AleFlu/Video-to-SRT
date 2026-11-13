# CLAUDE.md — Video → SRT v2

Guida per lavorare su questo repository (anche con Claude Code).

## Progetto

App desktop per **trascrizione automatica italiana** di video/audio + **editor SRT** integrato.
Una sola codebase (`app/`) per macOS ARM, macOS Intel e Windows. Stack: **PySide6** +
**faster-whisper** (CTranslate2, modello large-v3) + FFmpeg. Python 3.9+ (sintassi compatibile).
Lingua: UI, docstring e commenti in **italiano**; nomi di variabili/funzioni/classi in inglese.

## Struttura

```
app/                          # tutta l'applicazione
├── main.py                   # entry point, splash, avvio robusto
├── engine.py                 # pipeline di trascrizione (ffmpeg, VAD, faster-whisper)
├── platform_support.py       # UNICO punto dipendente dal sistema operativo
├── pyi_rth_threads.py        # runtime hook PyInstaller (thread OMP/CT2)
├── requirements.txt          # dipendenze runtime
├── assets/                   # app.icns, app_512.png, make_icon.py (app.ico non presente)
├── core/                     # logica senza UI
│   ├── subtitle_model.py     # Subtitle / SubtitleProject
│   ├── subtitle_table_model.py  # QAbstractTableModel, parse/format timestamp, issues
│   ├── undo_commands.py      # QUndoCommand per ogni modifica
│   ├── srt_io.py, v2srt_io.py   # lettura/scrittura SRT/VTT/TXT/ASS e progetto .v2srt
│   ├── transcription_worker.py  # QThread che chiama engine
│   ├── audio_player.py       # player/anteprima audio
│   └── constants.py
├── ui/                       # interfaccia
│   ├── theme.py              # token colore, stylesheet, MANAGER (tema chiaro/scuro)
│   ├── main_window.py, workspace.py, project_widget.py
│   ├── project_tab_bar.py, tab_bar.py
│   ├── home_widget.py, progress_widget.py, result_widget.py, widgets.py, prefs.py
│   ├── editor_tab.py, subtitle_timeline.py, inspector_widget.py, find_replace_dialog.py
│   ├── preview_area.py, transport_bar.py, waveform_widget.py
│   └── export_tab.py, export_panel.py, placeholder_widget.py
└── tests/                    # pytest (UI offscreen)
packaging/                    # script di build, ognuno con il proprio README
├── macos/                    # ARM + Intel: build_mac.py, build_intel.sh, install.sh, ...
└── windows/                  # build_windows.py, setup_windows.bat
docs/                         # piani (docs/plans) e riferimenti di design
legacy-v1/                    # versione storica: NON toccare
pyproject.toml                # solo config pytest + ruff (non è un pacchetto installabile)
requirements-dev.txt          # pytest, ruff
.github/workflows/ci.yml      # lint + test su macOS, Windows, Linux
```

## Regole di architettura

- `core/` non importa mai da `ui/`. `platform_support.py` non importa `core`, `ui` né `engine`
  (PySide6 solo dentro le funzioni che ne hanno bisogno).
- Nessun `if sys.platform` / `platform.system()` fuori da `platform_support.py`
  (font, cache, ffmpeg, scorciatoie, "reveal in file manager", estensioni native).
- `from __future__ import annotations` in ogni modulo; type hint; 4 spazi; ~100 colonne.
- Niente `print()` nel codice applicativo: `logging.getLogger(__name__)`.
- Nessun colore esadecimale hardcoded nei widget: token di `ui/theme.py` (`theme.c("nome")`),
  e reazione a `theme.MANAGER.theme_changed`.
- Ogni modifica ai sottotitoli passa dal `QUndoStack`; `apply_edit_raw` è l'unica via per
  toccare il modello senza handler (usata da undo/redo).
- Non cambiare i valori di tuning di Whisper/VAD/ffmpeg senza una ragione esplicita.
- Ogni bug corretto ha un test che fallisce prima e passa dopo (se testabile senza modello).
- Import: stdlib → PySide6 → core → ui. `camelCase` solo per override Qt.

## Comandi

Setup (dalla root): `python -m venv .venv && source .venv/bin/activate` (Windows: `.venv\Scripts\activate`), poi
`pip install -r app/requirements.txt -r requirements-dev.txt`.

| Cosa | Comando (dalla root) |
|---|---|
| Avvio | `python app/main.py` |
| Test | `QT_QPA_PLATFORM=offscreen python -m pytest -q` |
| Lint | `ruff check app` |
| Build macOS | `packaging/macos/install.sh --app` (Intel: `packaging/macos/build_intel.sh`) |
| Build Windows | `python packaging\windows\build_windows.py` |

Output build in `dist/`, `build/`; modello da includere in `_build_model/` (tutti nella root). Dettagli: `packaging/*/README.md`.
CI: stessi `ruff check app` + `pytest` su macOS/Windows/Ubuntu (Python 3.11, senza faster-whisper).

## Shortcut (⌘ su macOS = Ctrl altrove; etichette via `platform_support.shortcut_label`)

| Shortcut | Azione |
|---|---|
| Ctrl+Z / Ctrl+Shift+Z | Undo / Redo |
| Ctrl+K / Ctrl+M / Ctrl+Shift+K | Dividi / Unisci col successivo / Elimina selezionati |
| Ctrl+F / Ctrl+Alt+F | Trova (ricerca inline) / Trova e sostituisci |
| Ctrl+I | Mostra/nascondi Inspector |
| Ctrl+O / Ctrl+N | Apri file / nuova trascrizione |
| Ctrl+S / Ctrl+E | Esporta SRT / apri tab Esportazione |
| Ctrl+Shift+S | Salva progetto `.v2srt` |
| Ctrl+Shift+T / Ctrl+W | Nuovo / chiudi tab progetto |
| Ctrl+Shift+] / [ | Tab progetto successivo / precedente |
| Ctrl+Shift+L | Cambia tema chiaro/scuro |
| Meta+Ctrl+F (mac) / F11 | Schermo intero |
| Space / K / J / L | Play-Pausa / pausa / seek −2 s / play (non attivi mentre si scrive) |
| ← / → | Seek ±1 s |
| Shift+← / Shift+→ | Sottotitolo precedente / successivo |

## Trappole note

- **Inspector passivo**: non modifica il modello; emette segnali `(row, valore)` e l'editor crea
  il comando. Se scrivesse direttamente: dataChanged → refresh → editingFinished → loop infinito.
- **Timestamp in due formati**: `srt_io.format_timestamp_srt` → `HH:MM:SS,mmm` (virgola, standard SRT);
  `subtitle_table_model.format_timestamp` → `MM:SS.mmm` (UI). `parse_timestamp` accetta più formati
  e ritorna `None` se non parsabile (`setData` scarta).
- **Snapshot undo**: nei `QUndoCommand` usare `dataclasses.replace(sub)` per copiare il sottotitolo,
  altrimenti le modifiche successive contaminano lo stato salvato.
- **Il worker non scrive l'SRT**: i segmenti tornano alla UI per l'editing; scrive solo l'esportazione.
- **Editor modificato + nuova apertura**: chiedere sempre conferma prima di sovrascrivere; una sola
  trascrizione alla volta; `_editor_loaded` in `ProjectWidget` evita doppi caricamenti.
- **PyInstaller**: servono `--collect-all PySide6/shiboken6/ctranslate2` e `--paths app`; in app
  "frozen" `engine.py` cerca `ffmpeg` e `whisper_model` in `sys._MEIPASS`.
- **Icona Dock macOS**: `setWindowIcon` non basta; `platform_support.set_dock_icon` usa pyobjc (Cocoa).

## Diagnostica
- Log su console e su file a rotazione `videosrt.log` in `platform_support.app_cache_dir()`
  (mac `~/Library/Caches/VideoSRT`, Windows `%LOCALAPPDATA%\VideoSRT`, Linux `~/.cache/VideoSRT`).
  Gli autosave `.v2srt` stanno nella stessa cartella.
- Crash UI: lanciare `python app/main.py` da terminale per il traceback completo.
