# 🎬 Video → SRT

Trascrizione automatica di video/audio in italiano con la massima qualità possibile, generando sottotitoli SRT sincronizzati.

## Perché questo stack

| Scelta | Motivo |
|---|---|
| **faster-whisper** | 4x più veloce di openai-whisper, ~50% meno RAM |
| **large-v3** | Il miglior modello Whisper per l'italiano |
| **VAD (Silero)** | Filtra i silenzi, previene le allucinazioni |
| **Beam search (5)** | Esplora più ipotesi, sceglie la migliore |
| **Prompt italiano** | Guida punteggiatura, accenti e stile |
| **Word timestamps** | Sincronizzazione SRT precisa a livello di parola |
| **Post-processing timing** | I sottotitoli spariscono nei silenzi |
| **customtkinter** | GUI moderna con drag & drop |

## Setup macOS (Apple Silicon)

```bash
chmod +x setup_mac.sh
./setup_mac.sh
```

Installa tutto: FFmpeg, faster-whisper, customtkinter, tkinterdnd2, e scarica `large-v3` (~1.5 GB).

## Utilizzo

### GUI (con drag & drop)

```bash
source venv/bin/activate
python app.py
```

Trascina un file video/audio sulla drop zone, scegli il modello e avvia.

### CLI

```bash
source venv/bin/activate

# Massima qualità (default)
python transcribe.py video.mp4

# Più veloce
python transcribe.py video.mp4 -m large-v3-turbo

# Test rapido
python transcribe.py video.mp4 -m small
```

### Build .app

```bash
source venv/bin/activate
python build_mac.py
```

## Modelli disponibili

| Modello | RAM | Qualità IT | Uso consigliato |
|---|---|---|---|
| `tiny` | ~1 GB | ★☆☆☆☆ | Solo test |
| `base` | ~1 GB | ★★☆☆☆ | Solo test |
| `small` | ~2 GB | ★★★☆☆ | Test rapidi |
| `medium` | ~5 GB | ★★★★☆ | Buona alternativa |
| **`large-v3`** | **~6 GB** | **★★★★★** | **Default** |
| `large-v3-turbo` | ~4 GB | ★★★★½ | Velocità/qualità |

## Struttura progetto

```
video-to-srt/
├── engine.py          # Core trascrizione + post-processing timing
├── transcribe.py      # CLI
├── app.py             # GUI cross-platform (customtkinter + drag&drop)
├── build_mac.py       # Build .app bundle
├── setup_mac.sh       # Setup automatico macOS
└── requirements.txt
```