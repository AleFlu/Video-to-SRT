# Video → SRT v2 — Versione Windows

Editor professionale di sottotitoli con trascrizione automatica italiana (faster-whisper + large-v3).

---

## Requisiti di sistema

| Requisito | Minimo | Raccomandato |
|-----------|--------|--------------|
| OS | Windows 10 64-bit | Windows 11 64-bit |
| Python | 3.10 x64 | 3.11 x64 |
| RAM | 8 GB | 16 GB |
| Disco | 10 GB liberi (modello ~3 GB + dipendenze) | SSD |
| GPU | — | NVIDIA con CUDA 11.8+ (trascrizione più veloce) |

---

## Setup e avvio (sviluppo)

### 1. Installa Python

Scarica Python 3.10+ (64-bit) da https://www.python.org/downloads/

**Importante:** spunta "Add Python to PATH" durante l'installazione.

### 2. Installa ffmpeg

ffmpeg è necessario per la trascrizione e la gestione dei formati video.

**Opzione A — Scoop (consigliata):**
```powershell
scoop install ffmpeg
```

**Opzione B — Chocolatey:**
```powershell
choco install ffmpeg
```

**Opzione C — Manuale:**
1. Scarica da https://www.gyan.dev/ffmpeg/builds/ (versione `essentials`)
2. Estrai e copia `ffmpeg.exe` in `C:\Windows\System32\` o aggiungilo al PATH

### 3. Setup e avvio

```bat
cd windows
setup_windows.bat --run
```

Il setup:
- Crea un virtualenv `venv\`
- Installa tutte le dipendenze Python
- Scarica il modello Whisper large-v3 (~3 GB, solo al primo avvio)
- Avvia l'app

**Avvii successivi:**
```bat
venv\Scripts\activate
python main.py
```

---

## Build eseguibile (.exe)

```bat
venv\Scripts\activate
pip install pyinstaller
python build_windows.py
```

L'eseguibile viene generato in `dist\VideoSRT\VideoSRT.exe`.

Con `--onefile` (file singolo, più lento all'avvio):
```bat
python build_windows.py --onefile
```

**Nota:** PyInstaller su Windows può generare falsi positivi antivirus.
Se questo accade, aggiungi la cartella `dist\` alle eccezioni dell'antivirus.

---

## Differenze rispetto alla versione macOS

| Funzionalità | macOS | Windows |
|---|---|---|
| Font UI | SF Pro / Helvetica Neue | Segoe UI |
| Font monospace | SF Mono | Consolas |
| Icona Dock | NSApplication (pyobjc) | Non applicabile |
| Formato icona | app.icns | app.ico |
| Shortcut schermo intero | ⌃⌘F | F11 |
| Cache autosave | `~/Library/Caches/VideoSRT` | `%APPDATA%\VideoSRT` |
| File temp audio | `$TMPDIR` | `%TEMP%` |
| Player video nativo | AVFoundation | Media Foundation / DirectShow |
| Codec video | mp4/mov/m4a nativi | mp4 nativo; MKV richiede codec |
| Build | PyInstaller → .app + .dmg | PyInstaller → .exe |
| Installer | install.sh | setup_windows.bat |

### Codec video su Windows

Qt Multimedia su Windows usa Media Foundation, che supporta nativamente:
- MP4 (H.264 / H.265)
- MP3, WAV, M4A, WMA, AAC

Per **MKV, AVI, FLAC, OGG** e altri formati:
- L'app tenta automaticamente il fallback su WAV pre-processato da ffmpeg
- Se ffmpeg è disponibile, la trascrizione funziona comunque
- Il player video mostra la waveform come alternativa

---

## Struttura cartella (differenze da macOS)

```
windows/
├── main.py                   # Entry point adattato (no NSApp, font Windows)
├── engine.py                 # Core trascrizione (ffmpeg.exe, logging aggiuntivo)
├── requirements.txt          # Senza pyobjc-framework-Cocoa
├── setup_windows.bat         # Setup venv + deps + modello
├── build_windows.py          # PyInstaller → .exe
├── pyi_rth_threads.py        # Runtime hook PyInstaller (identico a macOS)
├── core/
│   ├── audio_player.py       # Fix: tempfile.gettempdir() invece di /tmp
│   └── ... (identici a macOS)
└── ui/
    ├── preview_area.py       # Fix: tempfile + logging errori player
    ├── project_widget.py     # Fix: _app_cache_dir() cross-platform
    ├── main_window.py        # Fix: _app_cache_dir() cross-platform
    ├── theme.py              # Fix: font stack Windows-first (Segoe UI, Consolas)
    └── ... (identici a macOS)
```

---

## Debug e log

L'app stampa log dettagliati su stdout. Per catturarli:

```bat
python main.py > log.txt 2>&1
```

In caso di crash:
1. Apri `Prompt dei comandi` nella cartella `windows\`
2. Attiva il venv: `venv\Scripts\activate`
3. Esegui: `python main.py`
4. Leggi l'output — ogni errore ha il modulo e la causa esatta

### Problemi comuni

**`ModuleNotFoundError: No module named 'ctranslate2'`**
→ Reinstalla le dipendenze: `pip install -r requirements.txt`

**`ffmpeg non trovato nel PATH`**
→ Installa ffmpeg e aggiungilo al PATH (vedi sezione Setup)

**Player video non mostra immagine**
→ Installa i codec media di Windows o usa un file MP4

**Trascrizione lenta**
→ Normale su CPU. Con GPU NVIDIA: installa `onnxruntime-gpu` e CUDA 11.8+

**Antivirus blocca il .exe**
→ Aggiungi `dist\VideoSRT\` alle eccezioni

---

## Stato compatibilità

| Componente | Status |
|---|---|
| UI (PySide6) | ✅ Funziona su Windows |
| Trascrizione (faster-whisper) | ✅ Wheel Windows su PyPI |
| VAD (onnxruntime) | ✅ Wheel Windows su PyPI |
| Waveform (soundfile + numpy) | ✅ Funziona |
| Player audio (Qt Multimedia) | ✅ Funziona |
| Player video (Qt Multimedia) | ✅ MP4; MKV con fallback WAV |
| Export SRT/VTT/TXT/ASS | ✅ Funziona |
| Salva/carica .v2srt | ✅ Funziona |
| Autosave | ✅ Usa %APPDATA% |
| Build .exe | ✅ PyInstaller |
