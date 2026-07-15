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

Il progetto è organizzato in più versioni che condividono lo stesso motore di trascrizione (`engine.py`) e differiscono per piattaforma di destinazione e adattamenti dell'interfaccia.

| Cartella | Piattaforma | Note |
|---|---|---|
| [`macos-arm/`](macos-arm/) | macOS Apple Silicon (M1/M2/M3…) | Versione di riferimento, sviluppo attivo |
| [`macos-intel/`](macos-intel/) | macOS Intel (x86_64, anche via Rosetta) | Stesso codice, build per architettura Intel |
| [`windows/`](windows/) | Windows 10/11 (x64) | Port Windows (font di sistema, build `.exe`, percorsi `%APPDATA%`) |
| [`legacy-v1/`](legacy-v1/) | macOS | Prima versione storica con interfaccia minimale e CLI, conservata come riferimento |

Ogni cartella contiene un proprio README con le istruzioni di setup dettagliate per quella piattaforma.

Struttura tipica di una versione:

```
<piattaforma>/
├── main.py                 # Entry point dell'applicazione
├── engine.py               # Motore di trascrizione (condiviso)
├── requirements.txt
├── core/                   # Modello dati, I/O sottotitoli, worker, player
└── ui/                     # Interfaccia PySide6 (finestra, editor, anteprima, ...)
```

---

## Requisiti

- **FFmpeg** (installato automaticamente dagli script di setup)
- **Python 3.10+** (3.11 consigliato)
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

Le istruzioni complete sono nel README di ciascuna cartella. In sintesi:

**macOS (Apple Silicon)**
```bash
cd macos-arm
chmod +x install.sh
./install.sh --run
```

**macOS (Intel)**
```bash
cd macos-intel
chmod +x install.sh
./install.sh --run
```

**Windows**
```bat
cd windows
setup_windows.bat --run
```

Lo script di setup installa FFmpeg, crea l'ambiente virtuale, installa le dipendenze e scarica il modello Whisper `large-v3` al primo avvio.

---

## Formati supportati

| Tipo | Formati |
|------|---------|
| Video | MP4, MKV, AVI, MOV, WebM |
| Audio | MP3, WAV, M4A, FLAC, OGG, AAC, WMA |

---

## Build distribuibile

- **macOS** — `python build_mac.py` → `.app` + `.dmg`
- **Windows** — `python build_windows.py` → `.exe`

Dettagli nei README delle rispettive cartelle.

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
