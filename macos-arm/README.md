# 🎬 Video → SRT v2

**Workspace professionale** per trascrizione italiana con editor integrato.
Stack: PySide6 + faster-whisper + large-v3.

## Cosa cambia rispetto a v1

| | v1 (Try1) | v2 (Try2) |
|---|---|---|
| UI | customtkinter — single screen | **PySide6 — sidebar + pannelli multipli** |
| Layout | Fisso 620×640 | **Ridimensionabile + fullscreen** |
| Editing SRT | ❌ | **✅ (in arrivo Step 2)** |
| Undo/Redo | ❌ | **✅ (in arrivo Step 2)** |
| Find & Replace | ❌ | **✅ (in arrivo Step 2)** |
| Dock panels | ❌ | ✅ pianificato |

## Struttura

```
Try2/
├── main.py                     # Entry point + splash Qt
├── engine.py                   # Core trascrizione (invariato da v1)
├── pyi_rth_threads.py          # PyInstaller runtime hook
├── core/
│   ├── subtitle_model.py       # Subtitle + SubtitleProject
│   ├── srt_io.py               # Write SRT
│   └── transcription_worker.py # QThread worker
├── ui/
│   ├── theme.py                # Palette dark + stylesheet
│   ├── main_window.py          # QMainWindow + sidebar + stacked panels
│   ├── sidebar.py              # Navigazione sezioni
│   ├── source_panel.py         # Drop zone
│   ├── settings_panel.py       # Modello/VAD/Accuracy
│   ├── transcribe_panel.py     # Progress + log
│   ├── editor_panel.py         # ⚠️ Step 1: solo lettura. Step 2: editing completo
│   └── export_panel.py         # Salvataggio SRT
├── requirements.txt
└── setup_mac.sh
```

## Flusso utente

1. **📁 Sorgente** — carica file (drag&drop)
2. **⚙️ Impostazioni** — scegli modello e opzioni
3. **▶️ Trascrizione** — avvia, guarda progress, log
4. **📝 Editor** — revisiona i sottotitoli (Step 1: read-only · Step 2: editing)
5. **💾 Esporta** — salva SRT

## Setup

```bash
chmod +x setup_mac.sh
./setup_mac.sh

source venv/bin/activate
python main.py
```

## Roadmap

- **Step 1** ✅ — Scaffolding completo, porting trascrizione
- **Step 2** — Editor tabella editabile, Undo/Redo, inspector laterale
- **Step 3** — Waveform audio + player + shortcut J/K/L
- **Step 4** — Find & Replace, menubar completa, salvataggio progetto
```
