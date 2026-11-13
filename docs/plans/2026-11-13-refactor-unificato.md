# Refactor unificato Video → SRT — Piano di implementazione

**Goal:** una sola codebase (`app/`) per macOS ARM, macOS Intel e Windows, con i bug noti corretti, UI rivista e test verdi.

**Architettura:** `app/` contiene `core/`, `ui/`, `engine.py`, `main.py`, `tests/` (base: ex `macos-arm`, la copia più recente). Tutto ciò che dipende dal sistema operativo passa da un unico modulo `app/platform_support.py`. Gli script di build vivono in `packaging/`.

**Stack:** Python 3.9+ (sintassi compatibile 3.9), PySide6, faster-whisper/CTranslate2, pytest. Venv di sviluppo: `.venv/` nella root (`../.venv/bin/python` da `app/`).

**Comando test (da `app/`):** `QT_QPA_PLATFORM=offscreen ../.venv/bin/python -m pytest -q`
Baseline prima del refactor: 200 passed, 5 failed (badge `_badge_modified`).

## Vincoli globali

- Lingua: UI, docstring, commenti in **italiano**; nomi di variabili/funzioni/classi in inglese.
- `from __future__ import annotations` in ogni modulo; type hint; 4 spazi; ~100 colonne.
- `core/` non importa mai da `ui/`. `platform_support.py` non importa né `core` né `ui` né `engine` (può importare PySide6 solo dentro le funzioni che ne hanno bisogno).
- Niente `print()` nel codice applicativo: usare `logging.getLogger(__name__)`.
- Nessun colore esadecimale hardcoded nei widget: usare i token di `ui/theme.py` (`theme.c("nome")`) e reagire a `theme.MANAGER.theme_changed`.
- Nessun `if sys.platform` / `platform.system()` fuori da `platform_support.py`.
- Ogni modifica ai sottotitoli passa dal `QUndoStack`.
- Non cambiare i valori di tuning di Whisper/VAD/ffmpeg salvo dove indicato.
- Ogni bug corretto ha un test che fallisce prima e passa dopo (dove testabile senza modello Whisper).
- Non fare commit, non creare subagent: il coordinatore fa i commit dopo la review.

## Review Focus (casi che nessun test copriva)

1. File sorgente con formati non nativi (mkv/flac): l'anteprima non deve mai riprodurre un WAV non correlato.
2. Avvio con dipendenze rotte (ImportError di ctranslate2): lo splash deve chiudersi con un messaggio, non restare appeso.
3. Editor modificato + apertura di un altro file: deve chiedere conferma, mai sovrascrivere in silenzio.
4. Segmento Whisper senza parole affidabili seguito da parlato: nessuna parola deve sparire dall'SRT.
5. SRT importato con righe vuote contenenti spazi, o millisecondi a 1–2 cifre: deve essere letto correttamente.

---

## Task 1 — Struttura unificata ✅ (fatto dal coordinatore)

`macos-arm/*` → `app/`; script di build → `packaging/{macos-arm,macos-intel,windows}/`; copie `macos-intel/` e `windows/` di codice rimosse.

## Task 2 — `platform_support.py` + avvio robusto

**File:** crea `app/platform_support.py`, `app/tests/test_platform_support.py`; modifica `app/main.py`, `app/core/audio_player.py`, `app/ui/theme.py`, `app/ui/preview_area.py`, `app/ui/project_widget.py`, `app/ui/main_window.py`, `app/ui/export_panel.py`, `app/ui/waveform_widget.py`, e ogni file `ui/` con `font-family` letterale o etichette "⌘".

**Interfaccia prodotta (`platform_support`):**

```python
IS_MAC: bool; IS_WIN: bool; IS_LINUX: bool
def cpu_threads() -> int            # lru_cache. mac: sysctl hw.perflevel0.logicalcpu, poi hw.physicalcpu; altrove max(4, cpu_count//2); mai < 1
def ffmpeg_executable_name() -> str # "ffmpeg.exe" su Windows, altrimenti "ffmpeg"
def subprocess_kwargs() -> dict     # {"creationflags": subprocess.CREATE_NO_WINDOW} su Windows, {} altrove
def app_cache_dir() -> Path         # mac ~/Library/Caches/VideoSRT; win %LOCALAPPDATA%/VideoSRT; linux $XDG_CACHE_HOME|~/.cache /VideoSRT; fallback tempdir/VideoSRT_cache; crea la dir
def legacy_cache_dirs() -> list[Path]  # [~/.cache/VideoSRT] su mac (vecchi autosave), [] altrove
def temp_dir() -> Path              # Path(tempfile.gettempdir())
def native_media_exts() -> frozenset[str]  # comuni {.mp4 .mov .m4a .m4v .mp3 .wav .aac} + .aiff (mac) / .wma (win)
def font_stack_ui() -> str          # stringa CSS font-family. mac: "SF Pro Display","SF Pro Text",-apple-system,"Helvetica Neue",sans-serif ; win: "Segoe UI",Arial,sans-serif ; linux: "Inter","Noto Sans","DejaVu Sans",sans-serif
def font_stack_mono() -> str        # mac: "SF Mono","Menlo",monospace ; win: "Cascadia Mono","Consolas",monospace ; linux: "DejaVu Sans Mono",monospace
def ui_font_family() -> str         # primo nome della stack UI (per QFont): "Helvetica Neue" mac, "Segoe UI" win, "Noto Sans" linux
def mono_font_family() -> str       # "SF Mono" mac (QFont ha fallback), "Consolas" win, "DejaVu Sans Mono" linux
def shortcut_label(seq: str) -> str # "Ctrl+Shift+T" -> "⌘⇧T" su mac, invariato altrove ("Ctrl"→⌘, "Shift"→⇧, "Alt"→⌥, "Return"→↵, senza '+')
def fullscreen_shortcut() -> str    # "Meta+Ctrl+F" mac, "F11" altrove
def reveal_in_file_manager(path: str) -> bool  # mac: open -R path; win: explorer /select,<path> (UN solo argomento f"/select,{path}"); linux: xdg-open <dir>. False se fallisce
def app_icon_path(assets_dir: Path) -> Path | None  # app.icns mac, app.ico win, app_512.png fallback; None se assente
def set_dock_icon(pixmap) -> None   # solo mac via pyobjc; no-op altrove; logga a debug se fallisce
def configure_logging() -> Path | None  # root logger INFO, StreamHandler + RotatingFileHandler in app_cache_dir()/"videosrt.log" (1 MB, 2 backup); ritorna il path del log
```

**Requisiti:**
- Sostituire in tutta `app/` ogni uso di `TMPDIR`/`"/tmp"`/`os.environ["HOME"]`/`.cache/VideoSRT` con `temp_dir()` / `app_cache_dir()`. `MainWindow._check_autosave_restore` scandisce `app_cache_dir()` **e** `legacy_cache_dirs()`.
- `theme.FONT_UI` / `theme.FONT_MONO` derivano da `font_stack_ui()` / `font_stack_mono()`; nessun `font-family` letterale né `QFont("SF …")` residuo in `ui/` (grep deve dare zero).
- Tutte le etichette/tooltips con "⌘…" usano `shortcut_label(...)`.
- `export_panel.py`: usa `reveal_in_file_manager`.
- `core/audio_player.py`: `native_media_exts()`, `temp_dir()`, logging, try/except attorno a `_resolve_source` in `load()` che emette `error_occurred`. **Rimuovere** la ricerca di `<stem>.wav`/`<stem>_16k.wav` in temp e accanto al file (l'engine non li scrive mai: rischio di riprodurre audio non correlato) — stessa rimozione in `ui/preview_area.py::_resolve_wav`.
- Su Windows `main.py` chiama `app.setStyle("Fusion")` prima di `apply_theme`.
- `main.py`: `configure_logging()` all'avvio; il worker dello splash è in `try/except/finally` e emette **sempre** `finished(ok: bool, error: str)`; in caso di errore `QMessageBox.critical` + uscita con codice 1; le connessioni dal thread worker verso la GUI usano `Qt.QueuedConnection` su slot di un `QObject` che vive nel thread GUI; il dialog di ripristino autosave va mostrato **dopo** la chiusura dello splash; rimuovere `state["done"]`; non rigenerare l'icona 512px se esiste il file icona.
- Test: `shortcut_label` (mac/non-mac con monkeypatch di `IS_MAC`), `app_cache_dir` crea la dir e fa fallback, `cpu_threads() >= 1`, `reveal_in_file_manager` costruisce l'argomento Windows corretto (monkeypatch `subprocess.run`), `native_media_exts`, nessun `sys.platform`/`platform.system` fuori da `platform_support.py` (test strutturale AST su tutta `app/` esclusi i test).

## Task 3 — Engine: unione delle tre varianti + bug

**File:** `app/engine.py`, crea `app/tests/test_engine.py` (senza caricare modelli: usare oggetti finti con `.word .start .end .probability`).

- Logging al posto di tutti i `print`.
- Rinomina: `_postprocess_italian` → `_postprocess_codeswitching`; `_postprocess_italian_subs` → `_postprocess_typography` (aggiornare tutti i call site).
- `_FakeWord` a livello modulo con `__slots__`; `collect_all_words(...) -> Tuple[List, set]`.
- **Bug parole perse:** `_flush_words` usa sempre `" ".join(w.word.strip() for w in words)`; un word sintetico forza uno split prima e dopo di sé. Test: segmento sintetico "ok va bene" seguito da segmento con parole reali → il testo complessivo contiene tutte le parole.
- **Merge frammenti corti:** unire solo se `len(combinato) <= HARD_LIMIT` e durata combinata `<= MAX_SUBTITLE_DURATION`. Test.
- **Cache modello thread-safe:** `threading.RLock` attorno a check+load+store; prima di caricare una chiave diversa azzerare la cache e `gc.collect()`. `_get_or_load_model` ritorna solo il modello; `num_workers=1`. Test con `WhisperModel` monkeypatchato: due thread concorrenti → un solo caricamento.
- `get_optimal_device`: usare `ctranslate2.get_cuda_device_count()` (non importare torch); `cuda/float16` se > 0, altrimenti `cpu/int8`. Rimuovere il ramo MPS (CTranslate2 non lo supporta).
- `cpu_threads`, nome ffmpeg, `subprocess_kwargs()` da `platform_support` (applicare a ogni `subprocess.run`). `check_ffmpeg` usa `shutil.which`.
- `preprocess_audio`: passa `os.path.abspath(input_path)`; logga `stderr[:500]` se fallisce; ramo `TimeoutExpired`; `on_status("⚠️ Pre-elaborazione audio non riuscita — uso l'audio originale")` in caso di fallimento. Filtri ffmpeg invariati (`highpass=f=80`, `afftdn=nf=-25`, `loudnorm=I=-16:TP=-1.5:LRA=7`).
- `_setup_environment`: `_setup_done = True` solo a lavoro riuscito; copia VAD in try/except con log.
- WhisperX: usa la pipeline globale (`collect_all_words` su tutti i segmenti adattati + `segment_words_semantic`); rispetta `language`; post-processing italiano solo se `language == "it"`; `del wx_model` in `try/finally`. Rimuovere `split_segment_by_words`.
- `_check_cancel(cancel_event)` a livello modulo (messaggio "Trascrizione annullata dall'utente").
- `VAD_PARAMS = dict(min_silence_duration_ms=150, speech_pad_ms=100, threshold=0.50)` come costante; parametri di decodifica invariati.
- Fallback VAD: catturare l'errore solo se è `ImportError`/`FileNotFoundError` o il messaggio contiene "onnx" (case-insensitive) **e** riguarda il VAD; chiudere il generatore precedente (`.close()` se presente).
- `post_process_timing`: pass finale che garantisce `end <= next.start - MIN_GAP_BETWEEN_SUBS` quando possibile e `end > start` sempre. Test con segmenti sovrapposti.
- Rimuovere duplicati e codice morto: `format_timestamp_srt`, `wrap_subtitle_text`, `generate_srt`, `write_srt`, `_unique_output_path` (usare `core.srt_io`: `run_pipeline` converte i segmenti in `Subtitle` e chiama `write_srt`/`unique_output_path`); costanti `SILENCE_THRESHOLD`, `END_PAD_SPEECH`, `END_PAD_SILENCE`, `READING_SPEED_CPS`; `MAX_CHARS_PER_LINE`/`MAX_SUBTITLE_DURATION`/`MIN_SUBTITLE_DURATION` importate da `core.constants`.
- `transcribe(input_path, *, model_size, beam_size, vad_filter, denoise, high_accuracy, language, cancel_event, on_status, on_progress)` — dopo `input_path` tutto keyword-only; `run_pipeline` accetta e inoltra `language`, solleva `RuntimeError` se nessun segmento.

## Task 4 — Core: I/O sottotitoli, modello, worker

**File:** `app/core/srt_io.py`, `subtitle_model.py`, `v2srt_io.py`, `constants.py`, `transcription_worker.py`, `subtitle_table_model.py`, `undo_commands.py` + test relativi in `app/tests/`.

- `srt_io`: un solo helper privato `_split_ms(seconds) -> (h, m, s, ms)` usato dai formatter SRT/VTT/ASS; un solo `_write_text(path, text)` **atomico** (file temporaneo nella stessa cartella + `os.replace`) usato da tutti i `write_*`.
- `wrap_subtitle_text(text, max_chars=MAX_CHARS_PER_LINE)`: rispetta i `\n` già presenti (non ri-spezza testo già a più righe); altrimenti spezza al confine di parola più bilanciato; massimo 2 righe.
- `parse_srt`: regex a livello modulo; accetta BOM, CRLF, righe "vuote" con spazi, millisecondi 1–3 cifre con `,` o `.`, ore a 1+ cifre, blocchi senza indice numerico, tag di posizione dopo il timestamp; salta blocchi malformati; solleva `ValueError` con messaggio italiano se il file non contiene alcun sottotitolo valido.
- ASS: `\n` → `\N`, `{`/`}` nel testo → escape (`\{`, `\}`); VTT: `-->` nel testo → `->`; `&`/`<` nel testo VTT → `&amp;`/`&lt;`.
- `Subtitle.to_dict` include `confidence` solo se `!= 1.0`; `from_dict` tollera chiavi mancanti/tipi stringa numerici e solleva `ValueError` chiaro se `start`/`end` mancano.
- `SubtitleProject.source_path: str = ""` sempre stringa. `v2srt_io` usa `Subtitle.to_dict/from_dict`, scrittura atomica, `load_project` solleva `ValueError` (messaggio italiano) per JSON non valido o `version` > 1; `source_path` assente → `""`.
- `constants.py`: i filtri file (`FILE_FILTER_*`) sono **generati** dai set di estensioni (niente liste duplicate); `MAX_CPS`, `WARN_CPS = 17.0`, `MIN_SUBTITLE_DURATION` definiti solo qui e importati da `subtitle_table_model.py`.
- `subtitle_table_model.py`: rimuovere `_TS_RE` inutilizzato; `parse_timestamp` rifiuta valori negativi e `nan/inf`; i colori di severità non sono più esadecimali nel model: `data()` per `BackgroundRole`/`ForegroundRole` legge da una funzione iniettabile `set_color_provider(callable(name) -> QColor)` con default neutro (il wiring ai token tema avviene in Task 6). `_apply_edit` non fa `strip()` dei `\n` interni. `row_severity` basata su codici (`issue codes`), non su sottostringhe dei messaggi: `row_issue_codes(row) -> list[str]` con codici `"end_before_start" "too_short" "too_fast" "overlap" "empty"`.
- `undo_commands.py`: `EditFieldCommand.mergeWith` unisce solo edit di **testo** (non start/end); `ReplaceAllCommand` e `DeleteSubtitleCommand` invariati salvo test.
- `transcription_worker.py`: parametri in una `@dataclass(frozen=True) TranscriptionParams(input_path, model_size="large-v3", beam_size=5, vad_filter=True, denoise=True, high_accuracy=False, language="it")` con `from_dict(d)` per compatibilità con i dict esistenti (il costruttore accetta entrambi); logging; rimuovere import inutili.

## Task 5 — UI: bug critici e perdita dati

**File:** `app/ui/*.py` (in particolare `workspace.py`, `subtitle_timeline.py`, `inspector_widget.py`, `project_widget.py`, `main_window.py`, `export_tab.py`, `find_replace_dialog.py`), test in `app/tests/`. Riferimento dettagliato: report `review-ui.md` (path nel brief), sezioni Critical/Important.

- **Inspector unico:** una sola istanza di `InspectorWidget`, quella visibile, collegata all'undo stack. Test: modifica di testo/start/end dall'inspector → il model cambia e `undo()` la annulla.
- **Trova e sostituisci raggiungibile:** azione menu Modifica + toolbar + `Ctrl+F` (trova inline) e `Ctrl+Alt+F`/`Ctrl+H` (dialog sostituisci). Test: l'azione apre `FindReplaceDialog`.
- **Conferma prima di sovrascrivere:** `open_path`, `load_v2srt`, `_load_srt`, "+Importa", Result → "Apri nell'editor": se l'editor è modificato chiedere conferma (Salva / Non salvare / Annulla) tramite un unico metodo `confirm_discard_changes() -> bool`. Test con `QMessageBox` monkeypatchato.
- **Autosave:** il file di autosave si elimina solo dopo un ripristino riuscito; un progetto ripristinato è marcato modificato; scrittura in try/except con log.
- **Risincronizzazione dopo caricamento:** dopo `load_v2srt`/ripristino, waveform e overlay sottotitoli vengono ri-sincronizzati; `_segments_raw` contiene sempre `list[dict]` (mai `Subtitle`). Test: carica `.v2srt` → esporta senza eccezioni.
- **Scorciatoie non ambigue:** ogni scorciatoia registrata una sola volta (azioni di menu della `MainWindow` che delegano al progetto attivo). Test: nessuna `QKeySequence` duplicata tra le azioni della finestra.
- **Badge:** rinominare `_badge_mod` → `_badge_modified` in `export_tab.py`; correggere il test che passa per il motivo sbagliato (`isHidden()` invece di `not isVisible()`). I 5 test rossi devono diventare verdi.
- Chiusura finestra: annulla e attende il worker di trascrizione attivo prima di chiudere.

## Task 6 — UI: UX, tema, prestazioni, pulizia

**File:** `app/ui/*.py`, `app/core/subtitle_table_model.py` (solo wiring colori), test.

- Transport: click sulla barra = seek alla posizione cliccata; pulsante loop funzionante (loop sul sottotitolo selezionato) oppure rimosso; combo velocità sincronizzata con J/L; durante la riproduzione non si sovrascrive la selezione dell'utente né il testo non confermato nell'inspector (follow-playback disattivato mentre un campo dell'inspector ha il focus).
- Tema: eliminare ogni colore esadecimale hardcoded in `ui/` (DepsBanner, model, waveform, placeholder d'errore…) → token; tutto si aggiorna al cambio tema. Collegare `SubtitleTableModel.set_color_provider` ai token e riemettere `dataChanged` al cambio tema. Aggiungere a `theme.apply_theme` una `QPalette` derivata dai token. Test strutturale: nessun `#rrggbb` letterale in `ui/` fuori da `theme.py`.
- Prestazioni: `ResultWidget` mostra l'anteprima con una vista virtualizzata (`QListView` + model) o limita a N righe con "mostra tutto", non un widget per segmento; waveform: lettura a blocchi con `soundfile.blocks` e calcolo dei picchi min/max per bucket (memoria O(larghezza), non O(file)), cache `QPixmap` dei picchi ridisegnata solo su resize/zoom/tema; sincronizzazioni di stato O(N) raggruppate con un `QTimer` single-shot (debounce 50 ms).
- Codice morto: rimuovere `SourcePanel`, `DropZone`, `_DropIcon` inutilizzati, pulsanti nascosti dell'inspector, `set_undo_stack`, progress inline inutilizzato di `EditorTab`, import inutilizzati (ruff `F401,F841` pulito su `app/`).
- Accessibilità: `setAccessibleName` su tutti i controlli interattivi senza testo (icone), tooltip con scorciatoia, ordine di tab sensato in Home, Inspector e dialog; focus ring visibile nel tema; drag&drop che rifiuta estensioni non supportate con messaggio.
- Testi UI tutti in italiano coerente (niente misto IT/EN nelle etichette).

## Task 7 — Packaging, CI, documentazione

**File:** `packaging/**`, `README.md`, `CLAUDE.md`, `app/requirements.txt`, crea `requirements-dev.txt`, `pyproject.toml` (solo config ruff + pytest), `.github/workflows/ci.yml`, `.gitignore`.

- `packaging/macos-arm` e `packaging/macos-intel` hanno script identici → una sola cartella `packaging/macos/` (lo script rileva l'architettura con `platform.machine()`; `build_intel.sh` resta come wrapper `arch -x86_64`). Tutti gli script puntano a `app/` (entry point `app/main.py`, asset `app/assets`, hook `app/pyi_rth_threads.py`) e includono `platform_support.py`. Windows: `packaging/windows/`.
- CI GitHub Actions: matrice `macos-latest`, `windows-latest`, `ubuntu-latest` × Python 3.11; installa `PySide6 numpy soundfile pytest ruff` (non faster-whisper); `ruff check app` + `pytest` con `QT_QPA_PLATFORM=offscreen`.
- README root aggiornato alla nuova struttura (sviluppo, test, build per piattaforma); `CLAUDE.md` riscritto corto e corrente (struttura reale, regole, comandi), senza la cronologia degli step passati.
- `legacy-v1/` resta intatto.

## Task 8 — Review finale e verifica

Review dell'intero branch su modello più capace; un solo giro di fix; avvio reale dell'app (`python app/main.py`) con screenshot tema chiaro/scuro; suite completa verde; ruff pulito.
