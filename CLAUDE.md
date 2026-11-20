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
├── main.py                   # entry point, splash, avvio robusto (--self-test)
├── self_test.py              # autotest dell'app compilata (ffmpeg, VAD, Qt, export)
├── engine.py                 # pipeline di trascrizione (ffmpeg, VAD, faster-whisper)
├── platform_support.py       # UNICO punto dipendente dal sistema operativo
├── pyi_rth_threads.py        # runtime hook PyInstaller (thread OMP/CT2)
├── requirements.txt          # dipendenze runtime
├── assets/                   # app.icns, app.ico, app_512.png: rigenerati da make_icon.py
├── core/                     # logica senza UI
│   ├── subtitle_model.py     # Subtitle / SubtitleProject
│   ├── subtitle_table_model.py  # QAbstractTableModel, parse/format timestamp, issues
│   ├── undo_commands.py      # QUndoCommand per ogni modifica
│   ├── srt_io.py, v2srt_io.py   # lettura/scrittura SRT/VTT/TXT/ASS e progetto .v2srt
│   ├── transcription_worker.py  # QThread che chiama engine
│   ├── transcription_config.py  # configurazione .vsrtconfig (decodifica, glossario, VAD, leggibilità)
│   ├── whisper_models.py     # catalogo modelli, modello consigliato (RAM/GPU), cache HF, download
│   ├── burn_in.py            # video MP4 con i sottotitoli impressi (Qt disegna, ffmpeg overlay)
│   ├── audio_player.py       # player/anteprima audio
│   └── constants.py
├── ui/                       # interfaccia
│   ├── theme.py              # token colore, stylesheet, MANAGER (tema chiaro/scuro)
│   ├── brand.py              # marchio: icona dell'app e splash di avvio (un solo disegno)
│   ├── main_window.py, workspace.py, project_widget.py
│   ├── project_tab_bar.py, tab_bar.py
│   ├── home_widget.py, progress_widget.py, result_widget.py, widgets.py, prefs.py
│   ├── editor_tab.py, subtitle_timeline.py, inspector_widget.py, find_replace_dialog.py
│   ├── preview_area.py, transport_bar.py, waveform_widget.py
│   └── export_tab.py, export_panel.py, placeholder_widget.py
└── tests/                    # pytest (UI offscreen)
packaging/                    # script di setup/build (README.md: tabella per piattaforma)
├── macos/                    # build_mac.py condiviso, install.sh, setup_mac.sh, .pkg, ...
│   ├── apple-silicon/build.sh   # build arm64
│   └── intel/build.sh           # build x86_64 (Rosetta); ffmpeg statico in intel/bin/
└── windows/                  # build_windows.py, setup_windows.bat
docs/                         # specifiche, piani, riferimenti di design, media del README
pyproject.toml                # solo config pytest + ruff (non è un pacchetto installabile)
requirements-dev.txt          # pytest, ruff
.github/workflows/ci.yml      # lint + test su macOS, Windows, Linux
.github/workflows/build.yml   # build macOS/Windows + autotest (manuale, tag, settimanale)
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
| Build macOS | `bash packaging/macos/apple-silicon/build.sh` · Intel: `bash packaging/macos/intel/build.sh` |
| Build Windows | `python packaging\windows\build_windows.py` |

Output build in `dist/`, `build/`; modello da includere in `_build_model/` (tutti nella root). Dettagli: `packaging/*/README.md`.
CI: stessi `ruff check app` + `pytest` su macOS/Windows (Python 3.11) e Ubuntu (Python 3.12: con
3.11 PySide 6.12 su Linux esaurisce i riferimenti a None e il processo si ferma), senza faster-whisper.

## Shortcut (⌘ su macOS = Ctrl altrove; etichette via `platform_support.shortcut_label`)

Verificate da `app/tests/test_shortcuts_audit.py` (sequenze vere, focus su tabella, ricerca,
testo dell'Inspector, forma d'onda, Home/risultato ed Esportazione).

| Shortcut | Azione |
|---|---|
| Ctrl+Z / Ctrl+Shift+Z | Undo / Redo (in un campo di testo agiscono sul campo) |
| Ctrl+K / Ctrl+M / Ctrl+Shift+K | Dividi / Unisci col successivo / Elimina selezionati (solo Editor) |
| Canc / ⌫ (focus sulla tabella) | Elimina selezionati |
| Ctrl+F / Ctrl+Alt+F | Trova (ricerca inline) / Trova e sostituisci (Windows/Linux anche Ctrl+H) |
| Ctrl+I | Mostra/nascondi Inspector (solo Editor) |
| Ctrl+Invio (testo dell'Inspector) | Applica il testo |
| Ctrl+O / Ctrl+N | Apri file / nuova trascrizione |
| Ctrl+S / Ctrl+E | Esporta SRT / apri tab Esportazione |
| Ctrl+Shift+S | Salva progetto `.v2srt` |
| Ctrl+Shift+T / Ctrl+W | Nuovo / chiudi tab progetto (Ctrl+W solo nella finestra principale; nel dialog Trova lo chiude) |
| Ctrl+Shift+] / [ — anche Ctrl+Tab / Ctrl+Shift+Tab (mac ⌃Tab / ⌃⇧Tab) | Tab progetto successivo / precedente |
| Ctrl+Shift+L | Cambia tema chiaro/scuro |
| Meta+Ctrl+F (mac ⌃⌘F) / F11 | Schermo intero |
| Space / K / J / L | Play-Pausa / pausa / seek −2 s / play (solo con l'Editor visibile; mai mentre si scrive; Spazio su un pulsante lo preme) |
| ← / → | Seek ±1 s (sullo slider del volume lo regolano) |
| Shift+← / Shift+→ | Sottotitolo precedente / successivo |
| Forma d'onda col focus | ←/→ ±1 s, Home/Fine inizio/fine, +/− zoom, 0 tutta la durata |

Forma d'onda col mouse/trackpad: rotella o due dita (verticale e orizzontale) = scorrimento
(solo con zoom, il playhead non si muove); Ctrl/⌘ o Alt + rotella e pizzico = zoom attorno al
cursore; doppio clic sullo sfondo = tutta la durata; clic = seek; tenere premuto e trascinare =
scrub (il playhead segue il mouse e resta dove lo si lascia; oltre i bordi la vista scorre);
⌥/Alt + trascinamento = scorrimento della vista.

Home: le impostazioni di trascrizione non scorrono; la finestra non scende sotto l'altezza che
servono (`MainWindow._fit_min_height`). Solo su uno schermo più basso di così diventano
scorrevoli come ultima risorsa (`HomeWidget.set_scroll_fallback`), invece di schiacciarsi. Il bordo tra Sorgente e Impostazioni si trascina
(impostazioni 380–600 px, sorgente almeno 440 px; larghezza in `home/settings_width`); con la
colonna stretta i formati della zona di rilascio vanno a capo per gruppi.

Video: il bordo tra monitor e forma d'onda si trascina (larghezza ricordata in
`workspace/monitor_width`); pulsante del trasporto o doppio clic sul video = schermo intero con i
sottotitoli (Esc, F o doppio clic per uscire; Spazio play/pausa, ←/→ ±1 s). Dopo uno scorrimento manuale
l'auto-scroll del playhead resta sospeso per 2 s (`FOLLOW_HOLD_S`); un seek esplicito lo riattiva.

## Trappole note

- **Seek in pausa**: `AudioPlayer.seek` emette subito `seeked` e poi `position_changed` (in pausa
  il backend non notifica; prima del caricamento il seek resta in sospeso). `seeked` sposta la
  selezione della tabella anche dove il follow della riproduzione (`_follow_blocked`) è sospeso.
- **Tasti di riproduzione**: sono QShortcut della timeline (contesto finestra). Se il widget col
  focus usa quel tasto (campo di testo, Spazio su pulsanti/interruttori, frecce sul volume) il
  tasto gli viene restituito (`ui.widgets.focus_owns_key`); widget custom attivabili con Spazio:
  proprietà `spaceActivates`.
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
- **PyInstaller**: solo i moduli Qt usati (`--hidden-import PySide6.Qt…`, niente `--collect-all
  PySide6`: WebEngine pesa ~650 MB), `--collect-all ctranslate2/onnxruntime` e `--paths app`.
  In app "frozen" `engine.py` cerca `ffmpeg` e `whisper_model` (solo con `--with-model`) in
  `sys._MEIPASS`.
- **Modelli Whisper**: mai scaricati allo splash. La Home segna il consigliato
  (`engine.recommended_model`, da RAM/GPU) e quelli da scaricare; il download parte con la
  trascrizione dopo la conferma (`ProjectWidget._confirm_model_download`). Nei test la cache di
  Hugging Face è vuota e isolata e l'hardware è fisso (16 GB, niente GPU) — `conftest.py`.
- **Parlato saltato da Whisper**: `engine._recover_skipped_speech` ritrascrive i tratti che il VAD
  marca come parlato ma senza parole, **anche col filtro VAD spento** (il VAD serve solo a
  trovarli). Le parole stirate oltre `subtitle_layout.MAX_WORD_S` (3 s: "con" su 16 s) non
  coprono il parlato e, se il tratto viene recuperato, sono sostituite.
- **Video con sottotitoli** (`core.burn_in`): i sottotitoli sono PNG trasparenti disegnati con Qt e
  sovrapposti da ffmpeg (`overlay` + concat demuxer), perché l'ffmpeg di Homebrew non ha libass né
  freetype (niente filtri `subtitles`/`drawtext`). Encoder: VideoToolbox al bitrate della sorgente,
  poi libx264 `veryfast`, `h264_mf`, `mpeg4`: se uno fallisce si prova il successivo.
- **Build e firma macOS**: dopo ogni build `build_mac.py` controlla le librerie fuori dal bundle
  (`packaging/macos/check_bundle.py`) e lancia `--self-test` sull'app compilata (PATH senza
  Homebrew). Con l'hardened runtime anche gli eseguibili di supporto (ffmpeg) vanno firmati con
  `entitlements.plist`, altrimenti non caricano le librerie del bundle.
- **ffmpeg nell'app macOS**: sta in `Contents/Frameworks/ffmpeg-bin/` con le sue librerie
  (`build_mac.bundle_ffmpeg`, riferimenti `@loader_path`), mai con `--add-binary`: Qt Multimedia
  include librerie FFmpeg con gli stessi nomi (libavcodec.62…) di un'altra versione e su un Mac
  pulito ffmpeg non partiva.
- **Icona Dock macOS**: `setWindowIcon` non basta; `platform_support.set_dock_icon` usa pyobjc (Cocoa).

## Diagnostica
- Log su console e su file a rotazione `videosrt.log` in `platform_support.app_cache_dir()`
  (mac `~/Library/Caches/VideoSRT`, Windows `%LOCALAPPDATA%\VideoSRT`, Linux `~/.cache/VideoSRT`).
  Gli autosave `.v2srt` stanno nella stessa cartella.
- Crash UI: lanciare `python app/main.py` da terminale per il traceback completo.
