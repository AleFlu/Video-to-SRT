# Video → SRT — Packaging macOS (Apple Silicon e Intel)

Gli script di questa cartella funzionano per entrambe le architetture: `build_mac.py`
rileva `arm64` / `x86_64` con `platform.machine()`. Possono essere lanciati da
qualsiasi cartella; i percorsi sono risolti dalla posizione dello script.

## Layout

- Sorgenti dell'app: `app/` (entry point `app/main.py`, hook PyInstaller `app/pyi_rth_threads.py`).
- Creati nella **root del repository** (tutti ignorati da git): `.venv/` (Apple Silicon o dev),
  `.venv-intel/` (build Intel), `_build_model/` (modello Whisper da includere), `build/`, `dist/`.
- `packaging/macos/bin/ffmpeg`: ffmpeg statico x86_64, solo per la build Intel (non nel repo).

| Script | Scopo |
|---|---|
| `setup_mac.sh` | Setup minimale: Homebrew, ffmpeg, Python, `.venv`, dipendenze, modello |
| `install.sh` | Setup completo con opzioni `--run`, `--app`, `--dmg` |
| `build_mac.py` | Build PyInstaller di `dist/Video-to-SRT.app` (+ `.dmg` con `create-dmg`) |
| `build_intel.sh` | Wrapper che esegue `build_mac.py` come x86_64 (`arch -x86_64`) |
| `build_installer.sh` | Crea `dist/Video-to-SRT-<versione>-Installer.pkg` dalla `.app` già costruita |
| `Installa-Video-to-SRT.command` | Installer per l'utente finale (doppio clic) |

## Sviluppo

```bash
packaging/macos/install.sh --run       # setup (.venv, dipendenze, modello) + avvio
# oppure, con il venv già pronto:
source .venv/bin/activate && python app/main.py
```

Requisiti: macOS 12+, Python 3.10+, Homebrew (installato dallo script se manca).
FFmpeg viene installato via Homebrew.

## Build della .app

### Apple Silicon

```bash
packaging/macos/install.sh --app       # setup + build
packaging/macos/install.sh --dmg       # setup + build + .dmg (installa create-dmg)
# oppure manualmente, dal venv della root:
.venv/bin/python packaging/macos/build_mac.py --clean [--no-dmg] [--sign "Developer ID Application: …"]
```

Output in `dist/`. Per il `.pkg`: `packaging/macos/build_installer.sh` dopo la build.
Il modello Whisper viene incluso se presente in `_build_model/` (o nella cache HuggingFace);
ffmpeg viene incluso se trovato nel PATH / Homebrew.

### Intel (x86_64)

Serve un venv x86_64 (anche su Mac ARM, via Rosetta) e un FFmpeg statico x86_64, che
**non è incluso nel repository**: è un binario da ~76 MB con licenza GPL, e ridistribuirlo
comporterebbe l'obbligo di fornirne il codice sorgente.

```bash
arch -x86_64 /usr/bin/python3 -m venv .venv-intel
arch -x86_64 .venv-intel/bin/pip install -r app/requirements.txt pyinstaller

mkdir -p packaging/macos/bin
# Scarica il build statico x86_64 da https://evermeet.cx/ffmpeg/ e salvalo come packaging/macos/bin/ffmpeg
chmod +x packaging/macos/bin/ffmpeg

bash packaging/macos/build_intel.sh
```

`build_intel.sh` verifica venv, ffmpeg e modello e si ferma con un messaggio esplicativo
se manca qualcosa; poi lancia `build_mac.py --clean` sotto `arch -x86_64`.

## Note

- Se `app/assets/app.icns` manca la build usa l'icona di default.
- Firma e notarizzazione sono opzionali (`--sign`); senza firma macOS mostrerà l'avviso Gatekeeper.
