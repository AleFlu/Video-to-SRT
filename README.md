# Video → SRT

Trascrive in **italiano** video e audio e crea sottotitoli `.srt` pronti per il montaggio,
con un editor per rivederli riga per riga. Tutto gira **sul tuo computer**: nessun file
viene caricato in rete e, dopo il primo setup, l'app funziona offline.

![Video → SRT: dal file alla trascrizione, all'editor, all'esportazione](docs/media/demo.gif)

<sub>Demo registrata con una voce sintetica: avanzamento della trascrizione accelerato, il resto è l'app reale.</sub>

---

## Cosa fa

**Trascrizione**
- Modello Whisper `large-v3` via [faster-whisper](https://github.com/SYSTRAN/faster-whisper), timestamp parola per parola
- Riduzione del rumore e filtro VAD per saltare i silenzi (meno frasi inventate); i tratti di parlato saltati per errore vengono recuperati
- **Glossario** per termini inglesi, marchi e nomi propri (`iPhone`, `deploy`, `social media`…), con la punteggiatura italiana preservata
- Sottotitoli composti secondo le regole di leggibilità professionali: 42 caratteri per riga, 2 righe, 17 caratteri al secondo, durata tra 0,83 e 7 s, a capo senza lasciare articoli e preposizioni a fine riga

**Editor**
- Tabella modificabile e Ispettore con tempi al millisecondo, annulla/ripristina illimitato
- Dividi, unisci, elimina, trova e sostituisci
- Diagnostica in tempo reale: sovrapposizioni, sottotitoli troppo veloci, troppo corti o troppo lunghi
- Anteprima video con i sottotitoli sovrapposti e forma d'onda interattiva:
  clic per spostarti, rotella o due dita per scorrere, ⌘ + rotella o pizzico per lo zoom
- Scorciatoie da montatore (Spazio, J/K/L, frecce), tutte usabili anche da tastiera con focus visibile

**Esportazione**
- SRT, WebVTT, TXT, ASS e progetto `.v2srt` (riapribile e modificabile)
- Copia diretta per YouTube Studio, Vimeo, Premiere Pro / DaVinci Resolve

**Altro**
- Più progetti aperti in tab, tema chiaro e scuro, salvataggio automatico
- **Profili dei parametri** (`.vsrtconfig`): *File → Importa / Esporta configurazione* per salvare e condividere glossario, prompt, VAD e limiti di leggibilità
- macOS (Apple Silicon e Intel) e Windows

---

## Come funziona

```
file video/audio
   │  FFmpeg: estrazione audio a 16 kHz + riduzione del rumore
   ▼
Silero VAD ──► tratti di parlato
   │
   ▼
faster-whisper large-v3 (italiano, beam search, prompt + glossario)
   │  parole con tempi e probabilità
   ▼
recupero dei tratti saltati ──► composizione dei sottotitoli (righe, durata, CPS)
   │
   ▼
editor ──► esportazione SRT / VTT / TXT / ASS
```

| Componente | Tecnologia |
|---|---|
| Riconoscimento vocale | faster-whisper (CTranslate2), modello Whisper `large-v3` |
| Rilevamento del parlato | Silero VAD |
| Audio e video | FFmpeg, Qt Multimedia |
| Interfaccia | PySide6 (Qt 6) |
| Pacchetti | PyInstaller (`.app` / `.dmg`, `.exe`) |

---

## Requisiti

- **8 GB di RAM** (il modello `large-v3` ne usa circa 6; ci sono modelli più leggeri)
- **4–10 GB di spazio** per modello e dipendenze
- **FFmpeg** (lo installano gli script di setup)
- **Python 3.10+** per lo sviluppo (3.11 consigliato; il codice resta compatibile con 3.9)
- Internet **solo** al primo avvio, per scaricare dipendenze e modello

| Modello | RAM | Qualità in italiano | Quando usarlo |
|---|---|---|---|
| `tiny` · `base` | ~1 GB | ★☆☆☆☆ · ★★☆☆☆ | Prove veloci |
| `small` | ~2 GB | ★★★☆☆ | Computer con poca memoria |
| `medium` | ~5 GB | ★★★★☆ | Buona alternativa |
| **`large-v3`** | **~6 GB** | **★★★★★** | **Predefinito** |
| `large-v3-turbo` | ~4 GB | ★★★★½ | Più veloce, quasi la stessa qualità |

**Formati in ingresso:** MP4, MOV, MKV, AVI, WebM, M4V · MP3, WAV, M4A, FLAC, OGG, AAC, WMA · SRT e `.v2srt` per riaprire un lavoro.

---

## Installazione e avvio

**Setup guidato** (FFmpeg, ambiente Python, dipendenze e modello):

```bash
packaging/macos/install.sh --run
```

```bat
packaging\windows\setup_windows.bat --run
```

**A mano**, dalla cartella del repository:

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r app/requirements.txt -r requirements-dev.txt
python app/main.py
```

FFmpeg deve essere nel `PATH` (macOS: `brew install ffmpeg`; Windows: vedi [`packaging/windows/README.md`](packaging/windows/README.md)).
Il modello si scarica al primo utilizzo.

---

## Scorciatoie principali

⌘ su macOS, Ctrl su Windows e Linux.

| Tasti | Azione |
|---|---|
| ⌘O · ⌘N | Apri file · nuova trascrizione |
| Spazio · J / K / L | Play/pausa · indietro 2 s / pausa / play |
| ← / → · ⇧← / ⇧→ | ±1 s · sottotitolo precedente / successivo |
| ⌘K · ⌘M · ⌘⇧K | Dividi · unisci col successivo · elimina |
| ⌘Z · ⌘⇧Z | Annulla · ripristina |
| ⌘F · ⌘⌥F | Cerca · trova e sostituisci |
| ⌘I | Mostra/nascondi l'Ispettore |
| ⌘S · ⌘⇧S · ⌘E | Esporta SRT · salva progetto · scheda Esportazione |
| ⌘⇧T · ⌘W · ⌃Tab | Nuovo tab · chiudi tab · tab successivo |
| ⌘⇧L | Tema chiaro/scuro |

L'elenco completo, con i casi particolari, è in [`CLAUDE.md`](CLAUDE.md).

---

## Sviluppo

```
app/
├── main.py               avvio
├── engine.py             pipeline di trascrizione
├── platform_support.py   tutto ciò che dipende dal sistema operativo
├── core/                 modello dei sottotitoli, composizione, I/O, configurazione, player
├── ui/                   interfaccia PySide6
└── tests/                test pytest (UI offscreen)
packaging/                build per macOS e Windows
docs/                     specifiche, piani, riferimenti di design
legacy-v1/                prima versione, solo come riferimento
```

```bash
QT_QPA_PLATFORM=offscreen python -m pytest -q    # Windows (cmd): set QT_QPA_PLATFORM=offscreen
ruff check app
```

La CI (GitHub Actions) esegue lint e test su macOS, Windows e Linux. Le regole di architettura sono in [`CLAUDE.md`](CLAUDE.md).

### Build distribuibile

- **macOS Apple Silicon:** `packaging/macos/install.sh --app` (oppure `--dmg`)
- **macOS Intel:** `bash packaging/macos/build_intel.sh`
- **Windows:** `python packaging\windows\build_windows.py` → `dist\VideoSRT\VideoSRT.exe`

Dettagli in [`packaging/macos/README.md`](packaging/macos/README.md) e [`packaging/windows/README.md`](packaging/windows/README.md).

---

## Licenza

**MIT**: puoi usare, modificare, ridistribuire e vendere il software, anche in prodotti proprietari, mantenendo la nota di copyright. Testo completo in [LICENSE](LICENSE). Il software è fornito senza garanzie.

### Componenti di terze parti

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

FFmpeg viene eseguito come processo esterno, non collegato al programma: la sua licenza non si estende al codice di questo progetto, che resta MIT.

**Se ridistribuisci i binari** (`.app` / `.dmg` / `.exe`), il pacchetto contiene componenti copyleft:

- **Qt/PySide6** — la LGPLv3 chiede che l'utente possa sostituire le librerie Qt con una propria versione; pubblicare sorgente e script di build, come fa questo repository, va in questa direzione.
- **FFmpeg** — le build con `--enable-gpl` sono GPL: chi distribuisce un pacchetto che include FFmpeg deve fornirne anche il sorgente o un'offerta scritta per ottenerlo (GPL, sezione 6). Il sorgente è su [ffmpeg.org](https://ffmpeg.org/download.html).

Gli script di setup installano FFmpeg con il gestore di pacchetti del sistema (Homebrew su macOS): in quel caso il binario non viene ridistribuito da questo progetto e l'obbligo non si applica.
