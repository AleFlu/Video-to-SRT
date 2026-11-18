# Packaging

One codebase (`app/`) builds for every platform. This folder only holds the setup and build
scripts for each target. Every script resolves paths from its own location, so you can run it
from any directory. Output goes to `build/` and `dist/` at the repository root.

| Platform | Setup + run (development) | Build | Output |
|---|---|---|---|
| **macOS · Apple Silicon** (M1 and later) | `packaging/macos/install.sh --run` | `bash packaging/macos/apple-silicon/build.sh` | `dist/Video-to-SRT.app`, `dist/Video-to-SRT-<version>-macOS-arm64.dmg` |
| **macOS · Intel** (x86_64) | `packaging/macos/install.sh --run` | `bash packaging/macos/intel/build.sh` | `dist/Video-to-SRT.app`, `dist/Video-to-SRT-<version>-macOS-intel.dmg` |
| **Windows** 10/11 x64 | `packaging\windows\setup_windows.bat --run` | `python packaging\windows\build_windows.py` | `dist\VideoSRT\VideoSRT.exe` |

```
packaging/
├── macos/
│   ├── apple-silicon/build.sh      Apple Silicon build (arm64)
│   ├── intel/build.sh              Intel build (x86_64, also from an Apple Silicon Mac via Rosetta)
│   ├── build_mac.py                shared PyInstaller build used by both
│   ├── install.sh                  full setup: Homebrew, FFmpeg, venv, model (+ --run / --app / --dmg)
│   ├── setup_mac.sh                minimal setup
│   ├── build_installer.sh          .pkg installer from an existing .app
│   └── Installa-Video-to-SRT.command   double-click installer for end users
└── windows/
    ├── setup_windows.bat           setup: venv, dependencies, model (+ --run)
    └── build_windows.py            PyInstaller build of the .exe
```

Details: [macOS](macos/README.md) · [Windows](windows/README.md).
