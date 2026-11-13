# Video → SRT

Applicazione desktop per la trascrizione automatica di video e audio in **italiano** e la generazione di sottotitoli `.srt` sincronizzati, con un editor integrato per la revisione professionale dei sottotitoli.

La trascrizione avviene interamente in locale: nessun dato viene inviato a servizi esterni e, dopo il primo setup, l'applicazione funziona completamente offline.

---

## Funzionalità principali

- **Trascrizione locale** di video e audio con timestamp a livello di parola
- **Editor di sottotitoli** con tabella editabile, inspector, undo/redo, find & replace e diagnostica automatica (overlap, durata, caratteri al secondo)
- **Anteprima sincronizzata** con player video / waveform e controlli di trasporto (play, seek, shortcut J/K/L)
- **Export multiplo**: SRT, VTT, TXT, ASS e formato di progetto `.v2srt`
- **Multipiattaforma**: macOS (Apple Silicon e Intel) e Windows

---

## Stack tecnico

| Componente | Tecnologia | Ruolo |
|---|---|---|
| Motore di trascrizione | [faster-whisper](https://github.com/SYSTRAN/faster-whisper) (CTranslate2) | Inferenza Whisper ottimizzata, più veloce e con minor uso di RAM |
| Modello | Whisper **large-v3** | Riconoscimento vocale ad alta qualità per l'italiano |
| Voice Activity Detection | Silero VAD | Filtra i silenzi e riduce le allucinazioni del modello |
| Estrazione audio | FFmpeg | Decodifica e conversione dei formati video/audio |
| Interfaccia | PySide6 (Qt 6) | UI desktop a pannelli, editor tabellare, dock, undo/redo |
| Elaborazione waveform | NumPy + soundfile | Calcolo e rendering della forma d'onda |
| Packaging | PyInstaller | Build di `.app`/`.dmg` (macOS) ed `.exe` (Windows) |

### Pipeline di trascrizione

1. **Estrazione audio** dal file sorgente tramite FFmpeg
2. **Voice Activity Detection** (Silero) per isolare il parlato dai silenzi
3. **Trascrizione** con faster-whisper (`language=it`, beam search, word timestamps, prompt in italiano per punteggiatura e accenti)
4. **Post-processing** dei timing e correzione delle italianizzazioni più comuni
5. **Segmentazione** in sottotitoli con vincoli di durata e lunghezza riga

---

## Struttura del repository

Una sola codebase per tutte le piattaforme; gli script di build sono separati.

```
app/                 # applicazione (macOS ARM/Intel e Windows)
├── main.py          # entry point
├── engine.py        # motore di trascrizione
├── platform_support.py  # tutto ciò che dipende dal sistema operativo
├── core/            # modello dati, I/O sottotitoli, worker, player
├── ui/              # interfaccia PySide6 (finestra, editor, anteprima, ...)
├── assets/          # icone
├── tests/           # test pytest
└── requirements.txt
packaging/
├── macos/           # build .app/.dmg/.pkg per Apple Silicon e Intel
└── windows/         # build .exe
docs/                # piani e riferimenti di design
legacy-v1/           # prima versione storica con interfaccia minimale e CLI (solo riferimento)
```

---

## Requisiti

- **FFmpeg** (installato automaticamente dagli script di setup)
- **Python 3.10+** (3.11 consigliato; il codice resta compatibile con 3.9)
- **8 GB di RAM** minimo — il modello `large-v3` ne usa ~6 GB; sono selezionabili modelli più leggeri
- **~4–10 GB di spazio libero** per modello e dipendenze
- Connessione internet **solo** per il primo setup (download dipendenze e modello)

### Modelli disponibili

| Modello | RAM | Qualità IT | Uso consigliato |
|---|---|---|---|
| `small` | ~2 GB | ★★★☆☆ | Test rapidi |
| `medium` | ~5 GB | ★★★★☆ | Buona alternativa |
| **`large-v3`** | **~6 GB** | **★★★★★** | **Default** |
| `large-v3-turbo` | ~4 GB | ★★★★½ | Equilibrio velocità/qualità |

---

## Setup e avvio

**Sviluppo (tutte le piattaforme)**, dalla root del repository:

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r app/requirements.txt -r requirements-dev.txt
python app/main.py
```

FFmpeg deve essere nel `PATH` (macOS: `brew install ffmpeg`; Windows: vedi `packaging/windows/README.md`).
Il modello Whisper `large-v3` viene scaricato al primo utilizzo.

**Script di setup guidato** (installano FFmpeg, venv, dipendenze e modello):

```bash
packaging/macos/install.sh --run   # macOS (ARM e Intel)
```
```bat
packaging\windows\setup_windows.bat --run
```

## Test e lint

```bash
QT_QPA_PLATFORM=offscreen python -m pytest -q    # Windows (cmd): set QT_QPA_PLATFORM=offscreen
ruff check app
```

La CI (GitHub Actions) esegue gli stessi comandi su macOS, Windows e Linux.

---

## Formati supportati

| Tipo | Formati |
|------|---------|
| Video | MP4, MKV, AVI, MOV, WebM |
| Audio | MP3, WAV, M4A, FLAC, OGG, AAC, WMA |

---

## Build distribuibile

Gli script risolvono i percorsi dalla propria posizione e scrivono in `build/` e `dist/` nella root.

- **macOS (Apple Silicon)** — `packaging/macos/install.sh --app` (o `--dmg`), oppure `python packaging/macos/build_mac.py --clean`
- **macOS (Intel)** — `bash packaging/macos/build_intel.sh` (richiede venv x86_64 e ffmpeg statico, vedi README)
- **Windows** — `python packaging\windows\build_windows.py` → `dist\VideoSRT\VideoSRT.exe`

Dettagli in [`packaging/macos/README.md`](packaging/macos/README.md) e [`packaging/windows/README.md`](packaging/windows/README.md).

---

## Licenza

Questo progetto è distribuito sotto **licenza MIT**. Il testo completo è nel file [LICENSE](LICENSE).

In sintesi: sei libero di usare, modificare, ridistribuire e vendere il software, anche in prodotti proprietari, a condizione di mantenere la nota di copyright. Il software è fornito senza garanzie.

### Componenti di terze parti

La licenza MIT copre il codice di questo progetto. I componenti di terze parti mantengono le proprie licenze:

| Componente | Licenza |
|---|---|
| [PySide6 / Qt](https://www.qt.io/qt-for-python) | LGPLv3 (o commerciale) |
| [faster-whisper](https://github.com/SYSTRAN/faster-whisper) / CTranslate2 | MIT |
| [Whisper](https://github.com/openai/whisper) (modello) | MIT |
| [Silero VAD](https://github.com/snakers4/silero-vad) | MIT |
| [ONNX Runtime](https://github.com/microsoft/onnxruntime) | MIT |
| [NumPy](https://numpy.org/) · [soundfile](https://github.com/bastibe/python-soundfile) | BSD-3-Clause |
| [FFmpeg](https://ffmpeg.org/) | LGPLv2.1+ / GPLv2+ secondo la build |
| [PyInstaller](https://pyinstaller.org/) | GPLv2+ con eccezione per il bootloader |

FFmpeg viene invocato come processo esterno (`subprocess`) e non collegato al programma: la sua licenza non si estende quindi al codice di questo progetto, che resta MIT.

**Nota per chi ridistribuisce i binari.** Usare o compilare il progetto dal sorgente non comporta obblighi ulteriori. Se invece distribuisci una build `.app` / `.dmg` / `.exe` a terzi, tieni presente che il pacchetto include componenti con licenze copyleft:

- **Qt/PySide6** — la LGPLv3 richiede che l'utente finale possa sostituire le librerie Qt con una versione propria. Pubblicare il sorgente completo e gli script di build, come fa questo repository, va in questa direzione.
- **FFmpeg** — le build compilate con `--enable-gpl` sono GPL. Chi distribuisce un pacchetto che include un binario FFmpeg deve fornirne anche il codice sorgente corrispondente, o un'offerta scritta per ottenerlo (GPL, sezione 6). Il sorgente è disponibile su [ffmpeg.org](https://ffmpeg.org/download.html).

Gli script di setup installano FFmpeg dal gestore di pacchetti di sistema (Homebrew su macOS): in quel caso il binario non viene ridistribuito da questo progetto e l'obbligo non si applica.
