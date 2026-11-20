# Video → SRT — macOS (Apple Silicon and Intel)

Both architectures share `build_mac.py`, which detects `arm64` / `x86_64` with
`platform.machine()`. Each architecture has its own entry point:

| Mac | Build command | Python environment | FFmpeg bundled in the app |
|---|---|---|---|
| **Apple Silicon** (M1 and later) | `bash packaging/macos/apple-silicon/build.sh` | `.venv/` (arm64) | Homebrew FFmpeg from `PATH` |
| **Intel** (x86_64) | `bash packaging/macos/intel/build.sh` | `.venv-intel/` (x86_64) | static binary in `packaging/macos/intel/bin/ffmpeg` |

Created at the **repository root** and ignored by git: `.venv/`, `.venv-intel/`,
`_build_model/` (only for `--with-model`), `build/`, `dist/`.

| Script | Purpose |
|---|---|
| `install.sh` | Full setup (Homebrew, FFmpeg, Python, `.venv`, dependencies) with `--run`, `--app`, `--dmg` |
| `setup_mac.sh` | Minimal setup |
| `apple-silicon/build.sh` | Apple Silicon build |
| `intel/build.sh` | Intel build, runs `build_mac.py` under `arch -x86_64` |
| `build_mac.py` | Shared PyInstaller build of `dist/Video-to-SRT.app` (+ `.dmg` with `create-dmg`) |
| `build_installer.sh` | Builds `dist/Video-to-SRT-<version>-Installer.pkg` from an existing `.app` |
| `Installa-Video-to-SRT.command` | Double-click installer for end users |

## Development

```bash
packaging/macos/install.sh --run       # setup (.venv, dependencies) + launch
# or, with the venv already set up:
source .venv/bin/activate && python app/main.py
```

Requirements: macOS 12+, Python 3.10+, Homebrew (installed by the script if missing).

## Apple Silicon build

```bash
packaging/macos/install.sh --run                    # once: environment
bash packaging/macos/apple-silicon/build.sh         # .app + .dmg
bash packaging/macos/apple-silicon/build.sh --no-dmg
bash packaging/macos/apple-silicon/build.sh --with-model   # + large-v3 for offline installs
bash packaging/macos/apple-silicon/build.sh --sign "Developer ID Application: …"
```

`install.sh --app` / `--dmg` do setup and build in one go. The app ships **without** a Whisper
model: it recommends one for the computer and downloads it at the first transcription.
`--with-model` bundles large-v3 (~3 GB, from `_build_model/` or the Hugging Face cache) for
computers without internet. Only the Qt modules the app uses are bundled (no WebEngine, QML,
3D…). FFmpeg is bundled if found in `PATH` / Homebrew. For a `.pkg`, run `packaging/macos/build_installer.sh` after the build.

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

The script checks the venv and FFmpeg, and stops with an explanation if something is missing.

## Checks after every build

The build stops with an error if either check fails (`--skip-checks` to skip them):

1. **Libraries outside the bundle** (`check_bundle.py`): every Mach-O file is read with
   `otool -L`; a reference to `/opt/homebrew` or `/usr/local` means the app would not start on
   a Mac without Homebrew. Run it alone with `python3 packaging/macos/check_bundle.py`.
2. **Self-test of the built app**: `Video-to-SRT.app/Contents/MacOS/Video-to-SRT --self-test`,
   run with a `PATH` without Homebrew. It checks the bundled FFmpeg (filters and encoders),
   CTranslate2, the Silero VAD, Qt Multimedia/SVG and the fonts, and exports a small video with
   burned-in subtitles. Exit code 0 = passed. Any copy of the app can be checked the same way.

The **Build app** GitHub workflow (`.github/workflows/build.yml`: manual, on `v*` tags and
weekly) builds macOS (Apple Silicon) and Windows on clean runners, runs the same checks and
uploads the apps as artifacts.

## Signing and notarization

Without a Developer ID the app is only ad-hoc signed: downloaded on another Mac, Gatekeeper
blocks it ("damaged" / "unidentified developer"; workaround: right-click → Open, or
`xattr -dr com.apple.quarantine Video-to-SRT.app`). For a clean install you need an
**Apple Developer Program** membership and a *Developer ID Application* certificate in the
keychain (`security find-identity -v -p codesigning` lists it). Then, once:

```bash
# Apple ID, team ID and an app-specific password (appleid.apple.com): saved in the keychain
xcrun notarytool store-credentials videosrt-notary
```

and every release:

```bash
bash packaging/macos/apple-silicon/build.sh \
    --sign "Developer ID Application: Name (TEAMID)" --notarize videosrt-notary
```

The script signs every library and executable inside the app, then the bundle, with hardened
runtime, timestamp and `entitlements.plist` (Python and CTranslate2 need executable memory and
the bundled libraries); then it runs the self-test on the **signed** app, signs the DMG, sends
it to Apple, and staples the ticket to the DMG and the app. `--sign -` signs ad-hoc the same
way, to check locally that the hardened-runtime app still starts.

## Notes

- Without `app/assets/app.icns` the build uses the default icon.
