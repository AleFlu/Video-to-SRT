# Video → SRT — macOS (Apple Silicon and Intel)

Both architectures share `build_mac.py`, which detects `arm64` / `x86_64` with
`platform.machine()`. Each architecture has its own entry point:

| Mac | Build command | Python environment | FFmpeg bundled in the app |
|---|---|---|---|
| **Apple Silicon** (M1 and later) | `bash packaging/macos/apple-silicon/build.sh` | `.venv/` (arm64) | Homebrew FFmpeg from `PATH` |
| **Intel** (x86_64) | `bash packaging/macos/intel/build.sh` | `.venv-intel/` (x86_64) | static binary in `packaging/macos/intel/bin/ffmpeg` |

Created at the **repository root** and ignored by git: `.venv/`, `.venv-intel/`,
`_build_model/` (the Whisper model to bundle), `build/`, `dist/`.

| Script | Purpose |
|---|---|
| `install.sh` | Full setup (Homebrew, FFmpeg, Python, `.venv`, dependencies, model) with `--run`, `--app`, `--dmg` |
| `setup_mac.sh` | Minimal setup |
| `apple-silicon/build.sh` | Apple Silicon build |
| `intel/build.sh` | Intel build, runs `build_mac.py` under `arch -x86_64` |
| `build_mac.py` | Shared PyInstaller build of `dist/Video-to-SRT.app` (+ `.dmg` with `create-dmg`) |
| `build_installer.sh` | Builds `dist/Video-to-SRT-<version>-Installer.pkg` from an existing `.app` |
| `Installa-Video-to-SRT.command` | Double-click installer for end users |

## Development

```bash
packaging/macos/install.sh --run       # setup (.venv, dependencies, model) + launch
# or, with the venv already set up:
source .venv/bin/activate && python app/main.py
```

Requirements: macOS 12+, Python 3.10+, Homebrew (installed by the script if missing).

## Apple Silicon build

```bash
packaging/macos/install.sh --run                    # once: environment and model
bash packaging/macos/apple-silicon/build.sh         # .app + .dmg
bash packaging/macos/apple-silicon/build.sh --no-dmg
bash packaging/macos/apple-silicon/build.sh --sign "Developer ID Application: …"
```

`install.sh --app` / `--dmg` do setup and build in one go. The Whisper model is bundled if it
is in `_build_model/` (or the Hugging Face cache); FFmpeg is bundled if found in `PATH` /
Homebrew. For a `.pkg`, run `packaging/macos/build_installer.sh` after the build.

## Intel build

Needs an x86_64 virtual environment (on an Apple Silicon Mac too, through Rosetta) and a static
x86_64 FFmpeg. FFmpeg is **not in the repository**: it is a ~76 MB GPL binary, and
redistributing it would require providing its source code.

```bash
arch -x86_64 /usr/bin/python3 -m venv .venv-intel
arch -x86_64 .venv-intel/bin/pip install -r app/requirements.txt pyinstaller

mkdir -p packaging/macos/intel/bin
# Download the static x86_64 build from https://evermeet.cx/ffmpeg/ and save it as
# packaging/macos/intel/bin/ffmpeg
chmod +x packaging/macos/intel/bin/ffmpeg

bash packaging/macos/intel/build.sh
```

The script checks the venv, FFmpeg and the model, and stops with an explanation if something
is missing.

## Notes

- Without `app/assets/app.icns` the build uses the default icon.
- Signing and notarization are optional (`--sign`); unsigned apps trigger the Gatekeeper warning
  on first launch (right-click → Open).
